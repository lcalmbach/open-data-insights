from django.conf import settings
from django.db import models, transaction

from .story_template import StoryTemplate



class StoryTemplateSubscription(models.Model):
    """Track a user subscription to a story template and its status."""
    story_template = models.ForeignKey(
        StoryTemplate,
        on_delete=models.CASCADE,
        related_name="subscriptions",
        help_text="Subscriptions to this template",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
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

    @classmethod
    def subscribe_user_to_templates(cls, user, templates=None):
        """Subscribe `user` to every template in `templates` (all if omitted)."""
        if templates is None:
            templates = StoryTemplate.objects.all()
        template_ids = list(templates.values_list("id", flat=True))
        if not template_ids:
            return
        existing_ids = set(
            cls.objects.filter(user=user, story_template_id__in=template_ids)
            .values_list("story_template_id", flat=True)
        )
        new_subscriptions = [
            cls(user=user, story_template_id=template_id)
            for template_id in template_ids
            if template_id not in existing_ids
        ]
        if not new_subscriptions:
            return
        with transaction.atomic():
            cls.objects.bulk_create(new_subscriptions)

    @classmethod
    def subscribe_user_to_all_templates(cls, user):
        """Subscribe `user` to every story template."""
        cls.subscribe_user_to_templates(user)
