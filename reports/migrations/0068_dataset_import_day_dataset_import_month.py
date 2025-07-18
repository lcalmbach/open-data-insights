# Generated by Django 4.2.21 on 2025-06-18 04:27

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0067_alter_storytemplate_run_day_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="dataset",
            name="import_day",
            field=models.IntegerField(
                blank=True,
                help_text="Day of the month when the dataset should be imported. If left empty, the dataset will be imported every day.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="dataset",
            name="import_month",
            field=models.IntegerField(
                blank=True,
                help_text="Month of the year when the dataset should be imported. If left empty, the dataset will be imported every month.",
                null=True,
            ),
        ),
    ]
