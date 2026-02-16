from __future__ import annotations

import csv
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils.dateparse import parse_datetime


CustomUser = apps.get_model("account", "CustomUser")
Organisation = apps.get_model("account", "Organisation")


DEFAULT_CSV_PATH = (
    Path("/home/lcalm/Work/Dev/open-data-insights/work/backup")
    / f"account_customuser_{datetime.now().strftime('%Y%m%d')}.csv"
)


def _parse_bool(value: Any) -> bool:
    if value is None:
        return False
    s = str(value).strip().lower()
    if s in {"1", "true", "t", "yes", "y"}:
        return True
    if s in {"0", "false", "f", "no", "n", "", "none", "null"}:
        return False
    raise ValueError(f"Invalid boolean: {value!r}")


def _parse_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    s = str(value).strip()
    if s == "" or s.upper() == "NULL":
        return None
    return int(s)


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    s = str(value).strip()
    if s == "" or s.upper() == "NULL":
        return None
    # Common export format: "2026-02-15 16:14:08.317709+00"
    parsed = parse_datetime(s)
    if parsed is not None:
        return parsed
    if " " in s and "T" not in s:
        parsed = parse_datetime(s.replace(" ", "T"))
        if parsed is not None:
            return parsed
    # last resort for Python-iso style
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _new_slug(used: Set[str]) -> str:
    while True:
        candidate = uuid.uuid4().hex[:10]
        if candidate not in used:
            used.add(candidate)
            return candidate


@dataclass
class Stats:
    read: int = 0
    filtered_out: int = 0
    duplicates_existing: int = 0
    inserted: int = 0
    org_missing: int = 0
    slug_regenerated: int = 0


