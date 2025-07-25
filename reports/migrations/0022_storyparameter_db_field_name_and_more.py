# Generated by Django 4.2.21 on 2025-05-29 07:36

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0021_parametercomparison_p10_parametercomparison_p90_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="storyparameter",
            name="db_field_name",
            field=models.CharField(
                default=1,
                help_text="Name of the database field where the parameter data is stored.",
                max_length=255,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="storyparameter",
            name="db_table_name",
            field=models.CharField(
                default=1,
                help_text="Name of the database table where the parameter data is stored.",
                max_length=255,
            ),
            preserve_default=False,
        ),
    ]
