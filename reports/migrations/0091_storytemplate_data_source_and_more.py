# Generated by Django 4.2.23 on 2025-07-16 05:28

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0090_remove_storytable_title_storytable_table_template"),
    ]

    operations = [
        migrations.AddField(
            model_name="storytemplate",
            name="data_source",
            field=models.JSONField(
                default=dict,
                help_text="Data source for the story template, e.g., [{'text': 'data.bs', 'url': 'https://data.bs.ch/explore/dataset/100051']",
            ),
        ),
        migrations.AddField(
            model_name="storytemplate",
            name="other_ressources",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Additional ressource, e.g., [{'text': 'meteoblue', 'url': 'https://meteoblue.ch/station_346353']",
                null=True,
            ),
        ),
    ]
