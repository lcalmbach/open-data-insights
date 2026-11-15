"""
Two unrelated sync failures, fixed together because both are one-off repairs.

1. data.bl.ch datasets 11000 (energy consumption) and 12060 (waste recycling)
   now expose their year as a year-precision `date` field. Configured as
   NEW_PK they build `<field> IN ('2024-01-01 00:00:00+00:00', ...)`, which
   the ODS API rejects with HTTP 400, and the date-vs-int mismatch flags every
   year as new on every run. Same problem and same fix as migration 0206:
   switch to NEW_YEAR, which builds `<field> > <last_year>`. Matched by
   source_identifier because primary keys differ per environment.

2. opendata.ds_100164 (groundwater levels) has add_time_aggregation_fields
   set but its table lacks `day_in_year`, so every incremental insert fails
   with UndefinedColumn. Add the column and backfill it. Guarded so it is a
   no-op where the table does not exist (test databases) or already has it.
"""

from django.db import migrations

NEW_YEAR_IMPORT_TYPE_ID = 76
NEW_PK_IMPORT_TYPE_ID = 78
YEAR_FIELD_BY_SOURCE_IDENTIFIER = {
    "11000": "erhebungsjahr",
    "12060": "jahr",
}
BASE_URL = "data.bl.ch"

ADD_DAY_IN_YEAR = """
DO $$
BEGIN
    IF to_regclass('opendata.ds_100164') IS NOT NULL THEN
        ALTER TABLE opendata.ds_100164
            ADD COLUMN IF NOT EXISTS day_in_year integer;
        UPDATE opendata.ds_100164
           SET day_in_year = EXTRACT(doy FROM date)::integer
         WHERE day_in_year IS NULL AND date IS NOT NULL;
    END IF;
END $$;
"""


def to_new_year(apps, schema_editor):
    Dataset = apps.get_model("reports", "Dataset")
    for source_identifier, year_field in YEAR_FIELD_BY_SOURCE_IDENTIFIER.items():
        Dataset.objects.filter(
            source_identifier=source_identifier, base_url=BASE_URL
        ).update(import_type_id=NEW_YEAR_IMPORT_TYPE_ID, year_field=year_field)


def to_new_pk(apps, schema_editor):
    Dataset = apps.get_model("reports", "Dataset")
    Dataset.objects.filter(
        source_identifier__in=list(YEAR_FIELD_BY_SOURCE_IDENTIFIER),
        base_url=BASE_URL,
    ).update(import_type_id=NEW_PK_IMPORT_TYPE_ID, year_field=None)


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0211_add_record_count_import_type"),
    ]

    operations = [
        migrations.RunPython(to_new_year, to_new_pk),
        # Reverse is a no-op: dropping the column would break the sync again.
        migrations.RunSQL(ADD_DAY_IN_YEAR, migrations.RunSQL.noop),
    ]
