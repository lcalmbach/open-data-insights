from django.db import migrations, models
import django.db.models.deletion
from django.db.models import Q


def forwards(apps, schema_editor):
    Story = apps.get_model("reports", "Story")
    StoryTemplateFocus = apps.get_model("reports", "StoryTemplateFocus")

    # Map each StoryTemplate -> default StoryTemplateFocus (create if missing).
    template_to_focus = {}

    for story in Story.objects.exclude(template_id__isnull=True).only("id", "template_id"):
        template_id = story.template_id
        if template_id in template_to_focus:
            continue

        focus = (
            StoryTemplateFocus.objects.filter(story_template_id=template_id)
            .filter(Q(focus_filter__isnull=True) | Q(focus_filter=""))
            .order_by("id")
            .first()
        )
        if focus is None:
            focus = StoryTemplateFocus.objects.create(
                story_template_id=template_id,
                focus_filter="",
                filter_value=None,
                focus_subject=None,
                additional_context=None,
                image=None,
            )
        template_to_focus[template_id] = focus.id

    # Assign templatefocus for all existing stories.
    for story in Story.objects.exclude(template_id__isnull=True).only("id", "template_id"):
        focus_id = template_to_focus.get(story.template_id)
        if focus_id:
            Story.objects.filter(id=story.id).update(templatefocus_id=focus_id)


def backwards(apps, schema_editor):
    Story = apps.get_model("reports", "Story")
    # Best-effort reverse: copy storytemplate back from focus.
    Story.objects.exclude(templatefocus_id__isnull=True).update(
        template_id=models.F("templatefocus__story_template_id")
    )


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0158_rename_filter_condition_storytemplatefocus_focus_filter"),
    ]

    operations = [
        migrations.AddField(
            model_name="story",
            name="templatefocus",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="stories",
                to="reports.storytemplatefocus",
            ),
        ),
        migrations.RunPython(forwards, backwards),
        migrations.AlterField(
            model_name="story",
            name="templatefocus",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="stories",
                to="reports.storytemplatefocus",
            ),
        ),
        migrations.RemoveField(
            model_name="story",
            name="template",
        ),
    ]

