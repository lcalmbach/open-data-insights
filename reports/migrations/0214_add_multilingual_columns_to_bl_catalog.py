"""
data.bl.ch added per-language variants (_de/_fr/_en/_it) of title,
description, theme, keyword, license, license_url and publisher to dataset
10660 (the portal's own dataset catalogue). Appending newly published
datasets to opendata.ds_10660 then fails with UndefinedColumn "title_de".

Add the columns rather than reloading the table: a reload would reset
`is_new` to true on every row and the "New Metadata published" story would
announce the whole catalogue as new. Existing rows keep NULL in the new
columns. Guarded so it is a no-op where the table does not exist.
"""

from django.db import migrations

FIELDS = ["title", "description", "theme", "keyword", "license", "license_url", "publisher"]
LANGUAGES = ["de", "fr", "en", "it"]
NEW_COLUMNS = [f"{field}_{language}" for field in FIELDS for language in LANGUAGES]

ADD_COLUMNS = """
DO $$
BEGIN
    IF to_regclass('opendata.ds_10660') IS NOT NULL THEN
        ALTER TABLE opendata.ds_10660
            {columns};
    END IF;
END $$;
""".format(
    columns=",\n            ".join(
        f"ADD COLUMN IF NOT EXISTS {column} text" for column in NEW_COLUMNS
    )
)


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0213_reload_bl_landuse_dataset"),
    ]

    operations = [
        # Reverse is a no-op: dropping the columns would break the sync again.
        migrations.RunSQL(ADD_COLUMNS, migrations.RunSQL.noop),
    ]
