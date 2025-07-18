# Generated by Django 4.2.23 on 2025-06-30 13:56

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0074_alter_storytemplate_publish_conditions"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="dataset",
            options={
                "ordering": ["name"],
                "verbose_name": "Dataset",
                "verbose_name_plural": "Datasets",
            },
        ),
        migrations.AlterModelOptions(
            name="storytemplate",
            options={
                "ordering": ["title"],
                "verbose_name": "Story Template",
                "verbose_name_plural": "Story Templates",
            },
        ),
        migrations.RemoveField(
            model_name="storytemplatecontext",
            name="follow_up_command",
        ),
        migrations.RemoveField(
            model_name="storytemplatecontext",
            name="predecessor",
        ),
        migrations.AddField(
            model_name="storytemplate",
            name="post_publish_command",
            field=models.TextField(
                blank=True,
                help_text="SQL command to be executed after the story is published. This can be used to update the story template or perform other actions.",
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="dataset",
            name="db_timestamp_field",
            field=models.CharField(
                blank=True,
                help_text="Field in the database that contordering = ['title']  # or any other fieldains the timestamp.",
                max_length=255,
                null=True,
            ),
        ),
    ]
