import uuid
from django.db import models
from .story_template import StoryTemplate
from .lookups import GraphType
from .managers import NaturalKeyManager


class StoryTemplateGraphicManager(NaturalKeyManager):
    lookup_fields = ('story_template__slug', 'slug')

class StoryTemplateGraphic(models.Model):
    story_template = models.ForeignKey(
        StoryTemplate,
        on_delete=models.CASCADE,
        related_name="graphic_templates",
        help_text="The story template this graphic belongs to.",
    )
    slug = models.SlugField(blank=True, null=True, editable=False)
    title = models.CharField(max_length=255, help_text="Title of the graphic.")
    settings = models.JSONField(
        default=dict,
        help_text="Settings for the graphic, e.g., {'type': 'bar', 'x': 'date', 'y': 'value'}. This can include any settings required by the graphic library used.",
    )
    sql_command = models.TextField(
        help_text="SQL command to get the data for the graphic, e.g., 'SELECT date, value FROM weather_data WHERE date >= %s AND date <= %s'. This command should return the data in a format suitable for the graphic library used.",
    )
    graphic_type = models.ForeignKey(
        GraphType,
        on_delete=models.CASCADE,
        help_text="Type of the graphic, e.g., 'line', 'bar', 'pie'.",
    )
    sort_order = models.IntegerField(
        default=0, help_text="Sort order of the graphic within the story template."
    )

    class Meta:
        verbose_name = "Graphic Template"
        verbose_name_plural = "Graphics Templates"
        ordering = ["sort_order"]  

    def __str__(self):
        return self.title
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = uuid.uuid4().hex[:8]  # or shortuuid.uuid()[:10]
        super().save(*args, **kwargs)
        
    def natural_key(self):
        return (self.story_template.slug, self.slug)
    natural_key.dependencies = ['reports.storytemplate']
    objects = StoryTemplateGraphicManager()




