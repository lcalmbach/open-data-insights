from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
import requests
from django.core.management.base import CommandError


DEFAULT_DATASET_LABEL = "eia_pet_pri_spt_s1_d"
EIA_API_URL = "https://api.eia.gov/v2/petroleum/pri/spt/data/"


@dataclass(frozen=True)
class SeriesConfig:
    commodity: str
    series: str
    market: str
    unit: str
    description: str


AVAILABLE_SERIES = [
    SeriesConfig(
        commodity="WTI Crude",
        series="RWTC",
        market="Cushing, OK",
        unit="barrel",
        description="Cushing, OK WTI Spot Price FOB (Dollars per Barrel)",
    ),
    SeriesConfig(
        commodity="Brent Crude",
        series="RBRTE",
        market="Europe",
        unit="barrel",
        description="Europe Brent Spot Price FOB (Dollars per Barrel)",
    ),
    SeriesConfig(
        commodity="Conventional Gasoline Regular",
        series="EER_EPMRU_PF4_Y35NY_DPG",
        market="New York Harbor",
        unit="gallon",
        description="New York Harbor Conventional Gasoline Regular Spot Price FOB (Dollars per Gallon)",
    ),
    SeriesConfig(
        commodity="Conventional Gasoline Regular",
        series="EER_EPMRU_PF4_RGC_DPG",
        market="U.S. Gulf Coast",
        unit="gallon",
        description="U.S. Gulf Coast Conventional Gasoline Regular Spot Price FOB (Dollars per Gallon)",
    ),
    SeriesConfig(
        commodity="RBOB Regular Gasoline",
        series="EER_EPMRR_PF4_Y05LA_DPG",
        market="Los Angeles, CA",
        unit="gallon",
        description="Los Angeles Reformulated RBOB Regular Gasoline Spot Price (Dollars per Gallon)",
    ),
    SeriesConfig(
        commodity="No. 2 Heating Oil",
        series="EER_EPD2F_PF4_Y35NY_DPG",
        market="New York Harbor",
        unit="gallon",
        description="New York Harbor No. 2 Heating Oil Spot Price FOB (Dollars per Gallon)",
    ),
    SeriesConfig(
        commodity="Ultra-Low Sulfur No. 2 Diesel",
        series="EER_EPD2DXL0_PF4_Y35NY_DPG",
        market="New York Harbor",
        unit="gallon",
        description="New York Harbor Ultra-Low Sulfur No 2 Diesel Spot Price (Dollars per Gallon)",
    ),
    SeriesConfig(
        commodity="Ultra-Low Sulfur No. 2 Diesel",
        series="EER_EPD2DXL0_PF4_RGC_DPG",
        market="U.S. Gulf Coast",
        unit="gallon",
        description="U.S. Gulf Coast Ultra-Low Sulfur No 2 Diesel Spot Price (Dollars per Gallon)",
    ),
    SeriesConfig(
        commodity="Ultra-Low Sulfur CARB Diesel",
        series="EER_EPD2DC_PF4_Y05LA_DPG",
        market="Los Angeles, CA",
        unit="gallon",
        description="Los Angeles, CA Ultra-Low Sulfur CARB Diesel Spot Price (Dollars per Gallon)",
    ),
    SeriesConfig(
        commodity="Kerosene-Type Jet Fuel",
        series="EER_EPJK_PF4_RGC_DPG",
        market="U.S. Gulf Coast",
        unit="gallon",
        description="U.S. Gulf Coast Kerosene-Type Jet Fuel Spot Price FOB (Dollars per Gallon)",
    ),
    SeriesConfig(
        commodity="Propane",
        series="EER_EPLLPA_PF4_Y44MB_DPG",
        market="Mont Belvieu, TX",
        unit="gallon",
        description="Mont Belvieu, TX Propane Spot Price FOB (Dollars per Gallon)",
    ),
]
SERIES = AVAILABLE_SERIES
SERIES_REGISTRY = {series.series: series for series in AVAILABLE_SERIES}
DEFAULT_SERIES_CODES = ("RWTC", "RBRTE")
DEFAULT_SERIES = [SERIES_REGISTRY[series_code] for series_code in DEFAULT_SERIES_CODES]


def resolve_series_configs(series_selection: list[Any] | None = None) -> list[SeriesConfig]:
    if not series_selection:
        return list(AVAILABLE_SERIES)

    resolved: list[SeriesConfig] = []
    for item in series_selection:
        if isinstance(item, str):
            series = SERIES_REGISTRY.get(item.strip().upper())
            if series is None:
                raise CommandError(
                    f"Unsupported EIA series code {item!r}. "
                    "Use a dict with explicit metadata or add it to the registry."
                )
            resolved.append(series)
            continue

        if isinstance(item, dict):
            series_code = (item.get("series") or item.get("commodity_code") or "").strip()
            commodity = (item.get("commodity") or item.get("name") or "").strip()
            market = (item.get("market") or "").strip()
            unit = (item.get("unit") or "barrel").strip()
            description = (item.get("description") or commodity or series_code).strip()
            if not series_code or not commodity or not market:
                raise CommandError(
                    "Custom EIA series configs require 'series', 'commodity', and 'market'."
                )
            resolved.append(
                SeriesConfig(
                    commodity=commodity,
                    series=series_code,
                    market=market,
                    unit=unit,
                    description=description,
                )
            )
            continue

        raise CommandError(
            "EIA series selection must be a list of series codes or metadata dicts."
        )

    return resolved


