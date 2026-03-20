from __future__ import annotations

import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils.dateparse import parse_date, parse_datetime


DEFAULT_SOURCE_PATH = Path("work/oil/market_events_seed.csv")


def _split_list(value: str) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(";") if item.strip()]


def _parse_bool(value: str) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y"}


def _parse_int(value: str) -> int | None:
    value = (value or "").strip()
    return int(value) if value else None


class Command(BaseCommand):
    help = "Import market events from a CSV seed file into opendata.market_events."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            type=str,
            default=str(DEFAULT_SOURCE_PATH),
            help="Path to the market events CSV file.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse the CSV without writing to the database.",
        )

    def handle(self, *args, **options):
        source_path = Path(options["source"]).expanduser()
        if not source_path.exists():
            raise CommandError(f"CSV file not found: {source_path}")

        rows = list(self._load_rows(source_path))
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING(f"Dry run: parsed {len(rows)} market events."))
            return

        written = self._upsert_rows(rows)
        self.stdout.write(self.style.SUCCESS(f"Imported {written} market events."))

    def _load_rows(self, source_path: Path):
        with source_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            required = {
                "event_key",
                "event_date",
                "title",
                "event_type",
                "commodities",
            }
            missing = required - set(reader.fieldnames or [])
            if missing:
                raise CommandError(
                    f"CSV is missing required columns: {', '.join(sorted(missing))}"
                )

            for raw in reader:
                event_date = parse_date((raw.get("event_date") or "").strip())
                if event_date is None:
                    raise CommandError(f"Invalid event_date for event_key={raw.get('event_key')}")

                event_end_date_raw = (raw.get("event_end_date") or "").strip()
                event_end_date = parse_date(event_end_date_raw) if event_end_date_raw else None
                source_published_at_raw = (raw.get("source_published_at") or "").strip()
                source_published_at = (
                    parse_datetime(source_published_at_raw) if source_published_at_raw else None
                )

                yield {
                    "event_key": (raw.get("event_key") or "").strip(),
                    "event_date": event_date,
                    "event_end_date": event_end_date,
                    "title": (raw.get("title") or "").strip(),
                    "event_type": (raw.get("event_type") or "").strip(),
                    "category": (raw.get("category") or "").strip() or None,
                    "region": (raw.get("region") or "").strip() or None,
                    "countries": _split_list(raw.get("countries") or ""),
                    "commodities": _split_list(raw.get("commodities") or ""),
                    "summary": (raw.get("summary") or "").strip() or None,
                    "impact_direction_oil": (raw.get("impact_direction_oil") or "").strip() or None,
                    "impact_direction_gold": (raw.get("impact_direction_gold") or "").strip() or None,
                    "impact_magnitude": (raw.get("impact_magnitude") or "").strip() or None,
                    "relevance_score": _parse_int(raw.get("relevance_score") or ""),
                    "is_geopolitical": _parse_bool(raw.get("is_geopolitical") or ""),
                    "is_supply_shock": _parse_bool(raw.get("is_supply_shock") or ""),
                    "is_demand_shock": _parse_bool(raw.get("is_demand_shock") or ""),
                    "source_name": (raw.get("source_name") or "").strip() or None,
                    "source_url": (raw.get("source_url") or "").strip() or None,
                    "source_published_at": source_published_at,
                    "confidence": (raw.get("confidence") or "").strip() or None,
                    "tags": _split_list(raw.get("tags") or ""),
                    "notes": (raw.get("notes") or "").strip() or None,
                }

    def _upsert_rows(self, rows) -> int:
        count = 0
        with transaction.atomic():
            with connection.cursor() as cursor:
                for row in rows:
                    cursor.execute(
                        """
                        INSERT INTO opendata.market_events (
                            event_key,
                            event_date,
                            event_end_date,
                            title,
                            event_type,
                            category,
                            region,
                            countries,
                            commodities,
                            summary,
                            impact_direction_oil,
                            impact_direction_gold,
                            impact_magnitude,
                            relevance_score,
                            is_geopolitical,
                            is_supply_shock,
                            is_demand_shock,
                            source_name,
                            source_url,
                            source_published_at,
                            confidence,
                            tags,
                            notes
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s::text[], %s::text[], %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::text[], %s
                        )
                        ON CONFLICT (event_key) DO UPDATE SET
                            event_date = EXCLUDED.event_date,
                            event_end_date = EXCLUDED.event_end_date,
                            title = EXCLUDED.title,
                            event_type = EXCLUDED.event_type,
                            category = EXCLUDED.category,
                            region = EXCLUDED.region,
                            countries = EXCLUDED.countries,
                            commodities = EXCLUDED.commodities,
                            summary = EXCLUDED.summary,
                            impact_direction_oil = EXCLUDED.impact_direction_oil,
                            impact_direction_gold = EXCLUDED.impact_direction_gold,
                            impact_magnitude = EXCLUDED.impact_magnitude,
                            relevance_score = EXCLUDED.relevance_score,
                            is_geopolitical = EXCLUDED.is_geopolitical,
                            is_supply_shock = EXCLUDED.is_supply_shock,
                            is_demand_shock = EXCLUDED.is_demand_shock,
                            source_name = EXCLUDED.source_name,
                            source_url = EXCLUDED.source_url,
                            source_published_at = EXCLUDED.source_published_at,
                            confidence = EXCLUDED.confidence,
                            tags = EXCLUDED.tags,
                            notes = EXCLUDED.notes,
                            updated_at = NOW()
                        """,
                        [
                            row["event_key"],
                            row["event_date"],
                            row["event_end_date"],
                            row["title"],
                            row["event_type"],
                            row["category"],
                            row["region"],
                            row["countries"],
                            row["commodities"],
                            row["summary"],
                            row["impact_direction_oil"],
                            row["impact_direction_gold"],
                            row["impact_magnitude"],
                            row["relevance_score"],
                            row["is_geopolitical"],
                            row["is_supply_shock"],
                            row["is_demand_shock"],
                            row["source_name"],
                            row["source_url"],
                            row["source_published_at"],
                            row["confidence"],
                            row["tags"],
                            row["notes"],
                        ],
                    )
                    count += 1
        return count