class Command(BaseCommand):
    help = (
        "Import users from a CSV export of report_generator.account_customuser into the local DB. "
        "By default, inserts only rows with id >= --min-id and skips any row whose email/id already exists."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            dest="csv_path",
            default=str(DEFAULT_CSV_PATH),
            help=f"Path to CSV export (default: {DEFAULT_CSV_PATH}).",
        )
        parser.add_argument(
            "--min-id",
            type=int,
            default=29,
            help="Only import rows whose id is >= this value (default: 29).",
        )
        parser.add_argument(
            "--chunk-size",
            type=int,
            default=500,
            help="bulk_create batch size (default: 500).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and report only; do not insert rows.",
        )

    def handle(self, *args, **opts):
        csv_path = Path(opts["csv_path"]).expanduser()
        min_id = int(opts["min_id"])
        chunk_size = int(opts["chunk_size"])
        dry = bool(opts["dry_run"])

        if not csv_path.exists():
            raise CommandError(f"CSV not found: {csv_path}")

        rows = self._read_rows(csv_path)
        stats = Stats(read=len(rows))

        rows = [r for r in rows if int(r["id"]) >= min_id]
        stats.filtered_out = stats.read - len(rows)

        if not rows:
            self.stdout.write(self.style.WARNING("No rows to import after filtering."))
            return

        incoming_ids = {int(r["id"]) for r in rows}
        incoming_emails = {r["email"] for r in rows if r.get("email")}
        incoming_slugs = {r["slug"] for r in rows if r.get("slug")}
        incoming_org_ids = {
            int(r["organisation_id"])
            for r in rows
            if r.get("organisation_id") not in (None, "", "NULL", "null")
        }

        existing_ids = set(
            CustomUser.objects.using("default")
            .filter(id__in=incoming_ids)
            .values_list("id", flat=True)
        )
        existing_emails = set(
            CustomUser.objects.using("default")
            .filter(email__in=incoming_emails)
            .values_list("email", flat=True)
        )
        existing_slugs = set(
            CustomUser.objects.using("default")
            .filter(slug__in=incoming_slugs)
            .values_list("slug", flat=True)
        )
        existing_org_ids = set(
            Organisation.objects.using("default")
            .filter(id__in=incoming_org_ids)
            .values_list("id", flat=True)
        )

        used_slugs = set(s for s in existing_slugs if s)

        to_create: List[Any] = []
        for r in rows:
            rid = int(r["id"])
            email = (r.get("email") or "").strip()
            if not email:
                raise CommandError(f"Row id={rid}: missing email")

            if rid in existing_ids or email in existing_emails:
                stats.duplicates_existing += 1
                continue

            slug = (r.get("slug") or "").strip() or None
            if slug:
                if slug in used_slugs:
                    slug = _new_slug(used_slugs)
                    stats.slug_regenerated += 1
                else:
                    used_slugs.add(slug)

            org_id = _parse_int(r.get("organisation_id"))
            if org_id is not None and org_id not in existing_org_ids:
                org_id = None
                stats.org_missing += 1

            try:
                user = CustomUser(
                    id=rid,
                    password=r.get("password") or "",
                    last_login=_parse_dt(r.get("last_login")),
                    is_superuser=_parse_bool(r.get("is_superuser")),
                    email=email,
                    first_name=(r.get("first_name") or "").strip(),
                    last_name=(r.get("last_name") or "").strip(),
                    country=(r.get("country") or "").strip(),
                    is_confirmed=_parse_bool(r.get("is_confirmed")),
                    date_joined=_parse_dt(r.get("date_joined")),
                    last_active=_parse_dt(r.get("last_active")),
                    is_active=_parse_bool(r.get("is_active")),
                    is_staff=_parse_bool(r.get("is_staff")),
                    auto_subscribe=_parse_bool(r.get("auto_subscribe")),
                    slug=slug,
                    organisation_id=org_id,
                )
            except Exception as exc:
                raise CommandError(f"Row id={rid} email={email!r}: {exc}") from exc

            if not user.first_name or not user.last_name or not user.country:
                raise CommandError(
                    f"Row id={rid} email={email!r}: missing first_name/last_name/country"
                )

            to_create.append(user)

        if not to_create:
            self.stdout.write(self.style.WARNING("Nothing to insert (all rows already exist)."))
            return

        self.stdout.write(
            self.style.NOTICE(
                f"Read={stats.read}, filtered_out(<{min_id})={stats.filtered_out}, "
                f"duplicates_existing={stats.duplicates_existing}, to_insert={len(to_create)}"
            )
        )
        if dry:
            self.stdout.write(self.style.WARNING("Dry-run mode: no rows inserted."))
            return

        with transaction.atomic(using="default"):
            CustomUser.objects.using("default").bulk_create(to_create, batch_size=chunk_size)
            stats.inserted = len(to_create)
            self._bump_id_sequence()

        self.stdout.write(
            self.style.SUCCESS(
                "Done. "
                f"inserted={stats.inserted}, duplicates_existing={stats.duplicates_existing}, "
                f"org_missing_set_null={stats.org_missing}, slug_regenerated={stats.slug_regenerated}"
            )
        )

    def _read_rows(self, csv_path: Path) -> List[Dict[str, str]]:
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                raise CommandError("CSV has no header row.")

            required = {
                "id",
                "password",
                "last_login",
                "is_superuser",
                "email",
                "first_name",
                "last_name",
                "country",
                "is_confirmed",
                "date_joined",
                "last_active",
                "is_active",
                "is_staff",
                "auto_subscribe",
                "slug",
                "organisation_id",
            }
            missing = required - set(reader.fieldnames)
            if missing:
                raise CommandError(f"CSV missing required columns: {', '.join(sorted(missing))}")

            rows: List[Dict[str, str]] = []
            for row in reader:
                rows.append(row)
            return rows

    def _bump_id_sequence(self) -> None:
        # Ensure Postgres sequence is >= max(id) after inserting explicit ids.
        table = f"report_generator.{CustomUser._meta.db_table}"
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT setval(
                    pg_get_serial_sequence(%s, 'id'),
                    COALESCE((SELECT MAX(id) FROM {table}), 1),
                    true
                )
                """,
                [table],
            )
