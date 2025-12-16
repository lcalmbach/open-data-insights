import json
from django.db import models
from django.urls import reverse
from pydantic import ValidationError
from report_generator import settings
from base.utils import default_yesterday
from .story_template import StoryTemplate


class Story(models.Model):
    template = models.ForeignKey(
        StoryTemplate,
        on_delete=models.CASCADE,
        related_name="stories",
        help_text="The template used to generate the story.",
    )
    title = models.CharField(
        max_length=255, help_text="Title of the story.", blank=True, null=True
    )
    summary = models.TextField(
        blank=True,
        null=True,
        help_text="Summary of the story template. This is used to provide a brief overview of the story.",
    )
    published_date = models.DateField(
        auto_now_add=True,
        help_text="Date when the story was published.",
        blank=True,
        null=True,
    )
    prompt_text = models.TextField(
        help_text="The prompt used to generate the story.", blank=True, null=True
    )
    context_values = models.JSONField(
        help_text="The JSON data used for the data story generation.",
        blank=True,
        null=True,
    )
    ai_model = models.CharField(
        max_length=50,
        help_text="AI model used for generating the story.",
        blank=True,
        null=True,
    )
    reference_period_start = models.DateField(
        default=default_yesterday,
        help_text="Start date of the reference period for the story.",
        blank=True,
        null=True,
    )
    reference_period_end = models.DateField(
        default=default_yesterday,
        help_text="End date of the reference period for the story.",
        blank=True,
        null=True,
    )
    content = models.TextField(help_text="Content of the story.", blank=True, null=True)

    @property
    def reference_period(self):
        if self.reference_period_start == self.reference_period_end:
            return self.reference_period_start.strftime("%Y-%m-%d")
        else:
            return f"{ self.reference_period_start.strftime('%Y-%m-%d') } – { self.reference_period_end.strftime('%Y-%m-%d') }"

    def reference_month(self):
        return self.reference_period_start.strftime("%B %Y")

    def reference_year(self):
        return self.reference_period_start.strftime("%Y")

    def __str__(self):
        return f"Report {self.title} - {self.published_date}"

    def clean(self):
        """Validate all model fields to prevent silent failures"""
        super().clean()

        # Check required fields
        if not self.title:
            raise ValidationError({"title": "Title is required"})

        if self.template is None:
            raise ValidationError({"template": "Story template is required"})

        if not self.content:
            raise ValidationError({"content": "Content is required"})

        # Validate date fields
        if self.reference_period_start and self.reference_period_end:
            if self.reference_period_start > self.reference_period_end:
                raise ValidationError(
                    {
                        "reference_period_start": "Reference period start date cannot be after end date"
                    }
                )
        # Validate context_values field
        if self.context_values:
            try:
                if isinstance(self.context_values, str):
                    json_obj = json.loads(self.context_values)
                    # Validate structure - check if it has expected keys
                    if not isinstance(json_obj, dict):
                        raise ValidationError(
                            {"context_values": "Must be a valid JSON object"}
                        )

                    if "context_data" not in json_obj:
                        raise ValidationError(
                            {
                                "context_values": 'Missing "context_data" key in context values'
                            }
                        )

                    # Verify context_data is a dictionary
                    if not isinstance(json_obj["context_data"], dict):
                        raise ValidationError(
                            {"context_values": '"context_data" must be a JSON object'}
                        )

            except json.JSONDecodeError:
                raise ValidationError({"context_values": "Invalid JSON format"})

        # Validate AI model field
        valid_ai_models = [
            "gpt-4o",
            "gpt-4",
            "gpt-3.5-turbo",
        ]  # Update with your valid models
        if self.ai_model and self.ai_model not in valid_ai_models:
            raise ValidationError(
                {
                    "ai_model": f'Invalid AI model. Choose from: {", ".join(valid_ai_models)}'
                }
            )

    def get_absolute_url(self):
        return settings.APP_ROOT.rstrip("/") + reverse("story_detail", args=[self.id])

    def get_email_list_entry(self):
        return f"<b>{self.title}:</b></br><p>{self.summary}<p>"
