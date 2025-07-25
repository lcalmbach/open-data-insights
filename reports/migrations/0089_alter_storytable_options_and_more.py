# Generated by Django 4.2.23 on 2025-07-16 04:52

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0088_remove_storygraphic_data_and_more"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="storytable",
            options={
                "ordering": ["sort_order"],
                "verbose_name": "Table",
                "verbose_name_plural": "Tables",
            },
        ),
        migrations.AlterModelOptions(
            name="storytemplatetable",
            options={
                "ordering": ["sort_order"],
                "verbose_name": "Table template",
                "verbose_name_plural": "Table templates",
            },
        ),
        migrations.RemoveField(
            model_name="storytable",
            name="settings",
        ),
    ]