def list_available_series() -> list[dict[str, str]]:
    return [
        {
            "series": series.series,
            "commodity": series.commodity,
            "market": series.market,
            "unit": series.unit,
            "description": series.description,
        }
        for series in AVAILABLE_SERIES
    ]


def _fetch_eia_daily_rows(
    *,
    api_url: str,
    api_key: str,
    series_configs: list[SeriesConfig],
    start_date: date | None,
    end_date: date | None,
) -> dict[str, list[tuple[date, Decimal]]]:
    result = {series.series: [] for series in series_configs}
    for series in series_configs:
        offset = 0
        page_size = 5000
        while True:
            params = [
                ("api_key", api_key),
                ("frequency", "daily"),
                ("data[0]", "value"),
                ("facets[series][]", series.series),
                ("sort[0][column]", "period"),
                ("sort[0][direction]", "asc"),
                ("offset", str(offset)),
                ("length", str(page_size)),
            ]
            if start_date:
                params.append(("start", start_date.isoformat()))
            if end_date:
                params.append(("end", end_date.isoformat()))
            response = requests.get(api_url, params=params, timeout=60)
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError as exc:
                content_type = response.headers.get("content-type", "")
                body_preview = " ".join(response.text.split())[:200]
                raise CommandError(
                    "EIA source_url did not return JSON. "
                    f"URL: {response.url} | content-type: {content_type or 'unknown'} | "
                    f"body preview: {body_preview!r}"
                ) from exc
            data = payload.get("response", {}).get("data", [])
            for row in data:
                raw_period = row.get("period")
                raw_value = row.get("value")
                if not raw_period or raw_value in {None, ""}:
                    continue
                try:
                    period = date.fromisoformat(raw_period)
                    price = Decimal(str(raw_value))
                except (ValueError, TypeError):
                    continue
                result[series.series].append((period, price))

            if len(data) < page_size:
                break
            offset += page_size
    return result


def _build_daily_rows(
    series: SeriesConfig,
    daily_rows: list[tuple[date, Decimal]],
    *,
    source_label: str = DEFAULT_DATASET_LABEL,
) -> list[dict]:
    rows: list[dict] = []
    for price_date, price in sorted(daily_rows):
        rows.append(
            {
                "commodity": series.commodity,
                "commodity_code": series.series,
                "year": price_date.year,
                "month": price_date.month,
                "market": series.market,
                "price": price.quantize(Decimal("0.000001")),
                "currency": "USD",
                "unit": series.unit,
                "quote_type": "daily_close",
                "source": source_label,
                "price_timestamp": datetime(
                    price_date.year, price_date.month, price_date.day, tzinfo=UTC
                ),
            }
        )
    return rows


def _recent_cutoff_date(*, as_of: date | None = None, days: int = 7) -> date:
    anchor = as_of or datetime.now(UTC).date()
    return anchor - timedelta(days=days - 1)


def _filter_recent_daily_rows(
    daily_rows: dict[str, list[tuple[date, Decimal]]],
    *,
    as_of: date | None = None,
    days: int = 7,
) -> dict[str, list[tuple[date, Decimal]]]:
    cutoff = _recent_cutoff_date(as_of=as_of, days=days)
    return {
        series_code: [row for row in rows if row[0] >= cutoff]
        for series_code, rows in daily_rows.items()
    }


def fetch_eia_prices_df(
    *,
    api_url: str = EIA_API_URL,
    source_label: str = DEFAULT_DATASET_LABEL,
    series_selection: list[Any] | None = None,
    recent_days: int | None = None,
    logger: logging.Logger | None = None,
) -> pd.DataFrame:
    logger = logger or logging.getLogger(__name__)
    end_date = datetime.now(UTC).date()
    start_date = end_date - timedelta(days=recent_days - 1) if recent_days else None
    api_key = os.getenv("EIA_API_KEY")
    if not api_key:
        raise CommandError("Set EIA_API_KEY in the environment before syncing EIA data.")
    series_configs = resolve_series_configs(series_selection)
    logger.info("Importing EIA prices from API %s", api_url)

    daily_rows = _fetch_eia_daily_rows(
        api_url=api_url,
        api_key=api_key,
        series_configs=series_configs,
        start_date=start_date,
        end_date=end_date,
    )
    if recent_days:
        daily_rows = _filter_recent_daily_rows(daily_rows, days=recent_days)

    rows: list[dict] = []
    for series in series_configs:
        rows.extend(
            _build_daily_rows(
                series,
                daily_rows.get(series.series, []),
                source_label=source_label,
            )
        )

    columns = [
        "commodity",
        "commodity_code",
        "year",
        "month",
        "market",
        "price",
        "currency",
        "unit",
        "quote_type",
        "source",
        "price_timestamp",
    ]
    return pd.DataFrame(rows, columns=columns)
