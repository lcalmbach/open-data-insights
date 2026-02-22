from django.db import models
from .story import Story
from .story_table_template import StoryTemplateTable
from reports.models.lookups import Language, LanguageEnum

class StoryTable(models.Model):
    story = models.ForeignKey(
        Story,
        on_delete=models.CASCADE,
        related_name="story_tables",
        help_text="The story this table belongs to.",
    )
    table_template = models.ForeignKey(
        StoryTemplateTable,
        on_delete=models.CASCADE,
        related_name="story_template_tables",
        help_text="The story template this table belongs to.",
    )
    title = models.CharField(max_length=255, help_text="Title of the table.")
    data = models.JSONField(
        default=dict,
        help_text="Data for the table, e.g., {'date': ['2023-01-01', '2023-01-02'], 'value': [10, 20]}. This should match the settings defined in the table.",
    )
    language = models.ForeignKey(
        Language,
        blank=True,     
        null=True,   
        default=LanguageEnum.ENGLISH.value,     # Default to English
        on_delete=models.SET_NULL,
        related_name="tables",
        help_text="Language of the table.",
    )
    sort_order = models.IntegerField(
        default=0, help_text="Sort order of the table within the story."
    )

    class Meta:
        verbose_name = "Table"
        verbose_name_plural = "Tables"
        ordering = ["sort_order"]  # or any other field

    def __str__(self):
        return str(self.table_template.title)
