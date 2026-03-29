from django.db import migrations, models
import django.db.models.deletion


REGION_CATEGORY_ID = 11
TOPIC_CATEGORY_ID = 12


def create_taxonomy_categories(apps, schema_editor):
    LookupCategory = apps.get_model("reports", "LookupCategory")
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


def delete_taxonomy_categories(apps, schema_editor):
    LookupCategory = apps.get_model("reports", "LookupCategory")
    LookupCategory.objects.filter(id__in=[REGION_CATEGORY_ID, TOPIC_CATEGORY_ID]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0183_storyimage_image_identifier_key"),
    ]

    operations = [
        migrations.RunPython(create_taxonomy_categories, delete_taxonomy_categories),
        migrations.AddField(
            model_name="storytemplate",
            name="region",
            field=models.ForeignKey(
                blank=True,
                help_text="Primary geographic coverage for this template.",
                limit_choices_to={"category_id": REGION_CATEGORY_ID},
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="story_templates_as_region",
                to="reports.lookupvalue",
            ),
        ),
        migrations.AddField(
            model_name="storytemplate",
            name="topics",
            field=models.ManyToManyField(
                blank=True,
                help_text="Editorial topics associated with this template.",
                limit_choices_to={"category_id": TOPIC_CATEGORY_ID},
                related_name="story_templates_by_topic",
                to="reports.lookupvalue",
            ),
        ),
    ]
