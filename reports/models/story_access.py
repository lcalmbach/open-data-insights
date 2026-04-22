from __future__ import annotations

import re
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


# Ordered list of (label, pattern) pairs.  First match wins, so put the most
# specific / well-known bots first and the generic catch-alls last.
_BOT_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("Googlebot",           re.compile(r"Googlebot", re.IGNORECASE)),
    ("Google-Extended",     re.compile(r"Google-Extended", re.IGNORECASE)),
    ("Bingbot",             re.compile(r"bingbot", re.IGNORECASE)),
    ("Baiduspider",         re.compile(r"Baiduspider", re.IGNORECASE)),
    ("YandexBot",           re.compile(r"YandexBot", re.IGNORECASE)),
    ("DuckDuckBot",         re.compile(r"DuckDuckBot", re.IGNORECASE)),
    ("Applebot",            re.compile(r"Applebot", re.IGNORECASE)),
    ("Yahoo Slurp",         re.compile(r"Slurp", re.IGNORECASE)),
    ("FacebookBot",         re.compile(r"facebookexternalhit|FacebookBot", re.IGNORECASE)),
    ("Twitterbot",          re.compile(r"Twitterbot", re.IGNORECASE)),
    ("LinkedInBot",         re.compile(r"LinkedInBot", re.IGNORECASE)),
    ("GPTBot",              re.compile(r"GPTBot", re.IGNORECASE)),
    ("ChatGPT-User",        re.compile(r"ChatGPT-User", re.IGNORECASE)),
    ("ClaudeBot",           re.compile(r"ClaudeBot|anthropic-ai", re.IGNORECASE)),
    ("PerplexityBot",       re.compile(r"PerplexityBot", re.IGNORECASE)),
    ("Semrushbot",          re.compile(r"SemrushBot", re.IGNORECASE)),
    ("AhrefsBot",           re.compile(r"AhrefsBot", re.IGNORECASE)),
    ("MJ12bot",             re.compile(r"MJ12bot", re.IGNORECASE)),
    ("DotBot",              re.compile(r"DotBot", re.IGNORECASE)),
    ("Screaming Frog",      re.compile(r"Screaming Frog", re.IGNORECASE)),
    ("UptimeRobot",         re.compile(r"UptimeRobot", re.IGNORECASE)),
    ("Pingdom",             re.compile(r"pingdom", re.IGNORECASE)),
    ("StatusCake",          re.compile(r"statuscake", re.IGNORECASE)),
    ("Site24x7",            re.compile(r"site24x7", re.IGNORECASE)),
    ("Scrapy",              re.compile(r"Scrapy", re.IGNORECASE)),
    ("Python-requests",     re.compile(r"python-requests|python-urllib", re.IGNORECASE)),
    ("curl",                re.compile(r"\bcurl\b", re.IGNORECASE)),
    ("wget",                re.compile(r"\bwget\b", re.IGNORECASE)),
    ("Postman",             re.compile(r"PostmanRuntime|insomnia", re.IGNORECASE)),
    ("Generic crawler",     re.compile(r"crawl|spider|bot", re.IGNORECASE)),
    ("HTTP library",        re.compile(
        r"axios|go-http-client|java/|libwww|httpie|okhttp|"
        r"apache-httpclient|aiohttp|node-fetch|got/|undici|php|perl|ruby",
        re.IGNORECASE,
    )),
]

# How long a revisit from the same visitor counts as a duplicate (no re-log).
_DEDUP_WINDOW = timedelta(minutes=5)


def _get_bot_name(user_agent: str) -> str | None:
    """Return a human-readable bot name if the UA matches a known pattern, else None."""
    if not user_agent:
        return None
    for name, pattern in _BOT_PATTERNS:
        if pattern.search(user_agent):
            return name
    return None


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
    bot_name = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Human-readable bot/crawler name detected from User-Agent.",
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
        bot_name = _get_bot_name(ua)
        bot = bot_name is not None
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
            bot_name=bot_name,
        )


def _get_client_ip(request) -> str | None:
    """Return the real client IP, respecting X-Forwarded-For if present."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")
