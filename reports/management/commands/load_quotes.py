from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Tuple

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from reports.models import Quote


def _build_lifespan(birth: str, death: str) -> str:
    """Create a simple lifespan string from birth/death years."""
    birth = birth.strip()
    death = death.strip()

    if birth and death:
        return f"{birth} - {death}"
    if birth:
        return birth
    if death:
        return death
    return ""


class Command(BaseCommand):
    help = "Load quotes stored in files/quotes.csv into the reports Quote model."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            type=str,
            help="Override the default CSV file (BASE_DIR/files/quotes.csv).",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Delete all existing quotes before importing.",
        )

    def handle(self, *args, **options):
        file_path = Path(options["source"]).expanduser() if options.get("source") else settings.BASE_DIR / "files" / "quotes.csv"

        if not file_path.exists():
            raise CommandError(f"Unable to find quotes CSV at {file_path}")

        if options.get("overwrite"):
            deleted, _ = Quote.objects.all().delete()
            self.stdout.write(f"Cleared {deleted} quote records before import.")

        created, updated = 0, 0
        for row in _iter_csv_rows(file_path):
            quote_text, author, author_url, birth, death = row

            obj, was_created = Quote.objects.update_or_create(
                quote=quote_text,
                defaults={
                    "author": author,
                    "lifespan": _build_lifespan(birth, death),
                    "author_wiki_url": author_url,
                },
            )

            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"Quotes import finished: {created} added, {updated} updated."
        ))


def _iter_csv_rows(path: Path) -> Iterable[Tuple[str, str, str, str, str]]:
    """Yield normalized tuples for quote, author, wiki url, birth, and death."""
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh, skipinitialspace=True)
        for raw in reader:
            if not raw:
                continue
            fields = [field.strip() for field in raw]
            if len(fields) < 2:
                continue

            quote_text = fields[0]
            author = fields[1] if len(fields) > 1 else ""
            if not quote_text:
                continue
            wiki_value = fields[2] if len(fields) > 2 else ""
            birth = fields[3] if len(fields) > 3 else ""
            death = fields[4] if len(fields) > 4 else ""
            yield quote_text, author, _extract_wiki_url(wiki_value), birth, death


def _extract_wiki_url(value: str) -> str:
    """Return a plain URL when the CSV column stores '[text](url)' markup."""
    value = value.strip()
    if not value:
        return ""
    if "](" in value and value.endswith(")"):
        start = value.index("](") + 2
        return value[start:-1].strip()
    return value
