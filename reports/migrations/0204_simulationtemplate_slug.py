from django.db import migrations, models
from django.utils.text import slugify


def populate_slugs(apps, schema_editor):
    SimulationTemplate = apps.get_model("reports", "SimulationTemplate")
    for tmpl in SimulationTemplate.objects.all():
        base = slugify(tmpl.title)[:100]
        slug = base
        n = 1
        while SimulationTemplate.objects.filter(slug=slug).exclude(pk=tmpl.pk).exists():
            slug = f"{base[:95]}-{n}"
            n += 1
        tmpl.slug = slug
        tmpl.save(update_fields=["slug"])


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0203_simulation_remove_story_template_fk"),
    ]

    operations = [
        # Add without any index so that deferred SQL list stays clean.
        migrations.AddField(
            model_name="simulationtemplate",
            name="slug",
            field=models.SlugField(
                blank=True, editable=False, max_length=100,
                default="", db_index=False,
            ),
            preserve_default=False,
        ),
        migrations.RunPython(populate_slugs, migrations.RunPython.noop),
        # Now add unique constraint (creates index once).
        migrations.AlterField(
            model_name="simulationtemplate",
            name="slug",
            field=models.SlugField(blank=True, editable=False, max_length=100, unique=True),
        ),
    ]
