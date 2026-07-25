"""
The Baselland (data.bl.ch) datasets whose `jahr` field is a year-precision
`date` were configured as NEW_PK (import-if-new-value), which builds a
`jahr IN ('1991-01-01 00:00:00+00:00', ...)` clause. The ODS API rejects
`IN`/`=` on a date field (IncompatibleTypesInComparisonFilter, HTTP 400),
and the date-vs-int mismatch also flags every row as new on every run.

Switch them to NEW_YEAR (import_type 76) with year_field='jahr', which uses
a `jahr > <last_year>` clause that the API accepts. Matched by
source_identifier so it applies regardless of per-environment PKs.
"""

from django.db import migrations

NEW_YEAR_IMPORT_TYPE_ID = 76
NEW_PK_IMPORT_TYPE_ID = 78
SOURCE_IDENTIFIERS = ["10200", "10010", "10040"]


def to_new_year(apps, schema_editor):
    Dataset = apps.get_model("reports", "Dataset")
    Dataset.objects.filter(source_identifier__in=SOURCE_IDENTIFIERS).update(
        import_type_id=NEW_YEAR_IMPORT_TYPE_ID,
        year_field="jahr",
    )


def to_new_pk(apps, schema_editor):
    Dataset = apps.get_model("reports", "Dataset")
    Dataset.objects.filter(source_identifier__in=SOURCE_IDENTIFIERS).update(
        import_type_id=NEW_PK_IMPORT_TYPE_ID,
        year_field=None,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0205_update_deepseek_model_keys"),
    ]

    operations = [
        migrations.RunPython(to_new_year, to_new_pk),
    ]
