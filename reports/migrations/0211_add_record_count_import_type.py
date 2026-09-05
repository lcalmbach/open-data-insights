from django.db import migrations

CATEGORY_NAME = "data-import-type"
RECORD_COUNT_KEY = "imp-CNT"


def add_record_count_import_type(apps, schema_editor):
    LookupCategory = apps.get_model("reports", "LookupCategory")
    LookupValue = apps.get_model("reports", "LookupValue")

    # Looked up by name, not by its id (8): a freshly built database — the test
    # database included — has no lookup seed data at all, and assuming the id
    # made this migration fail with a foreign key violation.
    category = LookupCategory.objects.filter(name=CATEGORY_NAME).first()
    if category is None:
        return

    # No explicit id: LookupValue ids differ per environment, so the sequence
    # assigns one locally and another in production. Code matches on `key`.
    LookupValue.objects.get_or_create(
        category=category,
        key=RECORD_COUNT_KEY,
        defaults={
            "value": "Import if record count differs",
            "description": (
                "Compares the row count of the target table against the source's "
                "total_count and reloads when the table is short. Catches records "
                "back-dated into the past, which the timestamp check misses."
            ),
            "sort_order": 5,
        },
    )


def remove_record_count_import_type(apps, schema_editor):
    LookupValue = apps.get_model("reports", "LookupValue")
    LookupValue.objects.filter(
        category__name=CATEGORY_NAME, key=RECORD_COUNT_KEY
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0210_pressreviewsource_feed_type_and_more"),
    ]

    operations = [
        migrations.RunPython(
            add_record_count_import_type, remove_record_count_import_type
        ),
    ]
