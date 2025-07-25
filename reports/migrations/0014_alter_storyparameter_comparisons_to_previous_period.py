# Generated by Django 4.2.21 on 2025-05-28 04:32

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0013_storyparameter_period_alter_storytemplate_options_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="storyparameter",
            name="comparisons_to_previous_period",
            field=models.JSONField(
                blank=True,
                help_text="Optional text to compare the parameter to the previous period.",
            ),
        ),
    ]
