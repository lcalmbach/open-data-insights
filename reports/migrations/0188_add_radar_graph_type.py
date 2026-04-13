from django.db import migrations

GRAPH_TYPE_CATEGORY_ID = 6


def add_radar(apps, schema_editor):
    LookupValue = apps.get_model("reports", "LookupValue")
    LookupValue.objects.get_or_create(
        category_id=GRAPH_TYPE_CATEGORY_ID,
        value="radar",
        defaults={
            "description": "Radar / spider chart – plots multiple numeric dimensions as a polygon on radial axes.",
            "sort_order": 20,
        },
    )


def remove_radar(apps, schema_editor):
    LookupValue = apps.get_model("reports", "LookupValue")
    LookupValue.objects.filter(category_id=GRAPH_TYPE_CATEGORY_ID, value="radar").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0187_storytemplate_ai_model_fk"),
    ]

    operations = [
        migrations.RunPython(add_radar, remove_radar),
    ]
