from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("account", "0008_organisation"),
        ("reports", "0124_rename_authro_wiki_url_quote_author_wiki_url"),
    ]

    operations = [
        migrations.AddField(
            model_name="storytemplate",
            name="organisation",
            field=models.ForeignKey(
                blank=True,
                help_text="Limit this template to members of a single organisation.",
                null=True,
                on_delete=models.SET_NULL,
                related_name="story_templates",
                to="account.organisation",
            ),
        ),
    ]
