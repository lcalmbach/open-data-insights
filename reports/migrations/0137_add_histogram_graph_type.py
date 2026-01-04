from django.db import migrations


GRAPH_TYPE_CATEGORY_ID = 6


def create_histogram_graph_type(apps, schema_editor):
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
        value="histogram",
        defaults={
            "description": "Histogram plot type for binning quantitative data.",
        },
    )


def remove_histogram_graph_type(apps, schema_editor):
    LookupCategory = apps.get_model("reports", "LookupCategory")
    LookupValue = apps.get_model("reports", "LookupValue")

    category = LookupCategory.objects.filter(id=GRAPH_TYPE_CATEGORY_ID).first()
    if not category:
        return

    LookupValue.objects.filter(
        category=category,
        value="histogram",
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0136_remove_dataset_calculated_fields_and_more"),
    ]

    operations = [
        migrations.RunPython(
            code=create_histogram_graph_type,
            reverse_code=remove_histogram_graph_type,
        )
    ]
