# Generated by Django 4.2.21 on 2025-06-07 12:10

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0044_remove_storytemplatecontext_reference_period"),
    ]

    operations = [
        migrations.RenameField(
            model_name="storytemplatecontext",
            old_name="name",
            new_name="description",
        ),
        migrations.AddField(
            model_name="storytemplatecontext",
            name="key",
            field=models.CharField(
                default=1,
                help_text="Key for the context, e.g., 'monthly_average_all_previous_years'. This key is used to identify the context in the story template.",
                max_length=255,
            ),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="storytemplatecontext",
            name="predecessor",
            field=models.ForeignKey(
                blank=True,
                help_text="master context for this context, in case follow_up_condition is met.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="contexts",
                to="reports.storytemplatecontext",
            ),
        ),
    ]
