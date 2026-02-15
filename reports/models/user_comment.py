from django.conf import settings
from django.db import models


class UserComment(models.Model):
    SENTIMENT_POSITIVE = 1
    SENTIMENT_NEUTRAL = 2
    SENTIMENT_NEGATIVE = 3

    SENTIMENT_CHOICES = (
        (SENTIMENT_POSITIVE, "Positive"),
        (SENTIMENT_NEUTRAL, "Neutral"),
        (SENTIMENT_NEGATIVE, "Negative"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="user_comments",
        help_text="User who submitted the comment.",
    )
    comment = models.TextField(help_text="User feedback / comment.")
    date = models.DateTimeField(auto_now_add=True, help_text="Submission timestamp.")
    sentiment = models.IntegerField(
        choices=SENTIMENT_CHOICES,
        default=SENTIMENT_NEUTRAL,
        help_text="1=positive, 2=neutral, 3=negative",
    )

    class Meta:
        verbose_name = "User Comment"
        verbose_name_plural = "User Comments"
        ordering = ["-date"]

    def __str__(self):
        return f"UserComment {self.id} by {self.user_id}"
