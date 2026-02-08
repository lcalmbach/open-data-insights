from django.db import models
from reports.utils import default_yesterday
from .story import Story


class StoryLog(models.Model):
    story = models.ForeignKey(
        Story,
        on_delete=models.CASCADE,
        related_name="story_logs",
        help_text="The story this log belongs to.",
    )
    publish_date = models.DateField(
        help_text="Date for which the log is created. Defaults to yesterday.",
    )
    reference_period_start = models.DateField(
        default=default_yesterday,
        help_text="Start date of the reference period for the log.",
    )
    reference_period_end = models.DateField(
        default=default_yesterday,
        help_text="End date of the reference period for the log.",
    )

    class Meta:
        verbose_name = "Story Log"
        verbose_name_plural = "Story Logs"

    def __str__(self):
        return f"Report {self.story.title} - {self.reference_period_start}"
