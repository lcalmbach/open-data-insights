import uuid
from django.db import models
from django.db.models import Q

from .managers import NaturalKeyManager
from .lookups import Period, PeriodDirection


class StoryTemplateQuerySet(models.QuerySet):
    """QuerySet helpers for story templates, primarily filtering by access."""

    def accessible_to(self, user):
        qs = self.filter(active=True)
        if user and getattr(user, "is_authenticated", False):
            org = getattr(user, "organisation", None)
            if org:
                return qs.filter(Q(organisation__isnull=True) | Q(organisation=org))
        return qs.filter(organisation__isnull=True)


class StoryTemplateManager(NaturalKeyManager):
    """Manager providing natural key lookups and scoped querysets for story templates."""

    lookup_fields = ("slug",)

    def get_queryset(self):
        return StoryTemplateQuerySet(self.model, using=self._db)

    def accessible_to(self, user):
        return self.get_queryset().accessible_to(user)


class StoryTemplate(models.Model):
    """Model representing a configurable template for generating stories."""

    slug = models.SlugField(unique=True, blank=True, null=True, editable=False)
    active = models.BooleanField(
        default=True,
        help_text="Indicates if the story template is active. Only active templates will be used for generating stories.",
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
    ai_model = models.CharField(
        max_length=255,
        default="gpt-4o",
        null=True,
        blank=True,
        help_text="AI model to use for generating the story. This can be set to 'deepseek-chat' to use the Deepseek API instead of OpenAI.",
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

    @property
    def default_focus(self):
        """
        Return the "default" focus row for this template:
        - Prefer the focus row without a filter value (single-insight templates)
        - Fallback to the first focus row, if all have filter values
        """
        qs = getattr(self, "focus_areas", None)
        if qs is None:
            return None
        return (
            qs.filter(Q(filter_value__isnull=True) | Q(filter_value=""))
            .order_by("id")
            .first()
            or qs.order_by("id").first()
        )


class StoryTemplateDataset(models.Model):
    """Join table linking story templates to datasets they rely on."""

    story_template = models.ForeignKey(
        StoryTemplate, on_delete=models.CASCADE, related_name="datasets"
    )
    dataset = models.ForeignKey(
        "Dataset", on_delete=models.CASCADE, related_name="story_templates"
    )

    class Meta:
        verbose_name = "StoryTemplate-Dataset relation"
        verbose_name_plural = "StoryTemplate-Dataset relations"
        unique_together = ("story_template", "dataset")

    def __str__(self):
        return f"{self.story_template.title} - {self.dataset.name}"


class StoryTemplateFocus(models.Model):
    """
    A focus row attached to a StoryTemplate.

    Normal (single-insight) templates should have exactly one focus row with no
    `filter_value`. Multi-focus templates can have multiple rows, each with a
    different `filter_value`.
    """

    story_template = models.ForeignKey(
        StoryTemplate,
        on_delete=models.CASCADE,
        related_name="focus_areas",
    )
    publish_conditions = models.TextField(
        blank=True,
        null=True,
        help_text="SQL command to check if the story should be published for this focus. If this command returns no results, the story will not be published.",
    )
    filter_expression = models.CharField(
        max_length=255,
        help_text="Expression to be pasted in text templates, e.g. the title. The filter value may be a numeric code in which case the filter expression is the associated expression.",
        blank=True,
        null=True,
    )
    filter_value = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Optional SQL filter value to apply for this focus area, e.g., 'Zurich' or 'Health'.",
    )
    focus_subject = models.TextField(
        help_text="Additional instructions for LLM on what to focus on in the insight content, 'Focus on population growth since 2022' or 'Focus on Health category'.",
        blank=True,
        null=True,
    )
    image = models.ImageField(
        blank=True,
        null=True,
        upload_to="story_template_focus/",
        help_text="Optional image shown for this focus.",
    )

    class Meta:
        verbose_name = "Story Template Focus"
        verbose_name_plural = "Story Template Focuses"
        constraints = [
            models.UniqueConstraint(
                fields=["story_template", "filter_value"],
                condition=Q(filter_value__isnull=False) & ~Q(filter_value=""),
                name="uniq_filter_value_per_template",
            ),
            models.UniqueConstraint(
                fields=["story_template"],
                condition=Q(filter_value__isnull=True) | Q(filter_value=""),
                name="uniq_default_focus_per_template",
            ),
        ]

    def __str__(self):
        suffix = (self.filter_expression or self.filter_value or "").strip()
        if suffix:
            return f"{self.story_template.title} ({suffix})"
        return f"{self.story_template.title} (default)"
