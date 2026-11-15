"""
data.bl.ch restructured dataset 11970 (Arealstatistik / land use) in Oct 2026:

- the value column `wert` was renamed to `hektaren`
- `erhebungsperiode` changed from survey years ('2014/2015') to the national
  survey cycle ('2013-2018'); `erhebungsjahr_e` from '2014/15' to '2014-15'
- the 'Polygonfläche' total rows were dropped; 'Punktfläche (1 - 17)' is the
  only remaining total
- earlier periods were revised and a new survey (2020-2025) was added

Appending to the old table fails (UndefinedColumn "hektaren"), and old and new
rows cannot be mixed anyway. This migration:

1. makes the post-import SQL parse both 'YYYY-YYYY' and 'YYYY/YYYY'
2. renames the column and empties the table, so the next sync sees every
   `erhebungsjahr_e` as new and re-imports the whole dataset
3. rewrites the story context that summed `wert` against 'Polygonfläche'

Matched by source_identifier / table name because PKs differ per environment.
The emptied table is refilled by the next `synch_data` run; the data is public
and re-downloadable, so the reverse only restores the configuration.
"""

from django.db import migrations

SOURCE_IDENTIFIER = "11970"
BASE_URL = "data.bl.ch"
CONTEXT_KEY = "most_recent_statistics"

OLD_POST_IMPORT_SQL = (
    "update opendata.ds_11970 set \r\n"
    "    jahr_von = split_part(erhebungsperiode, '/', 1)::int ,\r\n"
    "    jahr_bis = split_part(erhebungsperiode, '/', 2)::int\r\n"
    "where jahr_von is null and erhebungsperiode like '%/%';\r\n"
    "\r\n"
    "update opendata.ds_11970 set \r\n"
    "    jahr_von = erhebungsperiode::int,\r\n"
    "    jahr_bis = erhebungsperiode::int\r\n"
    "where jahr_von is null and erhebungsperiode not like '%/%';"
)

NEW_POST_IMPORT_SQL = """update opendata.ds_11970 set
    jahr_von = split_part(replace(erhebungsperiode, '/', '-'), '-', 1)::int,
    jahr_bis = split_part(replace(erhebungsperiode, '/', '-'), '-', 2)::int
where jahr_von is null and erhebungsperiode ~ '^[0-9]{4}[-/][0-9]{4}$';

update opendata.ds_11970 set
    jahr_von = erhebungsperiode::int,
    jahr_bis = erhebungsperiode::int
where jahr_von is null and erhebungsperiode ~ '^[0-9]{4}$'"""

OLD_CONTEXT_SQL = """with base as (
select
	erhebungsperiode,
	hauptbereich,
	sum(wert) as hectares
from opendata.ds_11970
where jahr_bis = (select max(jahr_bis) from opendata.ds_11970)
and hauptbereich <> 'Punktfläche (1 - 17)'
group by
erhebungsperiode, hauptbereich),

total as (
select * from base
where hauptbereich = 'Polygonfläche'
)

select
	b.erhebungsperiode,
	case b.hauptbereich
	when 'Polygonfläche' then 'Total'
	when 'Landwirtschaftsflächen (6 - 9)' then 'Agriculture'
	when 'Siedlungsflächen (1 - 5)' then 'Settlements'
	when 'Unproduktive Flächen (13 - 17)' then 'Unproductive Areas'
	when 'Bestockte Flächen (10 - 12)' then 'Forest'
	else b.hauptbereich end as category,
	b.hectares,
	round(b.hectares / t.hectares * 100, 1) as percent
from base as b
cross join total as t
order by b.hectares / t.hectares"""

NEW_CONTEXT_SQL = """with base as (
select
	erhebungsperiode,
	hauptbereich,
	sum(hektaren) as hectares
from opendata.ds_11970
where jahr_bis = (select max(jahr_bis) from opendata.ds_11970)
group by
erhebungsperiode, hauptbereich),

total as (
select * from base
where hauptbereich = 'Punktfläche (1 - 17)'
)

select
	b.erhebungsperiode,
	case b.hauptbereich
	when 'Punktfläche (1 - 17)' then 'Total'
	when 'Landwirtschaftsflächen (6 - 9)' then 'Agriculture'
	when 'Siedlungsflächen (1 - 5)' then 'Settlements'
	when 'Unproduktive Flächen (13 - 17)' then 'Unproductive Areas'
	when 'Bestockte Flächen (10 - 12)' then 'Forest'
	else b.hauptbereich end as category,
	b.hectares,
	round(b.hectares::numeric / t.hectares * 100, 1) as percent
from base as b
cross join total as t
order by b.hectares::numeric / t.hectares"""

RENAME_AND_EMPTY = """
DO $$
BEGIN
    IF to_regclass('opendata.ds_11970') IS NOT NULL AND EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'opendata' AND table_name = 'ds_11970'
           AND column_name = 'wert'
    ) THEN
        ALTER TABLE opendata.ds_11970 RENAME COLUMN wert TO hektaren;
        TRUNCATE opendata.ds_11970;
    END IF;
END $$;
"""


def _squash(sql):
    return " ".join(sql.split())


def _set_config(apps, post_import_sql, context_from, context_to):
    Dataset = apps.get_model("reports", "Dataset")
    Dataset.objects.filter(
        source_identifier=SOURCE_IDENTIFIER, base_url=BASE_URL
    ).update(post_import_sql_commands=post_import_sql)

    StoryTemplateContext = apps.get_model("reports", "StoryTemplateContext")
    for context in StoryTemplateContext.objects.filter(
        key=CONTEXT_KEY, sql_command__contains="opendata.ds_11970"
    ):
        # Compare ignoring whitespace: admin-edited text is stored with CRLF
        # and trailing blanks. A context edited beyond that is left alone.
        if _squash(context.sql_command) == _squash(context_from):
            context.sql_command = context_to
            context.save(update_fields=["sql_command"])


def forwards(apps, schema_editor):
    _set_config(apps, NEW_POST_IMPORT_SQL, OLD_CONTEXT_SQL, NEW_CONTEXT_SQL)


def backwards(apps, schema_editor):
    _set_config(apps, OLD_POST_IMPORT_SQL, NEW_CONTEXT_SQL, OLD_CONTEXT_SQL)


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0212_fix_bl_year_datasets_and_groundwater_column"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
        migrations.RunSQL(RENAME_AND_EMPTY, migrations.RunSQL.noop),
    ]
