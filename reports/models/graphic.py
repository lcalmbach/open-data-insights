from django.db import models
from .graphic_template import StoryTemplateGraphic
from .story import Story


class Graphic(models.Model):
    story = models.ForeignKey(
        Story,
        on_delete=models.CASCADE,
        related_name="story_graphics",
        help_text="The story this graph belongs to.",
    )
    graphic_template = models.ForeignKey(
        StoryTemplateGraphic,
        on_delete=models.CASCADE,
        related_name="story_template_graphics",
        help_text="The story template this graphic belongs to.",
    )
    title = models.CharField(max_length=255, help_text="Title of the graphic.")
    content_html = models.TextField(
        blank=True,
        null=True,
        help_text="HTML content of the graphic. This is used to render the graphic in the story view.",
    )
    data = models.JSONField(
        default=dict,
        help_text="Data for the graphic, e.g., {'date': ['2023-01-01', '2023-01-02'], 'value': [10, 20]}. This should match the settings defined in the graphic.",
    )
    sort_order = models.IntegerField(
        default=0, help_text="Sort order of the graphic within the story."
    )

    class Meta:
        verbose_name = "Graphic"
        verbose_name_plural = "Graphics"
        ordering = ["sort_order"]  # or any other field

    def __str__(self):
        return str(self.title)

