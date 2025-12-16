from django.db import models


class Quote(models.Model):
    quote = models.TextField(max_length=1000, help_text="Quote text.")
    author = models.CharField(max_length=255, help_text="Author of the quote.")
    author_wiki_url = models.URLField(
        max_length=500,
        blank=True,
        null=True,
        help_text="URL to the author's Wikipedia page.",
    )
    lifespan = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Lifespan of the author, e.g., '1900-1988'.",
    )

    class Meta:
        verbose_name = "Quote"
        verbose_name_plural = "Quotes"

    def __str__(self):
        return self.quote
