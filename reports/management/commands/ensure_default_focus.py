from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.core.management.base import CommandError

from reports.models.story_template import StoryTemplate, StoryTemplateFocus


@dataclass(frozen=True)
class _TemplateRow:
    id: int
    title: str


class Command(BaseCommand):
    help = (
        "Ensure each StoryTemplate has exactly one 'default' StoryTemplateFocus "
        "(where focus_filter is NULL/empty) and report duplicates."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Don't write changes; only report what would change.",
        )
        parser.add_argument(
            "--no-fix",
            action="store_true",
            help="Only report; don't create missing default focus rows.",
        )
        parser.add_argument(
            "--ignore-duplicates",
            action="store_true",
            help="Exit 0 even if duplicate default focus rows are found.",
        )

    def handle(self, *args, **options):
        dry_run: bool = options["dry_run"]
        fix_missing: bool = not options["no_fix"]
        ignore_duplicates: bool = options["ignore_duplicates"]

        focus_table = StoryTemplateFocus._meta.db_table
        with connection.cursor() as cursor:
            columns = {
                col.name for col in connection.introspection.get_table_description(cursor, focus_table)
            }

        if "focus_filter" in columns:
            filter_col = "focus_filter"
            schema_label = "post-0152"
        elif "filter" in columns:
            filter_col = "filter"
            schema_label = "pre-0152 (legacy column name 'filter')"
        else:
            raise CommandError(
                f"Database table {focus_table} has neither 'focus_filter' nor 'filter' column."
            )

        if schema_label.startswith("pre-0152") and fix_missing and not dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "Detected pre-0152 schema. Automatic creation of missing default focus rows is disabled "
                    "until migrations are applied."
                )
            )
            fix_missing = False

        st_table = StoryTemplate._meta.db_table
        default_pred = f"({focus_table}.{filter_col} IS NULL OR {focus_table}.{filter_col} = '')"

        missing_default_rows: list[_TemplateRow] = []
        duplicate_template_ids: list[int] = []

        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {st_table}.id, {st_table}.title
                FROM {st_table}
                LEFT JOIN {focus_table}
                  ON {focus_table}.story_template_id = {st_table}.id
                 AND {default_pred}
                WHERE {focus_table}.id IS NULL
                ORDER BY {st_table}.id
                """
            )
            missing_default_rows = [
                _TemplateRow(id=row[0], title=row[1]) for row in cursor.fetchall()
            ]

            cursor.execute(
                f"""
                SELECT story_template_id
                FROM {focus_table}
                WHERE {default_pred}
                GROUP BY story_template_id
                HAVING COUNT(*) > 1
                ORDER BY story_template_id
                """
            )
            duplicate_template_ids = [row[0] for row in cursor.fetchall()]

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Schema: {schema_label} | "
                f"StoryTemplates: {StoryTemplate.objects.count()} | "
                f"missing default focus: {len(missing_default_rows)} | "
                f"duplicate default focus: {len(duplicate_template_ids)}"
            )
        )

        if duplicate_template_ids:
            self.stdout.write(self.style.WARNING("Duplicate default focus rows found:"))
            with connection.cursor() as cursor:
                for template_id in duplicate_template_ids:
                    cursor.execute(
                        f"""
                        SELECT id, {filter_col}
                        FROM {focus_table}
                        WHERE story_template_id = %s
                          AND ({filter_col} IS NULL OR {filter_col} = '')
                        ORDER BY id
                        """,
                        [template_id],
                    )
                    focus_rows = cursor.fetchall()
                    title = (
                        StoryTemplate.objects.filter(id=template_id)
                        .values_list("title", flat=True)
                        .first()
                    )
                    self.stdout.write(
                        f"- StoryTemplate id={template_id} title={title!r} default_focus_rows={focus_rows}"
                    )

        if fix_missing and missing_default_rows:
            if dry_run:
                self.stdout.write(
                    self.style.WARNING(
                        "Dry-run: would create one default focus row for each missing template."
                    )
                )
            else:
                created = 0
                with transaction.atomic():
                    for row in missing_default_rows:
                        StoryTemplateFocus.objects.create(
                            story_template_id=row.id,
                            focus_filter="",
                            publish_conditions=None,
                            focus_subject=None,
                            additional_context=None,
                            image=None,
                        )
                        created += 1
                self.stdout.write(self.style.SUCCESS(f"Created default focus rows: {created}"))

        if duplicate_template_ids and not ignore_duplicates:
            raise CommandError(
                "Duplicate default focus rows detected. Resolve before continuing "
                "(or rerun with --ignore-duplicates)."
            )

        self.stdout.write(self.style.SUCCESS("Done."))
