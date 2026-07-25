"""
DeepSeek retired the `deepseek-chat` model name in favour of
`deepseek-v4-pro` / `deepseek-v4-flash`. The LookupValue.key is sent
verbatim as the API model name, so the old key now returns HTTP 400.

Rename the existing `deepseek-chat` LookupValue to `deepseek-v4-pro`
(preserving the FK on any StoryTemplate that points at it) and add
`deepseek-v4-flash` as an additional option.
"""

from django.db import migrations

AI_MODEL_CATEGORY_ID = 13


def update_deepseek_keys(apps, schema_editor):
    LookupValue = apps.get_model("reports", "LookupValue")

    # Rename the retired chat model in place so existing FKs stay valid.
    LookupValue.objects.filter(
        category_id=AI_MODEL_CATEGORY_ID, key="deepseek-chat"
    ).update(key="deepseek-v4-pro", value="DeepSeek V4 Pro")

    # Add the flash variant as a selectable option.
    LookupValue.objects.get_or_create(
        category_id=AI_MODEL_CATEGORY_ID,
        key="deepseek-v4-flash",
        defaults={"value": "DeepSeek V4 Flash", "sort_order": 6},
    )


def revert_deepseek_keys(apps, schema_editor):
    LookupValue = apps.get_model("reports", "LookupValue")
    LookupValue.objects.filter(
        category_id=AI_MODEL_CATEGORY_ID, key="deepseek-v4-flash"
    ).delete()
    LookupValue.objects.filter(
        category_id=AI_MODEL_CATEGORY_ID, key="deepseek-v4-pro"
    ).update(key="deepseek-chat", value="DeepSeek Chat")


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0204_simulationtemplate_slug"),
    ]

    operations = [
        migrations.RunPython(update_deepseek_keys, revert_deepseek_keys),
    ]
