

from django.db import models
from account.models import CustomUser
from .story import Story

class StoryRating(models.Model):
    story = models.ForeignKey(
        Story,
        on_delete=models.CASCADE,
        related_name="ratings",
        help_text="The story being rated.",
    )
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="story_ratings",
        help_text="User who rated the story.",
    )
    rating = models.IntegerField(help_text="Rating given to the story.")
    create_date = models.DateTimeField(
        auto_now_add=True, help_text="Timestamp when the rating was created."
    )
    rating_text = models.TextField(
        blank=True, help_text="Optional feedback for the story."
    )

    class Meta:
        verbose_name = "Story Rating"
        verbose_name_plural = "Story Ratings"

    def __str__(self):
        return f"Rating {self.rating} for {self.story.title}"