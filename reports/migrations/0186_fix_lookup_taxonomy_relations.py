from django.db import migrations


REGION_CATEGORY_ID = 11
TOPIC_CATEGORY_ID = 12


def fix_lookup_taxonomy_relations(apps, schema_editor):
    connection = schema_editor.connection
    quote_name = schema_editor.quote_name
    LookupCategory = apps.get_model("reports", "LookupCategory")
    LookupValue = apps.get_model("reports", "LookupValue")

    LookupCategory.objects.update_or_create(
        id=REGION_CATEGORY_ID,
        defaults={
            "name": "Region",
            "description": "Geographic scope for story templates.",
        },
    )
    LookupCategory.objects.update_or_create(
        id=TOPIC_CATEGORY_ID,
        defaults={
            "name": "Topic",
            "description": "Editorial topic hierarchy for story templates.",
        },
    )

    def table_exists(cursor, table_name):
        tables = connection.introspection.table_names(cursor)
        return table_name in tables

    def column_names(cursor, table_name):
        cursor.execute(
            """
            select column_name
            from information_schema.columns
            where table_name = %s
            order by ordinal_position
            """,
            [table_name],
        )
        return {row[0] for row in cursor.fetchall()}

    def fk_target_table(cursor, table_name, column_name):
        cursor.execute(
            """
            select rt.relname
            from pg_constraint c
            join pg_class t on t.oid = c.conrelid
            join pg_class rt on rt.oid = c.confrelid
            join unnest(c.conkey) with ordinality as cols(attnum, ord) on true
            join pg_attribute a on a.attrelid = t.oid and a.attnum = cols.attnum
            where t.relname = %s and c.contype = 'f' and a.attname = %s
            limit 1
            """,
            [table_name, column_name],
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def fk_constraints(cursor, table_name, column_name):
        cursor.execute(
            """
            select c.conname
            from pg_constraint c
            join pg_class t on t.oid = c.conrelid
            join unnest(c.conkey) with ordinality as cols(attnum, ord) on true
            join pg_attribute a on a.attrelid = t.oid and a.attnum = cols.attnum
            where t.relname = %s and c.contype = 'f' and a.attname = %s
            """,
            [table_name, column_name],
        )
        return [row[0] for row in cursor.fetchall()]

    def constraint_exists(cursor, table_name, constraint_name):
        cursor.execute(
            """
            select 1
            from pg_constraint c
            join pg_class t on t.oid = c.conrelid
            where t.relname = %s and c.conname = %s
            """,
            [table_name, constraint_name],
        )
        return cursor.fetchone() is not None

    def migrate_old_values(cursor, old_table_name, category_id):
        if not table_exists(cursor, old_table_name):
            return {}

        cursor.execute(
            f"""
            select id, name, coalesce(description, ''), coalesce(sort_order, 0), parent_id
            from {quote_name(old_table_name)}
            order by id
            """
        )
        rows = cursor.fetchall()
        if not rows:
            return {}

        mapping = {}
        for old_id, name, description, sort_order, _parent_id in rows:
            lookup = LookupValue.objects.filter(
                category_id=category_id,
                value=name,
            ).first()
            if lookup is None:
                lookup = LookupValue.objects.create(
                    category_id=category_id,
                    value=name,
                    description=description,
                    sort_order=sort_order,
                    level=0,
                )
            mapping[old_id] = lookup.id

        for old_id, _name, description, sort_order, parent_id in rows:
            predecessor_id = mapping.get(parent_id)
            level = 0
            if predecessor_id:
                predecessor = LookupValue.objects.filter(id=predecessor_id).first()
                level = (getattr(predecessor, "level", 0) or 0) + 1
            LookupValue.objects.filter(id=mapping[old_id]).update(
                description=description,
                sort_order=sort_order,
                predecessor_id=predecessor_id,
                level=level,
            )

        return mapping

    with connection.cursor() as cursor:
        storytemplate_columns = (
            column_names(cursor, "reports_storytemplate")
            if table_exists(cursor, "reports_storytemplate")
            else set()
        )
        topics_columns = (
            column_names(cursor, "reports_storytemplate_topics")
            if table_exists(cursor, "reports_storytemplate_topics")
            else set()
        )

        region_target = (
            fk_target_table(cursor, "reports_storytemplate", "region_id")
            if "region_id" in storytemplate_columns
            else None
        )
        topic_column = "lookupvalue_id" if "lookupvalue_id" in topics_columns else "topic_id"
        topic_target = (
            fk_target_table(cursor, "reports_storytemplate_topics", topic_column)
            if topic_column in topics_columns
            else None
        )

        region_mapping = (
            migrate_old_values(cursor, "reports_region", REGION_CATEGORY_ID)
            if region_target == "reports_region"
            else {}
        )
        topic_mapping = (
            migrate_old_values(cursor, "reports_topic", TOPIC_CATEGORY_ID)
            if topic_target == "reports_topic"
            else {}
        )

        if region_mapping and "region_id" in storytemplate_columns:
            for old_id, new_id in region_mapping.items():
                cursor.execute(
                    f"""
                    update {quote_name('reports_storytemplate')}
                    set region_id = %s
                    where region_id = %s
                    """,
                    [new_id, old_id],
                )

        if "topic_id" in topics_columns and topic_mapping:
            for old_id, new_id in topic_mapping.items():
                cursor.execute(
                    f"""
                    update {quote_name('reports_storytemplate_topics')}
                    set topic_id = %s
                    where topic_id = %s
                    """,
                    [new_id, old_id],
                )

        if "topic_id" in topics_columns and "lookupvalue_id" not in topics_columns:
            cursor.execute(
                f"""
                alter table {quote_name('reports_storytemplate_topics')}
                rename column topic_id to lookupvalue_id
                """
            )
            topics_columns.remove("topic_id")
            topics_columns.add("lookupvalue_id")

        for conname in fk_constraints(cursor, "reports_storytemplate_topics", "storytemplate_id"):
            cursor.execute(
                f"""
                alter table {quote_name('reports_storytemplate_topics')}
                drop constraint {quote_name(conname)}
                """
            )

        for conname in fk_constraints(cursor, "reports_storytemplate_topics", "lookupvalue_id"):
            cursor.execute(
                f"""
                alter table {quote_name('reports_storytemplate_topics')}
                drop constraint {quote_name(conname)}
                """
            )

        for conname in fk_constraints(cursor, "reports_storytemplate", "region_id"):
            cursor.execute(
                f"""
                alter table {quote_name('reports_storytemplate')}
                drop constraint {quote_name(conname)}
                """
            )

        if (
            "storytemplate_id" in topics_columns
            and "lookupvalue_id" in topics_columns
            and not constraint_exists(
                cursor,
                "reports_storytemplate_topics",
                "reports_storytemplate_topics_storytemplate_fk",
            )
        ):
            cursor.execute(
                f"""
                alter table {quote_name('reports_storytemplate_topics')}
                add constraint {quote_name('reports_storytemplate_topics_storytemplate_fk')}
                foreign key (storytemplate_id)
                references {quote_name('reports_storytemplate')}(id)
                deferrable initially deferred
                """
            )

        if (
            "lookupvalue_id" in topics_columns
            and not constraint_exists(
                cursor,
                "reports_storytemplate_topics",
                "reports_storytemplate_topics_lookupvalue_fk",
            )
        ):
            cursor.execute(
                f"""
                alter table {quote_name('reports_storytemplate_topics')}
                add constraint {quote_name('reports_storytemplate_topics_lookupvalue_fk')}
                foreign key (lookupvalue_id)
                references {quote_name('reports_lookupvalue')}(id)
                deferrable initially deferred
                """
            )

        if (
            "region_id" in storytemplate_columns
            and not constraint_exists(
                cursor,
                "reports_storytemplate",
                "reports_storytemplate_region_lookupvalue_fk",
            )
        ):
            cursor.execute(
                f"""
                alter table {quote_name('reports_storytemplate')}
                add constraint {quote_name('reports_storytemplate_region_lookupvalue_fk')}
                foreign key (region_id)
                references {quote_name('reports_lookupvalue')}(id)
                deferrable initially deferred
                """
            )


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0185_region_topic"),
    ]

    operations = [
        migrations.RunPython(fix_lookup_taxonomy_relations, migrations.RunPython.noop),
    ]
