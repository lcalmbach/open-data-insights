from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Iterable

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction


DEFAULT_SOURCE = "oilpriceapi_historical"
DEFAULT_MAPPINGS = [
    {"code": "WTI_USD", "commodity": "WTI", "unit": "barrel", "market": "NYMEX"},
    {"code": "BRENT_CRUDE_USD", "commodity": "Brent Crude", "unit": "barrel", "market": "ICE"},
]


@dataclass(frozen=True)
class CommodityMapping:
    code: str
    commodity: str
    unit: str
    market: str | None = None


@dataclass(frozen=True)
class MonthlyCommodityPrice:
    commodity: str
    commodity_code: str
    year: int
    month: int
    market: str | None
    price: Decimal
    currency: str
    unit: str
    quote_type: str
    source: str
    price_timestamp: datetime
    metadata: dict


def _parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _parse_mapping(value: str) -> CommodityMapping:
    parts = [part.strip() for part in value.split("|")]
    if len(parts) not in {3, 4}:
        raise CommandError(
            "Invalid --mapping value. Use 'CODE|Commodity|Unit|Market' or 'CODE|Commodity|Unit'."
        )
    code, commodity, unit = parts[:3]
    market = parts[3] if len(parts) == 4 and parts[3] else None
    if not code or not commodity or not unit:
        raise CommandError("Mapping fields code, commodity, and unit are required.")
    return CommodityMapping(code=code, commodity=commodity, unit=unit, market=market)


def _fetch_historical_prices(
    *,
    api_key: str,
    commodity_code: str,
    start_date: date,
    end_date: date,
    timeout: int = 60,
) -> list[dict]:
    session = requests.Session()
    session.headers.update({"Authorization": f"Token {api_key}"})
    all_prices: list[dict] = []
    current_day = start_date

    while current_day <= end_date:
        response = session.get(
            "https://api.oilpriceapi.com/v1/prices/historical",
            params={
                "by_code": commodity_code,
                "start_date": current_day.isoformat(),
                "end_date": current_day.isoformat(),
            },
            timeout=timeout,
        )
        if not response.ok:
            message = f"OilPriceAPI request failed for {commodity_code} on {current_day.isoformat()}: HTTP {response.status_code}"
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if isinstance(payload, dict):
                error_payload = payload.get("error")
                if isinstance(error_payload, dict):
                    detail = error_payload.get("message") or error_payload.get("code")
                    if detail:
                        message = f"{message} - {detail}"
                elif isinstance(error_payload, str) and error_payload:
                    message = f"{message} - {error_payload}"
            raise CommandError(message)
        payload = response.json()
        prices = payload.get("data", {}).get("prices")
        if not isinstance(prices, list):
            raise CommandError(f"Unexpected OilPriceAPI response for {commodity_code}: missing data.prices list.")
        all_prices.extend(prices)
        current_day += timedelta(days=1)

    return all_prices


def _build_daily_series(prices: Iterable[dict]) -> list[dict]:
    daily_best: dict[date, tuple[int, datetime, dict]] = {}

    for price_row in prices:
        created_at_raw = price_row.get("created_at")
        if not created_at_raw or "price" not in price_row:
            continue
        created_at = _parse_iso_datetime(created_at_raw)
        price_date = created_at.date()
        quote_type = price_row.get("type", "")
        priority = 0 if quote_type == "daily_average_price" else 1
        candidate = (priority, created_at, price_row)
        current = daily_best.get(price_date)
        if current is None or candidate < current:
            daily_best[price_date] = candidate

    return [daily_best[price_key][2] for price_key in sorted(daily_best)]


def _aggregate_monthly_prices(mapping: CommodityMapping, prices: Iterable[dict]) -> list[MonthlyCommodityPrice]:
    monthly_buckets: dict[tuple[int, int], list[dict]] = {}
    for row in _build_daily_series(prices):
        created_at = _parse_iso_datetime(row["created_at"])
        month_key = (created_at.year, created_at.month)
        monthly_buckets.setdefault(month_key, []).append(row)

    monthly_rows: list[MonthlyCommodityPrice] = []
    for year, month in sorted(monthly_buckets):
        rows = monthly_buckets[(year, month)]
        numeric_prices = [Decimal(str(row["price"])) for row in rows]
        average_price = sum(numeric_prices) / Decimal(len(numeric_prices))
        currencies = sorted({row.get("currency") or "" for row in rows if row.get("currency")})
        raw_sources = sorted({row.get("source") or "" for row in rows if row.get("source")})
        row_currency = currencies[0] if currencies else "USD"
        price_timestamp = datetime(year, month, 1, tzinfo=UTC)
        monthly_rows.append(
            MonthlyCommodityPrice(
                commodity=mapping.commodity,
                commodity_code=mapping.code,
                year=year,
                month=month,
                market=mapping.market,
                price=average_price.quantize(Decimal("0.000001")),
                currency=row_currency,
                unit=mapping.unit,
                quote_type="monthly_average",
                source=DEFAULT_SOURCE,
                price_timestamp=price_timestamp,
                metadata={
                    "aggregation": "monthly_average",
                    "daily_points": len(rows),
                    "period_month": f"{year:04d}-{month:02d}",
                    "raw_quote_types": sorted({row.get("type") or "" for row in rows if row.get("type")}),
                    "raw_sources": raw_sources,
                },
            )
        )
    return monthly_rows


