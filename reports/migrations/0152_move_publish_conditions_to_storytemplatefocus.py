from django.db import migrations, models


def forwards_move_conditions(apps, schema_editor):
    StoryTemplate = apps.get_model("reports", "StoryTemplate")
    StoryTemplateFocus = apps.get_model("reports", "StoryTemplateFocus")
    db_alias = schema_editor.connection.alias
    focus_table = StoryTemplateFocus._meta.db_table

    for template in StoryTemplate.objects.using(db_alias).all():
        focus_qs = StoryTemplateFocus.objects.using(db_alias).filter(
            story_template_id=template.id
        )
        if focus_qs.exists():
            focus_qs.filter(focus_filter__isnull=True).update(focus_filter="")
            if getattr(template, "publish_conditions", None):
                focus_qs.filter(publish_conditions__isnull=True).update(
                    publish_conditions=template.publish_conditions
                )
        else:
            schema_editor.execute(
                f"""
                INSERT INTO {focus_table}
                    (story_template_id, focus_filter, publish_conditions, focus_subject,
                     additional_context, publish_day, publish_month, image)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    template.id,
                    "",
                    getattr(template, "publish_conditions", None),
                    None,
                    None,
                    None,
                    None,
                    None,
                ],
            )


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0151_storytemplatefocus_image"),
    ]

    operations = [
        migrations.RenameField(
            model_name="storytemplatefocus",
            old_name="filter",
            new_name="focus_filter",
        ),
        migrations.RunSQL(
            sql=(
                "ALTER TABLE reports_storytemplatefocus "
                "ALTER COLUMN focus_filter DROP NOT NULL;"
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql="UPDATE reports_storytemplatefocus SET focus_filter = '' WHERE focus_filter IS NULL;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AlterField(
            model_name="storytemplatefocus",
            name="focus_filter",
            field=models.TextField(
                blank=True,
                help_text="Optional SQL filter to apply for this focus area, e.g., 'region = \"Zurich\"' or 'category = \"Health\"'.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="storytemplatefocus",
            name="publish_conditions",
            field=models.TextField(
                blank=True,
                help_text="SQL command to check if the story should be published for this focus. If this command returns no results, the story will not be published.",
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="storytemplatefocus",
            name="publish_day",
            field=models.IntegerField(
                blank=True,
                help_text="Day of the day when stories with this focus should be published. If null, stories will be published on the same day as the story template.",
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="storytemplatefocus",
            name="publish_month",
            field=models.IntegerField(
                blank=True,
                help_text="Day of the month when stories with this focus should be published. If null, stories will be published on the same day as the story template.",
                null=True,
            ),
        ),
        migrations.RunPython(forwards_move_conditions, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="storytemplate",
            name="has_data_sql",
        ),
        migrations.RemoveField(
            model_name="storytemplate",
            name="publish_conditions",
        ),
    ]
