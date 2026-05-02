from django.db import migrations, models


def populate_story_source(apps, schema_editor):
    StoryTemplate = apps.get_model("reports", "StoryTemplate")
    StoryTemplate.objects.filter(prompt_text__isnull=True).update(story_source="context_json")
    StoryTemplate.objects.filter(prompt_text="").update(story_source="context_json")


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0194_storyaccess_remove_title_snapshot"),
    ]

    operations = [
        migrations.AddField(
            model_name="storytemplate",
            name="story_source",
            field=models.CharField(
                choices=[
                    ("llm", "Generate article with LLM"),
                    ("context_json", "Read article directly from context JSON"),
                ],
                default="llm",
                help_text="Where the article content comes from: generate it with an LLM or read title/lead/body directly from context JSON.",
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="storytemplate",
            name="prompt_text",
            field=models.TextField(
                blank=True,
                null=True,
                help_text="The prompt used to generate the story. Leave empty when the story body is provided directly via context JSON.",
            ),
        ),
        migrations.RunPython(populate_story_source, migrations.RunPython.noop),
    ]