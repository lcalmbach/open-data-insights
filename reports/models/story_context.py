import uuid
from django.db import models
from .story_template import StoryTemplate
from .managers import NaturalKeyManager


class StoryTemplateContextManager(NaturalKeyManager):
    lookup_fields = ("story_template__slug", "slug")


class StoryTemplateContext(models.Model):
    story_template = models.ForeignKey(
        StoryTemplate,
        on_delete=models.CASCADE,
        related_name="contexts",
        help_text="The story this context belongs to.",
    )
    slug = models.SlugField(blank=True, null=True, editable=False)
    description = models.TextField(
        max_length=1000,
        help_text="Name of the context, e.g., 'Context monthly average with all previous years of same month'",
    )
    key = models.CharField(
        max_length=255,
        help_text="Key for the context, e.g., 'monthly_average_all_previous_years'. This key is used to identify the context in the story template.",
    )
    sql_command = models.TextField(
        help_text="SQL command to get the value for the context, e.g., 'SELECT AVG(temperature) FROM weather_data WHERE date >= %s AND date <= %s'.",
    )
    sort_order = models.IntegerField(
        default=0,
        help_text="Sort order of the context within the story template.",
    )

    class Meta:
        verbose_name = "Story Template Context"
        verbose_name_plural = "Story Template Contexts"
        ordering = ["sort_order"]

    def __str__(self):
        return self.key

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = uuid.uuid4().hex[:8]  # or shortuuid.uuid()[:10]
        super().save(*args, **kwargs)

    def natural_key(self):
        return (self.story_template.slug, self.slug)

    natural_key.dependencies = ["reports.storytemplate"]
    objects = StoryTemplateContextManager()
