"""Pytest configuration.

Seeds the reference data that model defaults depend on. `CustomUser.preferred_language`
defaults to `DEFAULT_PREFERRED_LANGUAGE_ID` (94), so creating any user in a freshly
migrated test database raised a ForeignKeyViolation — the languages are seeded by hand
in the real databases, not by a migration. Seeding once here, straight after the test
database is built, keeps it out of every individual test's setUp.
"""

import tempfile

import pytest


def pytest_configure():
    """Keep test file uploads on local disk.

    Settings load .env so pytest can reach the database, which also switches
    USE_S3_MEDIA on — tests that save an ImageField were uploading to the real
    media bucket. Force filesystem storage into a temp directory for the run.
    """
    from django.test.utils import override_settings

    override_settings(
        DEFAULT_FILE_STORAGE="django.core.files.storage.FileSystemStorage",
        STORAGES={
            "default": {
                "BACKEND": "django.core.files.storage.FileSystemStorage",
            },
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
            },
        },
        MEDIA_ROOT=tempfile.mkdtemp(prefix="odi-test-media-"),
    ).enable()

# Mirrors reports.language: these ids are referenced by model defaults and by
# ENGLISH_LANGUAGE_ID, so they must match the real data rather than be arbitrary.
LANGUAGE_CATEGORY_ID = 10
LANGUAGES = [
    (94, "en", "English"),
    (95, "de", "Deutsch"),
    (96, "fr", "Français"),
]


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    """Seed language lookups once, after migrations, before any test runs."""
    with django_db_blocker.unblock():
        from reports.models.lookups import LookupCategory, LookupValue

        category, _ = LookupCategory.objects.get_or_create(
            id=LANGUAGE_CATEGORY_ID,
            defaults={"name": "language", "description": "English, Deutsch, Français"},
        )
        for pk, key, label in LANGUAGES:
            LookupValue.objects.get_or_create(
                id=pk,
                defaults={"category": category, "key": key, "value": label},
            )

        # Inserting with explicit ids does not advance the Postgres sequence, so
        # later inserts would eventually reach 94 and collide with the rows above.
        # Sequences are not rolled back, so this surfaced only in full-suite runs.
        from django.db import connection

        with connection.cursor() as cursor:
            for table in ("reports_lookupvalue", "reports_lookupcategory"):
                cursor.execute(
                    f"""
                    SELECT setval(
                        pg_get_serial_sequence('{table}', 'id'),
                        COALESCE((SELECT MAX(id) FROM {table}), 1)
                    )
                    """
                )
