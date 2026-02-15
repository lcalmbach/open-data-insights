from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from reports.models.story_template import StoryTemplate, StoryTemplateFocus


@dataclass(frozen=True)
class _Row:
    bfs_nummer: str
    gemeinde: str


class Command(BaseCommand):
    help = (
        "Populate StoryTemplateFocus rows for StoryTemplate 68 from opendata.ds_10650. "
        "Creates one focus per BFS number and schedules publish_conditions on sequential days."
    )

    def add_arguments(self, parser):
        parser.add_argument("--template-id", type=int, default=68)
        parser.add_argument(
            "--start-date",
            default="02-16",
            help="Start month-day for scheduling (MM-DD). Default: 02-16.",
        )
        parser.add_argument(
            "--schema",
            default="opendata",
            help="Schema containing the source dataset table. Default: opendata.",
        )
        parser.add_argument(
            "--table",
            default="ds_10650",
            help="Source dataset table name. Default: ds_10650.",
        )
        parser.add_argument("--limit", type=int, default=None)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        template_id: int = options["template_id"]
        start_date_str: str = options["start_date"]
        schema: str = options["schema"]
        table: str = options["table"]
        limit: int | None = options["limit"]
        dry_run: bool = options["dry_run"]

        if not start_date_str or "-" not in start_date_str:
            raise CommandError("--start-date must be in MM-DD format (e.g. 02-16).")
        month_str, day_str = start_date_str.split("-", 1)
        if not (month_str.isdigit() and day_str.isdigit()):
            raise CommandError("--start-date must be numeric MM-DD (e.g. 02-16).")
        start_month = int(month_str)
        start_day = int(day_str)
        anchor = date(2000, start_month, start_day)

        if not StoryTemplate.objects.filter(id=template_id).exists():
            raise CommandError(f"StoryTemplate id={template_id} does not exist.")

        existing = set(
            StoryTemplateFocus.objects.filter(story_template_id=template_id)
            .exclude(filter_value__isnull=True)
            .exclude(filter_value="")
            .values_list("filter_value", flat=True)
        )

        def quote_ident(ident: str) -> str:
            if not ident.replace("_", "").isalnum():
                raise CommandError(f"Invalid identifier: {ident!r}")
            return f'"{ident}"'

        full_table = f'{quote_ident(schema)}.{quote_ident(table)}'
        limit_sql = "LIMIT %s" if limit else ""
        params: list[object] = [limit] if limit else []

        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT bfs_nummer::text AS bfs_nummer, MIN(gemeinde::text) AS gemeinde
                FROM {full_table}
                WHERE bfs_nummer IS NOT NULL
                GROUP BY bfs_nummer
                ORDER BY bfs_nummer::bigint
                {limit_sql}
                """,
                params,
            )
            rows = [_Row(bfs_nummer=r[0], gemeinde=r[1] or "") for r in cursor.fetchall()]

        created = 0
        skipped = 0
        batch: list[StoryTemplateFocus] = []

        for idx, row in enumerate(rows):
            bfs = (row.bfs_nummer or "").strip()
            if not bfs:
                skipped += 1
                continue
            if bfs in existing:
                skipped += 1
                continue

            publish_day = anchor + timedelta(days=idx)
            publish_conditions = (
                "select case when "
                "extract (month from %(published_date)s::DATE) = {m} "
                "and extract (day from %(published_date)s::DATE) = {d} "
                "then 1 else 0 end as result"
            ).format(m=publish_day.month, d=publish_day.day)

            batch.append(
                StoryTemplateFocus(
                    story_template_id=template_id,
                    publish_conditions=publish_conditions,
                    filter_value=bfs,
                    filter_expression=(row.gemeinde or "").strip() or None,
                )
            )
            existing.add(bfs)

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry-run: would create {len(batch)} StoryTemplateFocus rows; skipped={skipped}."
                )
            )
            return

        if batch:
            with transaction.atomic():
                StoryTemplateFocus.objects.bulk_create(batch, batch_size=500)
            created = len(batch)

        self.stdout.write(
            self.style.SUCCESS(f"Done. created={created} skipped={skipped} source_rows={len(rows)}")
        )

