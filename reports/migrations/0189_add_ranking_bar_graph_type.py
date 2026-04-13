from django.db import migrations

GRAPH_TYPE_CATEGORY_ID = 6


def add_ranking_bar(apps, schema_editor):
    LookupValue = apps.get_model("reports", "LookupValue")
    LookupValue.objects.get_or_create(
        category_id=GRAPH_TYPE_CATEGORY_ID,
        value="ranking_bar",
        defaults={
            "description": "Horizontal ranking bar chart – all bars grey, one highlighted bar in a distinct colour, sorted by value.",
            "sort_order": 21,
        },
    )


def remove_ranking_bar(apps, schema_editor):
    LookupValue = apps.get_model("reports", "LookupValue")
    LookupValue.objects.filter(category_id=GRAPH_TYPE_CATEGORY_ID, value="ranking_bar").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0188_add_radar_graph_type"),
    ]

    operations = [
        migrations.RunPython(add_ranking_bar, remove_ranking_bar),
    ]