def _upsert_monthly_prices(rows: Iterable[MonthlyCommodityPrice]) -> int:
    inserted = 0
    with transaction.atomic():
        with connection.cursor() as cursor:
            for row in rows:
                cursor.execute(
                    """
                    INSERT INTO opendata.commodity_price (
                        commodity,
                        commodity_code,
                        year,
                        month,
                        market,
                        price,
                        currency,
                        unit,
                        quote_type,
                        source,
                        price_timestamp,
                        metadata
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (commodity_code, source, price_timestamp)
                    WHERE commodity_code IS NOT NULL
                    DO UPDATE SET
                        commodity = EXCLUDED.commodity,
                        year = EXCLUDED.year,
                        month = EXCLUDED.month,
                        market = EXCLUDED.market,
                        price = EXCLUDED.price,
                        currency = EXCLUDED.currency,
                        unit = EXCLUDED.unit,
                        quote_type = EXCLUDED.quote_type,
                        metadata = EXCLUDED.metadata,
                        retrieved_at = NOW()
                    """,
                    [
                        row.commodity,
                        row.commodity_code,
                        row.year,
                        row.month,
                        row.market,
                        row.price,
                        row.currency,
                        row.unit,
                        row.quote_type,
                        row.source,
                        row.price_timestamp,
                        json.dumps(row.metadata),
                    ],
                )
                inserted += 1
    return inserted


class Command(BaseCommand):
    help = "Import monthly commodity price aggregates from OilPriceAPI historical data into opendata.commodity_price."

    def add_arguments(self, parser):
        parser.add_argument(
            "--start-date",
            type=str,
            required=True,
            help="Inclusive start date in YYYY-MM-DD format.",
        )
        parser.add_argument(
            "--end-date",
            type=str,
            required=True,
            help="Inclusive end date in YYYY-MM-DD format.",
        )
        parser.add_argument(
            "--mapping",
            action="append",
            help="Commodity mapping in the form 'CODE|Commodity|Unit|Market'. Can be passed multiple times.",
        )
        parser.add_argument(
            "--api-key",
            type=str,
            help="Override OILPRICEAPI_KEY for this run.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and aggregate without writing to the database.",
        )

    def handle(self, *args, **options):
        api_key = options.get("api_key") or os.environ.get("OILPRICEAPI_KEY")
        if not api_key:
            raise CommandError("Set OILPRICEAPI_KEY or pass --api-key.")

        try:
            start_date = date.fromisoformat(options["start_date"])
            end_date = date.fromisoformat(options["end_date"])
        except ValueError as exc:
            raise CommandError(f"Invalid date: {exc}") from exc

        if start_date > end_date:
            raise CommandError("--start-date must be on or before --end-date.")

        mappings = [_parse_mapping(value) for value in (options.get("mapping") or [])]
        if not mappings:
            mappings = [CommodityMapping(**mapping) for mapping in DEFAULT_MAPPINGS]

        total_rows = 0
        for mapping in mappings:
            self.stdout.write(
                f"Fetching {mapping.code} from {start_date.isoformat()} to {end_date.isoformat()}..."
            )
            prices = _fetch_historical_prices(
                api_key=api_key,
                commodity_code=mapping.code,
                start_date=start_date,
                end_date=end_date,
            )
            monthly_rows = _aggregate_monthly_prices(mapping, prices)
            total_rows += len(monthly_rows)

            if options.get("dry_run"):
                self.stdout.write(
                    self.style.WARNING(
                        f"Dry run: prepared {len(monthly_rows)} monthly rows for {mapping.code}."
                    )
                )
                continue

            written = _upsert_monthly_prices(monthly_rows)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Imported {written} monthly rows for {mapping.code}."
                )
            )

        if options.get("dry_run"):
            self.stdout.write(self.style.SUCCESS(f"Dry run complete. Prepared {total_rows} rows."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Import complete. Wrote {total_rows} rows."))
