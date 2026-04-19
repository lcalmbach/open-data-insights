from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from django.conf import settings

from .models.story import Story


class StaticViewSitemap(Sitemap):
    priority = 0.8
    changefreq = "weekly"
    protocol = "https"

    def get_domain(self, site=None):
        return settings.APP_ROOT.rstrip("/").removeprefix("https://").removeprefix("http://")

    def items(self):
        return ["home", "about", "stories"]

    def location(self, item):
        return reverse(item)


class StorySitemap(Sitemap):
    priority = 0.6
    changefreq = "monthly"
    protocol = "https"

    def get_domain(self, site=None):
        return settings.APP_ROOT.rstrip("/").removeprefix("https://").removeprefix("http://")

    def items(self):
        return (
            Story.objects.filter(
                templatefocus__story_template__is_published=True,
                templatefocus__story_template__active=True,
            )
            .select_related("templatefocus__story_template")
            .order_by("-published_date")
        )

    def lastmod(self, obj):
        return obj.published_date

    def location(self, obj):
        return reverse("view_story", args=[obj.pk])
