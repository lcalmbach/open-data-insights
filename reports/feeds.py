from datetime import date, timedelta

from django.contrib.syndication.views import Feed
from django.urls import reverse
from django.utils.feedgenerator import Rss201rev2Feed

from reports.models.lookups import LanguageEnum
from reports.models.story import Story

MAX_ITEMS = 20
MAX_AGE_DAYS = 90

LANGUAGE_CONFIG = {
    "en": {
        "id": LanguageEnum.ENGLISH.value,
        "title": "Open Data Insights – English",
        "description": "Latest data stories published on Open Data Insights.",
        "rss_lang": "en",
    },
    "de": {
        "id": LanguageEnum.GERMAN.value,
        "title": "Open Data Insights – Deutsch",
        "description": "Neueste Datengeschichten auf Open Data Insights.",
        "rss_lang": "de",
    },
    "fr": {
        "id": LanguageEnum.FRENCH.value,
        "title": "Open Data Insights – Français",
        "description": "Dernières histoires de données publiées sur Open Data Insights.",
        "rss_lang": "fr",
    },
}


class LanguageAwareRssFeed(Rss201rev2Feed):
    """RSS 2.0 feed with a <language> element."""

    def __init__(self, *args, **kwargs):
        self.rss_language = kwargs.pop("rss_language", "en")
        super().__init__(*args, **kwargs)

    def add_root_elements(self, handler):
        super().add_root_elements(handler)
        handler.addQuickElement("language", self.rss_language)


class StoryFeed(Feed):
    feed_type = LanguageAwareRssFeed

    def get_object(self, request, lang_code):
        if lang_code not in LANGUAGE_CONFIG:
            from django.http import Http404
            raise Http404("Unknown language code")
        return LANGUAGE_CONFIG[lang_code]

    def feed_extra_kwargs(self, obj):
        return {"rss_language": obj["rss_lang"]}

    def title(self, obj):
        return obj["title"]

    def description(self, obj):
        return obj["description"]

    def link(self, obj):
        return reverse("stories")

    def items(self, obj):
        cutoff = date.today() - timedelta(days=MAX_AGE_DAYS)
        return (
            Story.objects.filter(
                language_id=obj["id"],
                published_date__gte=cutoff,
                templatefocus__story_template__is_published=True,
                templatefocus__story_template__active=True,
            )
            .select_related("templatefocus__story_template")
            .order_by("-published_date")[:MAX_ITEMS]
        )

    def item_title(self, item):
        return item.title or ""

    def item_description(self, item):
        return item.summary or ""

    def item_pubdate(self, item):
        from datetime import datetime
        if item.published_date:
            return datetime(
                item.published_date.year,
                item.published_date.month,
                item.published_date.day,
            )
        return None

    def item_link(self, item):
        return item.get_absolute_url()
