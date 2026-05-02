from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0195_alter_storytemplate_prompt_text"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "ALTER TABLE reports_storytemplate "
                "ADD COLUMN IF NOT EXISTS story_source varchar(16) "
                "NOT NULL DEFAULT 'llm';"
                "UPDATE reports_storytemplate "
                "SET story_source = 'context_json' "
                "WHERE COALESCE(BTRIM(prompt_text), '') = '';"
            ),
            reverse_sql=(
                "ALTER TABLE reports_storytemplate "
                "DROP COLUMN IF EXISTS story_source;"
            ),
        ),
    ]
