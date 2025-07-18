# Generated by Django 4.2.21 on 2025-06-09 05:21

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0049_alter_dataset_db_timestamp_field"),
    ]

    operations = [
        migrations.AddField(
            model_name="dataset",
            name="record_identifier_field",
            field=models.CharField(
                default="test",
                help_text="Field in the source dataset that uniquely identifies a record. If not set, the first field will be used.",
                max_length=255,
            ),
            preserve_default=False,
        ),
    ]
