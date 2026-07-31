from django.conf import settings
from django.db import models


class PressReviewSource(models.Model):
    """Admin-curated feed source for the press review harvester."""

    FEED_TYPE_RSS = "rss"
    FEED_TYPE_NEWS_SITEMAP = "news_sitemap"
    FEED_TYPE_CHOICES = (
        (FEED_TYPE_RSS, "RSS / Atom feed"),
        (FEED_TYPE_NEWS_SITEMAP, "Google News sitemap"),
    )

    name = models.CharField(max_length=255)
    url = models.URLField(blank=True, null=True, help_text="Homepage of the source.")
    rss_url = models.URLField(
        unique=True, help_text="Feed URL to harvest (RSS/Atom feed or news sitemap)."
    )
    feed_type = models.CharField(
        max_length=16,
        choices=FEED_TYPE_CHOICES,
        default=FEED_TYPE_RSS,
        help_text=(
            "How to parse this source. Use 'Google News sitemap' for publishers that "
            "no longer maintain RSS — sitemaps stay fresh because Google News depends "
            "on them, but carry no article summary."
        ),
    )
    active = models.BooleanField(
        default=True, help_text="Only active sources are harvested."
    )
    local = models.BooleanField(
        default=False,
        help_text=(
            "Local sources report exclusively on local topics and are exempt from "
            "the mandatory-keyword check during harvesting."
        ),
    )
    last_fetched_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        verbose_name = "Press Review Source"
        verbose_name_plural = "Press Review Sources"
        ordering = ["name"]

    def __str__(self):
        return self.name


class PressReviewKeyword(models.Model):
    """Global, admin-curated keyword used to filter articles during harvesting."""

    keyword = models.CharField(max_length=255, unique=True)
    active = models.BooleanField(default=True)
    required = models.BooleanField(
        default=False,
        help_text=(
            "Mandatory keywords: at least one must appear in every article (OR logic "
            "between them), together with at least one topic keyword. Local sources "
            "are exempt from this check."
        ),
    )
    created_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Press Review Keyword"
        verbose_name_plural = "Press Review Keywords"
        ordering = ["-required", "keyword"]

    def __str__(self):
        return f"🔒 {self.keyword}" if self.required else self.keyword


class PressReviewArticle(models.Model):
    """A harvested RSS article that matched the global keyword filter."""

    source = models.ForeignKey(
        PressReviewSource, on_delete=models.CASCADE, related_name="articles"
    )
    title = models.TextField()
    summary = models.TextField(blank=True, null=True)
    link = models.URLField(unique=True, max_length=1024)
    published_date = models.DateTimeField(blank=True, null=True)
    harvested_date = models.DateTimeField(auto_now_add=True)
    matched_keywords = models.TextField(
        blank=True, null=True, help_text="Comma-separated keywords that matched."
    )

    class Meta:
        verbose_name = "Press Review Article"
        verbose_name_plural = "Press Review Articles"
        ordering = ["-published_date"]

    def __str__(self):
        return self.title or self.link


class UserPressReviewKeyword(models.Model):
    """A personal topic of interest a user wants matched against harvested articles."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="press_review_keywords",
    )
    keyword = models.CharField(max_length=255)

    class Meta:
        verbose_name = "User Press Review Keyword"
        verbose_name_plural = "User Press Review Keywords"
        unique_together = [("user", "keyword")]
        ordering = ["keyword"]

    def __str__(self):
        return self.keyword


class UserPressReviewArticleScore(models.Model):
    """LLM-scored relevance of a harvested article for a specific user."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="press_review_article_scores",
    )
    article = models.ForeignKey(
        PressReviewArticle, on_delete=models.CASCADE, related_name="user_scores"
    )
    score = models.SmallIntegerField(blank=True, null=True)
    reason = models.TextField(blank=True, null=True)
    digest_sent = models.BooleanField(default=False)

    class Meta:
        verbose_name = "User Press Review Article Score"
        verbose_name_plural = "User Press Review Article Scores"
        unique_together = [("user", "article")]

    def __str__(self):
        return f"{self.user} / {self.article_id} = {self.score}"


class PressReviewHarvestLog(models.Model):
    """Audit trail of a single harvest run."""

    run_date = models.DateTimeField()
    sources_checked = models.IntegerField()
    articles_new = models.IntegerField()
    articles_skipped = models.IntegerField()
    errors = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = "Press Review Harvest Log"
        verbose_name_plural = "Press Review Harvest Logs"
        ordering = ["-run_date"]

    def __str__(self):
        return f"{self.run_date} (+{self.articles_new})"
