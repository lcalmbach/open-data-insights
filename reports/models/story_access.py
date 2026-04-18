from __future__ import annotations

import re
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


# Common bot / crawler / scraper signatures in the User-Agent string.
_BOT_RE = re.compile(
    r"bot|crawl|spider|slurp|mediapartners|facebookexternalhit|"
    r"python-requests|python-urllib|curl|wget|axios|scrapy|"
    r"go-http-client|java/|ruby|php|perl|libwww|httpie|insomnia|postman|"
    r"okhttp|apache-httpclient|aiohttp|node-fetch|got/|undici|"
    r"check_http|uptimerobot|pingdom|statuscake|site24x7|"
    r"sentry|datadog|newrelic|nagios",
    re.IGNORECASE,
)

# How long a revisit from the same visitor counts as a duplicate (no re-log).
_DEDUP_WINDOW = timedelta(minutes=5)


def _is_bot(user_agent: str) -> bool:
    if not user_agent:
        return False
    return bool(_BOT_RE.search(user_agent))


class StoryAccess(models.Model):
    story = models.ForeignKey(
        "reports.Story",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="accesses",
        help_text="Story that was accessed. Kept as NULL after story deletion.",
    )
    story_id_snapshot = models.IntegerField(
        help_text="Original story PK at time of access (preserved after deletion).",
    )
    story_title_snapshot = models.CharField(
        max_length=255,
        blank=True,
        help_text="Story title at time of access.",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="story_accesses",
        help_text="Authenticated user, or NULL for anonymous visitors.",
    )
    accessed_at = models.DateTimeField(auto_now_add=True, db_index=True)
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="Client IP — used for anonymous deduplication.",
    )
    user_agent = models.CharField(
        max_length=512,
        blank=True,
        help_text="Raw User-Agent header.",
    )
    is_bot = models.BooleanField(
        default=False,
        db_index=True,
        help_text="True when the User-Agent matches a known bot/crawler pattern.",
    )

    class Meta:
        verbose_name = "Story Access"
        verbose_name_plural = "Story Accesses"
        ordering = ["-accessed_at"]
        indexes = [
            models.Index(fields=["story", "accessed_at"]),
            models.Index(fields=["user", "accessed_at"]),
        ]

    def __str__(self):
        who = self.user or self.ip_address or "anonymous"
        return f"{self.story_title_snapshot} – {who} @ {self.accessed_at:%Y-%m-%d %H:%M}"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def log(cls, request, story) -> "StoryAccess | None":
        """Create a StoryAccess entry for *request* viewing *story*.

        Returns the new instance, or None if the visit was deduplicated
        (same visitor, same story, within the dedup window).
        Bots are always logged without deduplication.
        """
        ua = request.META.get("HTTP_USER_AGENT", "")[:512]
        bot = _is_bot(ua)
        ip = _get_client_ip(request)
        user = request.user if request.user.is_authenticated else None

        if not bot:
            cutoff = timezone.now() - _DEDUP_WINDOW
            if user is not None:
                duplicate = cls.objects.filter(
                    story_id=story.pk,
                    user=user,
                    accessed_at__gte=cutoff,
                ).exists()
            else:
                duplicate = cls.objects.filter(
                    story_id=story.pk,
                    ip_address=ip,
                    accessed_at__gte=cutoff,
                ).exists()
            if duplicate:
                return None

        return cls.objects.create(
            story=story,
            story_id_snapshot=story.pk,
            story_title_snapshot=(story.title or "")[:255],
            user=user,
            ip_address=ip,
            user_agent=ua,
            is_bot=bot,
        )


def _get_client_ip(request) -> str | None:
    """Return the real client IP, respecting X-Forwarded-For if present."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")
