# Generated by Django 4.2.21 on 2025-05-25 09:16

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0007_dataset_aggregations_dataset_fields"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="dataset",
            name="fields",
        ),
        migrations.AddField(
            model_name="dataset",
            name="fields_selection",
            field=models.JSONField(
                default=[],
                help_text="List of fields in the dataset to be imported. Empty list if all fields will be imported.",
            ),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="dataset",
            name="aggregations",
            field=models.JSONField(
                default=list,
                help_text="List of aggregations to be applied to the if data frequency is > daily. Format: {'group_by_field: 'timestamp', 'target_field_name': 'date', 'parameters': [precipitation: ['sum'], 'temperature': ['min', 'max', 'mean']]}",
            ),
        ),
    ]
