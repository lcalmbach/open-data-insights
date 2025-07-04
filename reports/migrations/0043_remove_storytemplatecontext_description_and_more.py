# Generated by Django 4.2.21 on 2025-06-07 05:03

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0042_storytemplateparameter_db_field_name"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="storytemplatecontext",
            name="description",
        ),
        migrations.AddField(
            model_name="storytemplatecontext",
            name="context_period",
            field=models.ForeignKey(
                default=1,
                help_text="The context period for this context, e.g., 'day', 'month', 'season', 'year'.",
                on_delete=django.db.models.deletion.CASCADE,
                related_name="context_periods",
                to="reports.contextperiod",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="storytemplatecontext",
            name="name",
            field=models.CharField(
                default=1,
                help_text="Name of the context, e.g., 'Context monthly average with all previous years of same month'",
                max_length=255,
            ),
            preserve_default=False,
        ),
    ]
