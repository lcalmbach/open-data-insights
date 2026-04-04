"""
Replace StoryTemplate.ai_model CharField with a ForeignKey to LookupValue.

Steps:
1. Rename the old CharField to ai_model_old (preserves data).
2. Add the new FK field ai_model (nullable).
3. Create the AI Model LookupCategory (id=13) and seed known models.
4. Populate the FK on existing templates from the old string value.
5. Drop the old field.
"""

import django.db.models.deletion
from django.db import migrations, models

AI_MODEL_CATEGORY_ID = 13

SEED_MODELS = [
    {"key": "gpt-4o", "value": "GPT-4o (OpenAI)", "sort_order": 1},
    {"key": "deepseek-chat", "value": "DeepSeek Chat", "sort_order": 2},
    {"key": "claude-opus-4-6", "value": "Claude Opus 4.6 (Anthropic)", "sort_order": 3},
    {"key": "claude-sonnet-4-6", "value": "Claude Sonnet 4.6 (Anthropic)", "sort_order": 4},
    {"key": "claude-haiku-4-5", "value": "Claude Haiku 4.5 (Anthropic)", "sort_order": 5},
]


def populate_ai_model_fk(apps, schema_editor):
    LookupCategory = apps.get_model("reports", "LookupCategory")
    LookupValue = apps.get_model("reports", "LookupValue")
    StoryTemplate = apps.get_model("reports", "StoryTemplate")

    category, _ = LookupCategory.objects.get_or_create(
        id=AI_MODEL_CATEGORY_ID,
        defaults={
            "name": "AI Model",
            "description": "LLM models available for story generation.",
        },
    )

    key_to_lv = {}
    for entry in SEED_MODELS:
        lv, _ = LookupValue.objects.get_or_create(
            category=category,
            key=entry["key"],
            defaults={"value": entry["value"], "sort_order": entry["sort_order"]},
        )
        key_to_lv[entry["key"]] = lv

    for template in StoryTemplate.objects.all():
        old_key = (template.ai_model_old or "").strip()
        lv = key_to_lv.get(old_key)
        if lv:
            template.ai_model = lv
            template.save(update_fields=["ai_model"])


def restore_ai_model_old(apps, schema_editor):
    StoryTemplate = apps.get_model("reports", "StoryTemplate")
    for template in StoryTemplate.objects.select_related("ai_model").all():
        if template.ai_model_id:
            lv = template.ai_model
            template.ai_model_old = lv.key or lv.value or ""
            template.save(update_fields=["ai_model_old"])


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0186_fix_lookup_taxonomy_relations"),
    ]

    operations = [
        # 1. Preserve old string value under a temp name
        migrations.RenameField(
            model_name="storytemplate",
            old_name="ai_model",
            new_name="ai_model_old",
        ),
        # 2. Add the new FK (nullable so existing rows are valid before data migration)
        migrations.AddField(
            model_name="storytemplate",
            name="ai_model",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="reports.lookupvalue",
                limit_choices_to={"category_id": AI_MODEL_CATEGORY_ID},
                help_text="AI model to use for story generation.",
            ),
        ),
        # 3 + 4. Seed lookup data and populate FK
        migrations.RunPython(populate_ai_model_fk, restore_ai_model_old),
        # 5. Drop old field
        migrations.RemoveField(
            model_name="storytemplate",
            name="ai_model_old",
        ),
    ]
