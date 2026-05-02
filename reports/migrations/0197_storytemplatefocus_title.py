from django.db import migrations, models


def backfill_focus_defaults(apps, schema_editor):
    StoryTemplateFocus = apps.get_model("reports", "StoryTemplateFocus")

    # Preserve existing focus defaults and only fill blanks.
    for focus in StoryTemplateFocus.objects.select_related("story_template").all():
        template = focus.story_template
        original_default_title = getattr(focus, "default_title", None)
        original_default_lead = getattr(focus, "default_lead", None)

        current_default_title = (getattr(focus, "default_title", None) or "").strip()
        template_default_title = (getattr(template, "default_title", None) or "").strip()
        template_title = (getattr(template, "title", None) or "").strip()

        if not current_default_title:
            fill_title = template_default_title or template_title
            if fill_title:
                focus.default_title = fill_title

        current_default_lead = (getattr(focus, "default_lead", None) or "").strip()
        template_default_lead = (getattr(template, "default_lead", None) or "").strip()
        if not current_default_lead and template_default_lead:
            focus.default_lead = template_default_lead

        if (
            focus.default_title != original_default_title
            or focus.default_lead != original_default_lead
        ):
            focus.save(update_fields=["default_title", "default_lead"])


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0196_ensure_story_source_column"),
    ]

    operations = [
        migrations.AddField(
            model_name="storytemplatefocus",
            name="default_title",
            field=models.CharField(
                blank=True,
                help_text="Optional focus-specific default title used when title generation is disabled or no title is provided by context JSON.",
                max_length=255,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="storytemplatefocus",
            name="default_lead",
            field=models.TextField(
                blank=True,
                help_text="Optional focus-specific default lead used when lead generation is disabled or no lead is provided by context JSON.",
                null=True,
            ),
        ),
        migrations.RunPython(backfill_focus_defaults, migrations.RunPython.noop),
    ]
