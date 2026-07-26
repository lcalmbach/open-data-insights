"""
Story.ai_model stores a string snapshot of the model a story was generated
with. Existing stories still hold the retired `deepseek-chat` name, and the
regeneration path reuses that stored value (only falling back to the template
when it is empty), so re-generating any of them sends `deepseek-chat` to the
API and fails with HTTP 400.

Migration 0205 renamed the LookupValue; this does the parallel update for the
snapshot strings on existing Story rows.
"""

from django.db import migrations


def to_v4(apps, schema_editor):
    Story = apps.get_model("reports", "Story")
    Story.objects.filter(ai_model="deepseek-chat").update(ai_model="deepseek-v4-pro")


def to_chat(apps, schema_editor):
    Story = apps.get_model("reports", "Story")
    Story.objects.filter(ai_model="deepseek-v4-pro").update(ai_model="deepseek-chat")


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0207_dataset27_drop_stale_publisher_field"),
    ]

    operations = [
        migrations.RunPython(to_v4, to_chat),
    ]
