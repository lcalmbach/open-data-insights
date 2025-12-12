from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("account", "0007_alter_customuser_managers_customuser_slug_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="Organisation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=255, unique=True)),
                (
                    "slug",
                    models.SlugField(
                        unique=True, blank=True, null=True, editable=False
                    ),
                ),
                ("created_date", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["name"],
                "verbose_name": "Organisation",
                "verbose_name_plural": "Organisations",
            },
        ),
        migrations.AddField(
            model_name="customuser",
            name="organisation",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.SET_NULL,
                related_name="members",
                to="account.organisation",
                help_text="Assign this user to an organisation to unlock organisation-specific insights.",
            ),
        ),
    ]
