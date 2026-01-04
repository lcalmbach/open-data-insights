from django.db import migrations


GRAPH_TYPE_CATEGORY_ID = 6


def create_map_markers_graph_type(apps, schema_editor):
    LookupCategory = apps.get_model("reports", "LookupCategory")
    LookupValue = apps.get_model("reports", "LookupValue")

    category, _ = LookupCategory.objects.get_or_create(
        id=GRAPH_TYPE_CATEGORY_ID,
        defaults={
            "name": "Graph Type",
            "description": "Lookup category containing available graph types.",
        },
    )

    LookupValue.objects.get_or_create(
        category=category,
        value="map_markers",
        defaults={
            "description": "Map marker plot that renders latitude/longitude data with folium.",
        },
    )


def remove_map_markers_graph_type(apps, schema_editor):
    LookupCategory = apps.get_model("reports", "LookupCategory")
    LookupValue = apps.get_model("reports", "LookupValue")

    category = LookupCategory.objects.filter(id=GRAPH_TYPE_CATEGORY_ID).first()
    if not category:
        return

    LookupValue.objects.filter(
        category=category,
        value="map_markers",
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0138_add_horizontal_bar_graph_type"),
    ]

    operations = [
        migrations.RunPython(
            code=create_map_markers_graph_type,
            reverse_code=remove_map_markers_graph_type,
        )
    ]
