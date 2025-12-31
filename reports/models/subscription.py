from django.db import models
from .story_template import StoryTemplate
from account.models import CustomUser



class StoryTemplateSubscription(models.Model):
    """Track a user subscription to a story template and its status."""
    story_template = models.ForeignKey(
        StoryTemplate,
        on_delete=models.CASCADE,
        related_name="subscriptions",
        help_text="Subscriptions to this template",
    )
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="story_template_subscriptions",
        help_text="User who subscribed to the story template.",
    )
    create_date = models.DateTimeField(
        auto_now_add=True, help_text="Timestamp when the subscription was created."
    )
    cancellation_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the subscription was ended by the user. Null if still active.",
    )
    cancel_reason_text = models.TextField(
        blank=True,
        null=True,
        help_text="Optional text explaining why the subscription was revoked.",
    )

    class Meta:
        verbose_name = "Story Template Subscription"
        verbose_name_plural = "Story Template Subscriptions"
        ordering = ["-create_date"]

    def __str__(self):
        return f"{self.story_template.title} > {self.user.last_name}"
