# Generated by Django 4.2.23 on 2025-07-09 04:23

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0079_alter_storytemplate_publish_conditions"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="storytemplate",
            name="post_publish_command",
        ),
    ]
