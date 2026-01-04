from django.db import migrations


GRAPH_TYPE_CATEGORY_ID = 6


def create_horizontal_bar_graph_type(apps, schema_editor):
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
        value="horizontal_bar",
        defaults={
            "description": "Horizontal bar chart type that swaps the x/y axes.",
        },
    )


def remove_horizontal_bar_graph_type(apps, schema_editor):
    LookupCategory = apps.get_model("reports", "LookupCategory")
    LookupValue = apps.get_model("reports", "LookupValue")

    category = LookupCategory.objects.filter(id=GRAPH_TYPE_CATEGORY_ID).first()
    if not category:
        return

    LookupValue.objects.filter(
        category=category,
        value="horizontal_bar",
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0137_add_histogram_graph_type"),
    ]

    operations = [
        migrations.RunPython(
            code=create_horizontal_bar_graph_type,
            reverse_code=remove_horizontal_bar_graph_type,
        )
    ]
