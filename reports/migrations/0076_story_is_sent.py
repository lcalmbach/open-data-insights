# Generated by Django 4.2.23 on 2025-07-01 04:36

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0075_alter_dataset_options_alter_storytemplate_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="story",
            name="is_sent",
            field=models.BooleanField(
                default=False,
                help_text="Indicates if the story has been sent to the user.",
            ),
        ),
    ]
