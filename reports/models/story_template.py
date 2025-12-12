import uuid
from django.db import models
from django.db.models import Q

from .managers import NaturalKeyManager
from .lookups import Period, PeriodDirection


class StoryTemplateQuerySet(models.QuerySet):
    def accessible_to(self, user):
        qs = self.filter(active=True)
        if user and getattr(user, "is_authenticated", False):
            org = getattr(user, "organisation", None)
            if org:
                return qs.filter(Q(organisation__isnull=True) | Q(organisation=org))
        return qs.filter(organisation__isnull=True)


class StoryTemplateManager(NaturalKeyManager):
    lookup_fields = ('slug',)

    def get_queryset(self):
        return StoryTemplateQuerySet(self.model, using=self._db)

    def accessible_to(self, user):
        return self.get_queryset().accessible_to(user)

class StoryTemplate(models.Model):
    slug = models.SlugField(unique=True, blank=True, null=True, editable=False)
    active = models.BooleanField(
        default=True,
        help_text="Indicates if the story template is active. Only active templates will be used for generating stories.",
    )
    has_data_sql = models.TextField(
        blank=True,
        null=True,
        help_text="SQL command to check if there is data for a given date.",
    )
    publish_conditions = models.TextField(
        help_text="SQL command to check if the story should be published. If this command returns no results, the story will not be published.",
        blank=True,
        null=True,
    )
    most_recent_day_sql = models.TextField(
        blank=True,
        null=True,
        help_text="SQL command to get the most recent day for which data is available. This is used to determine the reference period for the story.",
    )
    title = models.CharField(max_length=255, help_text="Title of the story template.")
    default_title = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Default title for the story. This title is used for the story when create_title is false.",
    )
    default_lead = models.TextField(
        blank=True,
        null=True,
        help_text="Default lead for the story. This lead is used for the story when create_lead is false.",
    )
    summary = models.TextField(
        blank=True, null=True, help_text="Lead paragraph of the story template."
    )
    description = models.TextField(
        blank=True, help_text="Description of the story template."
    )
    reference_period = models.ForeignKey(
        Period,
        on_delete=models.CASCADE,
        related_name="story_templates",
        help_text="Reference period for the story template: day, month, season, year, etc.",
    )
    period_direction = models.ForeignKey(
        PeriodDirection,
        on_delete=models.CASCADE,
        related_name="direction_story_templates",
        help_text="Direction of the period for the story template: current, previous, etc.",
    )

    data_source = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        help_text="Data source for the story template, e.g., [{'text': 'data.bs', 'url': 'https://data.bs.ch/explore/dataset/100051']",
    )
    other_ressources = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        help_text="Additional ressource, e.g., [{'text': 'meteoblue', 'url': 'https://meteoblue.ch/station_346353']",
    )
    prompt_text = models.TextField(help_text="The prompt used to generate the story.")
    temperature = models.FloatField(
        default=0.3,
        help_text="Temperature parameter for the AI model. Controls the randomness of the output.",
    )
    system_prompt = models.TextField(
        blank=True, null=True, help_text="System prompt for the AI model."
    )
    title_prompt = models.TextField(
        blank=True,
        null=True,
        help_text="Title prompt for the AI model. If empty and create_title is true, a generic prompt will be used to generate the title.",
    )
    lead_prompt = models.TextField(
        blank=True,
        null=True,
        help_text="prompt for generating the lead for the story.",
    )
    post_publish_command = models.TextField(
        blank=True,
        null=True,
        help_text="SQL command to be executed after the story is published. This can be used to update other tables or perform additional actions.",
    )
    create_title = models.BooleanField(
        default=True,
        help_text="Indicates if a title should be created for the story, If false, the default title will be used.",
    )
    create_lead = models.BooleanField(
        default=True, help_text="Indicates if a lead should be created for the story."
    )
    created_date = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp of when the story template was created.",
    )
    is_published = models.BooleanField(
        default=False,
        help_text="Indicates if the story has been made public to the users.",
    )
    organisation = models.ForeignKey(
        "account.Organisation",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="story_templates",
        help_text="Limit this template to members of a single organisation.",
    )

    class Meta:
        verbose_name = "Story Template"
        verbose_name_plural = "Story Templates"
        ordering = ["title"]  # or any other field
    
    def __str__(self):
        return f"{self.title} ({self.reference_period})"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = uuid.uuid4().hex[:8]  # or shortuuid.uuid()[:10]
        super().save(*args, **kwargs)
        
    def natural_key(self):
        return (self.slug,)
    natural_key.dependencies = []
    objects = StoryTemplateManager()
