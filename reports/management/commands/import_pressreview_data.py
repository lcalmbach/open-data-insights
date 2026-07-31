"""
One-off import of sources/keywords/subscribers from the legacy work/pressreview
Postgres schema into this app's PressReview* models.

Historical articles/scores/logs are intentionally NOT migrated — they are
transient data; the first `harvest_press_review` run repopulates articles fresh.
"""

import os

import psycopg2
import psycopg2.extras
from django.core.management.base import BaseCommand
from django.db import transaction

from account.models import CustomUser
from reports.models.press_review import (
    PressReviewKeyword,
    PressReviewSource,
    UserPressReviewKeyword,
)


def _get_pressreview_dsn() -> str:
    """Resolve the legacy pressreview DB connection, mirroring work/pressreview/db.py::_get_dsn."""
    heroku_auto = os.getenv("DATABASE_URL")
    if heroku_auto:
        return heroku_auto.replace("postgres://", "postgresql://", 1)

    if os.getenv("USE_PRODUCTION_DB") == "1":
        url = os.getenv("HEROKU_DATABASE_URL", "")
        if url:
            return url.replace("postgres://", "postgresql://", 1)

    host = os.getenv("PRESSREVIEW_DB_HOST") or os.getenv("DB_HOST", "localhost")
    port = os.getenv("PRESSREVIEW_DB_PORT") or os.getenv("DB_PORT", "5432")
    name = os.getenv("PRESSREVIEW_DB_NAME") or os.getenv("DB_NAME", "postgres")
    user = os.getenv("PRESSREVIEW_DB_USER") or os.getenv("DB_USER", "postgres")
    password = os.getenv("PRESSREVIEW_DB_PASSWORD") or os.getenv("DB_PASSWORD", "")
    return f"postgresql://{user}:{password}@{host}:{port}/{name}"


class Command(BaseCommand):
    help = "Import sources, keywords and subscribers from the legacy pressreview Postgres schema"

    def add_arguments(self, parser):
        parser.add_argument(
            "--schema",
            default=os.getenv("PRESSREVIEW_DB_SCHEMA", "pressreview"),
            help="Postgres schema the legacy pressreview tables live in.",
        )

    def handle(self, *args, **options):
        schema = options["schema"]
        conn = psycopg2.connect(_get_pressreview_dsn(), options=f"-c search_path={schema}")
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            cur.execute("SELECT name, url, rss_url, active, local FROM sources")
            sources = cur.fetchall()

            cur.execute("SELECT keyword, active, required FROM keywords")
            keywords = cur.fetchall()

            cur.execute("SELECT id, email FROM subscribers WHERE active = TRUE")
            subscribers = cur.fetchall()

            try:
                cur.execute("SELECT subscriber_id, keyword FROM subscriber_keywords")
                subscriber_keywords = cur.fetchall()
            except psycopg2.errors.UndefinedTable:
                # Older pressreview deployments predate the subscriber_keywords table.
                conn.rollback()
                subscriber_keywords = []
        finally:
            conn.close()

        subscriber_keywords_by_id = {}
        for row in subscriber_keywords:
            subscriber_keywords_by_id.setdefault(row["subscriber_id"], []).append(row["keyword"])

        source_count = keyword_count = user_count = keyword_link_count = 0

        with transaction.atomic():
            for row in sources:
                _, created = PressReviewSource.objects.get_or_create(
                    rss_url=row["rss_url"],
                    defaults={
                        "name": row["name"],
                        "url": row["url"],
                        "active": row["active"],
                        "local": row["local"],
                    },
                )
                if created:
                    source_count += 1

            for row in keywords:
                _, created = PressReviewKeyword.objects.get_or_create(
                    keyword=row["keyword"],
                    defaults={"active": row["active"], "required": row["required"]},
                )
                if created:
                    keyword_count += 1

            for sub in subscribers:
                try:
                    user = CustomUser.objects.get(email=sub["email"])
                except CustomUser.DoesNotExist:
                    user = CustomUser.objects.create_user(
                        email=sub["email"], first_name="", last_name=""
                    )
                    user_count += 1

                for kw in subscriber_keywords_by_id.get(sub["id"], []):
                    _, kw_created = UserPressReviewKeyword.objects.get_or_create(
                        user=user, keyword=kw
                    )
                    if kw_created:
                        keyword_link_count += 1

        self.stdout.write(self.style.SUCCESS("Press review data import complete"))
        self.stdout.write(f"Sources created: {source_count} (of {len(sources)} rows)")
        self.stdout.write(f"Keywords created: {keyword_count} (of {len(keywords)} rows)")
        self.stdout.write(f"Users created: {user_count} (of {len(subscribers)} subscribers)")
        self.stdout.write(f"User keyword links created: {keyword_link_count}")
