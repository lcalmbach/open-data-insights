from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0143_alter_dataset_allow_future_data"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="UserComment",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("comment", models.TextField(help_text="User feedback / comment.")),
                ("date", models.DateTimeField(auto_now_add=True, help_text="Submission timestamp.")),
                (
                    "sentiment",
                    models.IntegerField(
                        choices=[(1, "Positive"), (2, "Neutral"), (3, "Negative")],
                        default=2,
                        help_text="1=positive, 2=neutral, 3=negative",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        help_text="User who submitted the comment.",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="user_comments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "User Comment",
                "verbose_name_plural": "User Comments",
                "ordering": ["-date"],
            },
        ),
    ]

