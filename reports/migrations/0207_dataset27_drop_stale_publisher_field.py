"""
The ODS source for dataset 100057 (Opendata Datasets Basel-Stadt) removed the
`publisher` column (superseded by `publizierende_organisation`), but it is
still listed in the dataset's fields_selection. transform_ods_data() does
`df = df[fields_selection]`, which raises KeyError: "['publisher'] not in
index" and fails the whole sync.

Drop the stale `publisher` entry, matched by source_identifier so it applies
regardless of per-environment PKs.
"""

from django.db import migrations

SOURCE_IDENTIFIER = "100057"
STALE_FIELD = "publisher"


def drop_stale_field(apps, schema_editor):
    Dataset = apps.get_model("reports", "Dataset")
    for d in Dataset.objects.filter(source_identifier=SOURCE_IDENTIFIER):
        fields = list(d.fields_selection or [])
        if STALE_FIELD in fields:
            fields.remove(STALE_FIELD)
            d.fields_selection = fields
            d.save(update_fields=["fields_selection"])


def restore_stale_field(apps, schema_editor):
    Dataset = apps.get_model("reports", "Dataset")
    for d in Dataset.objects.filter(source_identifier=SOURCE_IDENTIFIER):
        fields = list(d.fields_selection or [])
        if STALE_FIELD not in fields:
            try:
                idx = fields.index("metadata_processed") + 1
            except ValueError:
                idx = len(fields)
            fields.insert(idx, STALE_FIELD)
            d.fields_selection = fields
            d.save(update_fields=["fields_selection"])


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0206_baselland_year_import_type"),
    ]

    operations = [
        migrations.RunPython(drop_stale_field, restore_stale_field),
    ]
