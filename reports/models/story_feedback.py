from django.db import models
from account.models import CustomUser
from story import Story


class StoryFeedback(models.Model):
    story = models.ForeignKey(
        Story,
        on_delete=models.CASCADE,
        related_name="feedbacks",
        help_text="The story being rated.",
    )
    feedback_text = models.TextField(help_text="Feedback for the story.")
    create_date = models.DateTimeField(
        auto_now_add=True, help_text="Timestamp when the feedback was created."
    )
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="story_feedbacks",
        help_text="User who provided feedback.",
    )

    class Meta:
        verbose_name = "Story Feedback"
        verbose_name_plural = "Story Feedbacks"

    def __str__(self):
        return f"Feedback for {self.story.title} by {self.user_id}"

