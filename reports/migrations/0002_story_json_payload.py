# Generated by Django 4.2.21 on 2025-05-23 12:12

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="story",
            name="json_payload",
            field=models.JSONField(
                default="test",
                help_text="The JSON data used for the data story generation.",
            ),
            preserve_default=False,
        ),
    ]
