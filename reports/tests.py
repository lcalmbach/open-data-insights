import json
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from django.urls import reverse

from account.models import CustomUser
from reports.models.dataset import ImportTypeEnum, PeriodEnum
from reports.models.lookups import (
    LanguageEnum,
    PERIOD_CATEGORY_ID,
    PERIOD_DIRECTION_CATEGORY_ID,
    REGION_CATEGORY_ID,
    TOPIC_CATEGORY_ID,
    LookupCategory,
    Period,
    PeriodDirection,
    Region,
    Topic,
)
from reports.models.press_review import (
    PressReviewArticle,
    PressReviewHarvestLog,
    PressReviewKeyword,
    PressReviewSource,
    UserPressReviewArticleScore,
    UserPressReviewKeyword,
)
from reports.models.story import Story
from reports.models.story_rating import StoryRating
from reports.models.story_table import StoryTable
from reports.models.story_table_template import StoryTemplateTable
from reports.models.story_template import (
    StoryImage,
    StoryTemplate,
    StoryTemplateFocus,
    StoryTemplateFocusImage,
)
from reports.language import with_language_prefix
from reports.models.subscription import StoryTemplateSubscription
from reports.visualizations.plotting import (
    _color_for_value,
    _parse_color_bins,
    create_map_markers,
)
from reports.services.press_review_service import (
    PressReviewHarvestService,
    PressReviewMailer,
    parse_news_sitemap,
    PressReviewRelevanceService,
    _parse_response,
    keyword_matches,
)
from reports.management.commands.import_market_events import (
    _parse_bool,
    _parse_int,
    _split_list,
)
from reports.services.story_generation import StoryGenerationService
from reports.services.story_processor import StoryProcessor
from reports.views import _attach_graphic_chart_ids, _get_story_graphics
from reports.visualizations.plotting import create_line_chart, generate_chart
from reports.services.dataset_sync import (
    DatasetSyncService,
    EiaDatasetConnector,
    OdsDatasetConnector,
    UrlDatasetConnector,
    create_dataset_processor,
)
from reports.services.eia_api import (
    AVAILABLE_SERIES,
    fetch_eia_prices_df,
    list_available_series,
    resolve_series_configs,
    _fetch_eia_daily_rows,
    _build_daily_rows,
    _filter_recent_daily_rows,
    SERIES,
)


class StoryRatingsContextTests(TestCase):
    def setUp(self):
        period_category = LookupCategory.objects.create(
            id=PERIOD_CATEGORY_ID, name="Period", description=""
        )
        direction_category = LookupCategory.objects.create(
            id=PERIOD_DIRECTION_CATEGORY_ID, name="PeriodDirection", description=""
        )
        period = Period.objects.create(
            category=period_category, value="Daily", description="", sort_order=0
        )
        direction = PeriodDirection.objects.create(
            category=direction_category, value="Backward", description="", sort_order=0
        )
        self.template = StoryTemplate.objects.create(
            title="Template",
            description="",
            reference_period=period,
            period_direction=direction,
            prompt_text="prompt",
            active=True,
        )
        self.focus = StoryTemplateFocus.objects.create(
            story_template=self.template,
            filter_value=None,
        )
        self.story = Story.objects.create(
            templatefocus=self.focus,
            title="Story",
            summary="Summary",
            content="Content",
            published_date=date(2026, 2, 8),
            reference_period_start=date(2026, 2, 7),
            reference_period_end=date(2026, 2, 7),
        )
        self.user = CustomUser.objects.create_user(
            email="user@example.com",
            password="password",
            first_name="Test",
            last_name="User",
            country="US",
        )

    def test_stories_view_includes_rating_context(self):
        self.client.force_login(self.user)
        StoryRating.objects.create(story=self.story, user=self.user, rating=4)

        response = self.client.get(reverse("stories"), {"story": self.story.id}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["rating_count"], 1)
        self.assertAlmostEqual(float(response.context["rating_avg"]), 4.0)
        self.assertEqual(response.context["rating_stars_full"], 4)
        self.assertEqual(response.context["rating_stars_half"], 0)

    def test_half_star_rounding_in_context(self):
        self.client.force_login(self.user)
        StoryRating.objects.create(story=self.story, user=self.user, rating=4)
        other_user = CustomUser.objects.create_user(
            email="user2@example.com",
            password="password",
            first_name="Other",
            last_name="User",
            country="US",
        )
        StoryRating.objects.create(story=self.story, user=other_user, rating=5)

        response = self.client.get(reverse("stories"), {"story": self.story.id}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["rating_count"], 2)
        self.assertAlmostEqual(float(response.context["rating_avg"]), 4.5)
        self.assertEqual(response.context["rating_stars_full"], 4)
        self.assertEqual(response.context["rating_stars_half"], 1)

    def test_rate_story_creates_new_record_each_time(self):
        self.client.force_login(self.user)

        url = with_language_prefix(reverse("rate_story", args=(self.story.id,)), "en")
        self.client.post(url, {"rating": 3, "rating_text": "ok"}, follow=True)
        self.assertEqual(
            StoryRating.objects.filter(story=self.story, user=self.user).count(), 1
        )

        response = self.client.post(
            url, {"rating": 5, "rating_text": "great"}, follow=True
        )
        self.assertEqual(
            StoryRating.objects.filter(story=self.story, user=self.user).count(), 2
        )
        self.assertEqual(response.context["user_rating"], 5)

    def test_home_view_includes_rating_context(self):
        self.client.force_login(self.user)
        StoryRating.objects.create(story=self.story, user=self.user, rating=4)

        response = self.client.get(reverse("home"), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_story"].id, self.story.id)
        self.assertEqual(response.context["rating_count"], 1)
        self.assertAlmostEqual(float(response.context["rating_avg"]), 4.0)


    def test_home_view_exposes_recent_stories_grid(self):
        self.client.force_login(self.user)

        for offset in range(1, 10):
            story_date = date(2026, 2, 8) - timedelta(days=offset)
            Story.objects.create(
                templatefocus=self.focus,
                title=f"Story {offset}",
                summary=f"Summary {offset}",
                content=f"Content {offset}",
                published_date=story_date,
                reference_period_start=story_date,
                reference_period_end=story_date,
            )

        response = self.client.get(reverse("home"), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["featured_story"].id, self.story.id)
        self.assertEqual(len(response.context["recent_stories"]), 8)
        self.assertContains(response, "Recent insights")
        self.assertContains(response, "?page=2")

    def test_home_view_paginates_recent_stories(self):
        self.client.force_login(self.user)

        for offset in range(1, 19):
            story_date = date(2026, 2, 8) - timedelta(days=offset)
            Story.objects.create(
                templatefocus=self.focus,
                title=f"Story {offset}",
                summary=f"Summary {offset}",
                content=f"Content {offset}",
                published_date=story_date,
                reference_period_start=story_date,
                reference_period_end=story_date,
            )

        response = self.client.get(reverse("home"), {"page": 2}, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["recent_page_obj"].number, 2)
        self.assertEqual(len(response.context["recent_stories"]), 8)
        self.assertEqual(response.context["recent_stories"][0].title, "Story 9")
        self.assertEqual(response.context["recent_stories"][-1].title, "Story 16")
        self.assertContains(response, "?page=3")

    def test_home_view_limits_pager_to_four_pages_with_arrows(self):
        self.client.force_login(self.user)

        for offset in range(1, 35):
            story_date = date(2026, 2, 8) - timedelta(days=offset)
            Story.objects.create(
                templatefocus=self.focus,
                title=f"Story {offset}",
                summary=f"Summary {offset}",
                content=f"Content {offset}",
                published_date=story_date,
                reference_period_start=story_date,
                reference_period_end=story_date,
            )

        response = self.client.get(reverse("home"), {"page": 3}, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["recent_page_obj"].number, 3)
        self.assertEqual(response.context["recent_page_numbers"], [1, 2, 3, 4])
        self.assertContains(response, 'aria-label="First page"')
        self.assertContains(response, 'aria-label="Previous page"')
        self.assertContains(response, 'aria-label="Next page"')
        self.assertContains(response, 'aria-label="Last page"')

    def test_home_view_shows_image_in_recent_card_and_hides_its_lead(self):
        self.client.force_login(self.user)

        image_focus = StoryTemplateFocus.objects.create(
            story_template=self.template,
            filter_value="A",
        )
        image_story = Story.objects.create(
            templatefocus=image_focus,
            title="Story With Image",
            summary="Lead that should not appear in the card",
            content="Content",
            published_date=date(2026, 2, 7),
            reference_period_start=date(2026, 2, 7),
            reference_period_end=date(2026, 2, 7),
        )
        image = StoryImage.objects.create(
            title="Card image",
            remote_url="https://example.com/card-image.jpg",
        )
        StoryTemplateFocusImage.objects.create(
            focus=image_focus,
            image=image,
            sort_order=0,
        )

        Story.objects.create(
            templatefocus=self.focus,
            title="Story Without Image",
            summary="Lead that should remain visible in the card",
            content="Content",
            published_date=date(2026, 2, 6),
            reference_period_start=date(2026, 2, 6),
            reference_period_end=date(2026, 2, 6),
        )

        response = self.client.get(reverse("home"), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(image_story, response.context["recent_stories"])
        self.assertContains(response, "https://example.com/card-image.jpg")
        self.assertNotContains(response, "Lead that should not appear in the card")
        self.assertContains(response, "Lead that should remain visible in the card")

    def test_home_view_counts_only_active_accessible_subscriptions(self):
        self.client.force_login(self.user)
        # reports.signals.subscribe_new_user_to_templates already subscribed the user
        # to self.template when they were created; adding another row here would be a
        # duplicate, which the count would (correctly) report as 2.

        inactive_template = StoryTemplate.objects.create(
            title="Inactive template",
            description="",
            reference_period=self.template.reference_period,
            period_direction=self.template.period_direction,
            prompt_text="prompt",
            active=False,
        )
        StoryTemplateSubscription.objects.create(
            user=self.user,
            story_template=inactive_template,
        )

        response = self.client.get(reverse("home"), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_subscription_count"], 1)
        self.assertEqual(response.context["available_subscriptions"], 1)
        # The "1/1" badge this used to assert on is no longer rendered by any
        # template; the context assertions above cover the counting behaviour.

    def test_view_story_uses_story_detail_template(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("view_story", args=(self.story.id,)), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "reports/story_detail.html")
        self.assertContains(response, "All insights")


class StoryExplorerFilteringTests(TestCase):
    def setUp(self):
        period_category = LookupCategory.objects.create(
            id=PERIOD_CATEGORY_ID, name="Period", description=""
        )
        direction_category = LookupCategory.objects.create(
            id=PERIOD_DIRECTION_CATEGORY_ID, name="PeriodDirection", description=""
        )
        self.daily_period = Period.objects.create(
            category=period_category, value="Daily", description="", sort_order=0
        )
        self.monthly_period = Period.objects.create(
            category=period_category, value="Monthly", description="", sort_order=1
        )
        direction = PeriodDirection.objects.create(
            category=direction_category, value="Backward", description="", sort_order=0
        )
        region_category, _ = LookupCategory.objects.get_or_create(
            id=REGION_CATEGORY_ID, defaults={"name": "Region", "description": ""}
        )
        topic_category, _ = LookupCategory.objects.get_or_create(
            id=TOPIC_CATEGORY_ID, defaults={"name": "Topic", "description": ""}
        )

        self.switzerland = Region.objects.create(value="Switzerland", key="CH", sort_order=1)
        self.baselland = Region.objects.create(
            value="Baselland",
            key="BL",
            predecessor=self.switzerland,
            level=1,
            sort_order=1,
        )
        self.europe = Region.objects.create(
            value="Europe",
            key="EU",
            sort_order=2,
        )

        self.energy = Topic.objects.create(value="Energy", key="ENERGY", sort_order=1)
        self.electricity = Topic.objects.create(
            value="Electricity",
            key="ELECTRICITY",
            predecessor=self.energy,
            level=1,
            sort_order=1,
        )
        self.population = Topic.objects.create(
            value="Population",
            key="POPULATION",
            sort_order=2,
        )

        self.template_energy = StoryTemplate.objects.create(
            title="Municipality energy profile",
            description="Energy indicators for municipalities",
            reference_period=self.daily_period,
            period_direction=direction,
            prompt_text="prompt",
            active=True,
            region=self.baselland,
        )
        self.template_energy.topics.add(self.electricity)
        self.focus_energy = StoryTemplateFocus.objects.create(
            story_template=self.template_energy,
            filter_value="Liestal",
        )
        self.story_energy = Story.objects.create(
            templatefocus=self.focus_energy,
            title="Electricity use in Liestal",
            summary="Energy summary",
            content="Electricity consumption rose in the municipality.",
            published_date=date(2026, 2, 8),
            reference_period_start=date(2026, 2, 7),
            reference_period_end=date(2026, 2, 7),
        )

        self.template_population = StoryTemplate.objects.create(
            title="European population profile",
            description="Population indicators across Europe",
            reference_period=self.monthly_period,
            period_direction=direction,
            prompt_text="prompt",
            active=True,
            region=self.europe,
        )
        self.template_population.topics.add(self.population)
        self.focus_population = StoryTemplateFocus.objects.create(
            story_template=self.template_population,
            filter_value="Europe",
        )
        self.story_population = Story.objects.create(
            templatefocus=self.focus_population,
            title="Population change in Europe",
            summary="Population summary",
            content="Population growth remained stable across Europe.",
            published_date=date(2026, 2, 9),
            reference_period_start=date(2026, 2, 8),
            reference_period_end=date(2026, 2, 8),
        )

        self.user = CustomUser.objects.create_user(
            email="filter@example.com",
            password="password",
            first_name="Filter",
            last_name="User",
            country="US",
        )
        self.client.force_login(self.user)

    def test_region_filter_includes_descendant_regions(self):
        response = self.client.get(reverse("stories"), {"region": self.switzerland.id}, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [story.id for story in response.context["stories"]],
            [self.story_energy.id],
        )

    def test_topic_filter_includes_descendant_topics(self):
        response = self.client.get(reverse("stories"), {"topic": self.energy.id}, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [story.id for story in response.context["stories"]],
            [self.story_energy.id],
        )

    def test_search_matches_story_content(self):
        response = self.client.get(reverse("stories"), {"search": "consumption rose"}, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [story.id for story in response.context["stories"]],
            [self.story_energy.id],
        )

    def test_home_view_filters_by_region(self):
        response = self.client.get(reverse("home"), {"region": self.switzerland.id}, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["featured_story"].id, self.story_energy.id)
        self.assertEqual(response.context["recent_stories"], [])

    def test_home_view_filters_by_time_frequency(self):
        response = self.client.get(reverse("home"), {"reference_period": "day"}, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["featured_story"].id, self.story_energy.id)
        self.assertEqual(response.context["recent_stories"], [])
        self.assertEqual(response.context["filter_summary"]["reference_period"], "Day")

    def test_home_view_filters_by_template(self):
        response = self.client.get(
            reverse("home"),
            {"template": self.template_population.id},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["featured_story"].id, self.story_population.id)
        self.assertEqual(response.context["recent_stories"], [])
        self.assertEqual(
            response.context["filter_summary"]["template"].id,
            self.template_population.id,
        )

    def test_stories_view_filters_by_time_frequency(self):
        response = self.client.get(reverse("stories"), {"reference_period": "month"}, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [story.id for story in response.context["stories"]],
            [self.story_population.id],
        )


class StoryTemplateFocusSqlReplacementTests(TestCase):
    def setUp(self):
        period_category = LookupCategory.objects.create(
            id=PERIOD_CATEGORY_ID, name="Period", description=""
        )
        direction_category = LookupCategory.objects.create(
            id=PERIOD_DIRECTION_CATEGORY_ID, name="PeriodDirection", description=""
        )
        period = Period.objects.create(
            category=period_category, value="Daily", description="", sort_order=0
        )
        direction = PeriodDirection.objects.create(
            category=direction_category, value="Backward", description="", sort_order=0
        )
        self.template = StoryTemplate.objects.create(
            title="Template",
            description="",
            reference_period=period,
            period_direction=direction,
            prompt_text="prompt",
            active=True,
        )

    def test_focus_conditions_use_filter_value_not_focus_filter(self):
        """`:focus_filter` no longer exists; templates use `:filter_value`.

        It used to expand to a condition built from StoryTemplate.focus_filter_fields,
        removed in migration 0164, after which it could only produce 1=1 — silently
        generating stories over unfiltered data. It is now left untouched, so a
        template still using it fails loudly instead.
        """
        from datetime import date

        from reports.services.story_processor import StoryProcessor

        focus = StoryTemplateFocus.objects.create(
            story_template=self.template,
            filter_value="Zurich",
        )
        processor = StoryProcessor(
            published_date=date(2026, 2, 7), template=self.template, focus=focus
        )

        replaced = processor._replace_sql_expressions(
            "SELECT 1 WHERE district = ':filter_value'"
        )
        self.assertIn("Zurich", replaced)
        self.assertNotIn(":filter_value", replaced)

        # Not substituted any more, so it cannot silently become a no-op.
        untouched = processor._replace_sql_expressions("SELECT 1 WHERE :focus_filter")
        self.assertIn(":focus_filter", untouched)
        self.assertNotIn("1=1", untouched)

class LineChartReferenceLineTests(TestCase):
    def test_line_chart_supports_configured_reference_lines(self):
        data = pd.DataFrame(
            {
                "year": [2022, 2023, 2024],
                "value": [10, 15, 12],
            }
        )
        chart = create_line_chart(
            data,
            {
                "x": "year",
                "y": "value",
                "x_type": "Q",
                "y_type": "Q",
                "reference_lines": [
                    {"type": "V", "x": 2023, "color": "red", "width": 2, "stroke": "solid", "label": "average"},
                    {"type": "H", "y": 13, "color": "blue", "width": 1, "stroke": "dashed"},
                ],
            },
        )

        # ECharts returns an option dict; reference lines become a markLine on the
        # series rather than extra Altair layers.
        mark_line = chart["series"][0]["markLine"]
        vertical, horizontal = mark_line["data"]

        self.assertEqual(vertical["xAxis"], 2023)
        self.assertEqual(vertical["name"], "average")
        self.assertEqual(vertical["lineStyle"]["color"], "red")
        self.assertEqual(vertical["lineStyle"]["width"], 2)

        self.assertEqual(horizontal["yAxis"], 13)
        self.assertEqual(horizontal["lineStyle"]["color"], "blue")
        self.assertEqual(horizontal["lineStyle"]["width"], 1)

class DynamicReferenceLineSettingsTests(SimpleTestCase):
    def test_value_sql_is_resolved_into_vertical_line_x_value(self):
        class StubDbClient:
            def run_query(self, sql, params):
                self.sql = sql
                self.params = params
                return pd.DataFrame([[73]], columns=["value"])

        processor = StoryProcessor.__new__(StoryProcessor)
        processor.dbclient = StubDbClient()
        processor.logger = None
        processor.focus = None
        processor.template = SimpleNamespace(focus_filter_fields="")
        processor.story = SimpleNamespace(
            reference_period_start=date(2026, 3, 13),
            reference_period_end=date(2026, 3, 13),
            reference_period_expression="13 March 2026",
            published_date=date(2026, 3, 13),
        )
        processor.reference_period_start = date(2026, 3, 13)
        processor.reference_period_end = date(2026, 3, 13)
        processor.published_date = date(2026, 3, 13)
        processor.month = 3
        processor.year = 2026
        # __init__ is bypassed above, so set what _replace_reference_period_expression
        # reads; both branches of the real __init__ assign these.
        processor.season = 1
        processor.season_year = 2026

        settings = {
            "reference_lines": [
                {
                    "type": "V",
                    "value_sql": "select extract(doy from %(published_date)s::date)::int",
                    "label": "Today",
                }
            ]
        }

        resolved = processor._resolve_reference_line_settings(settings)

        self.assertEqual(resolved["reference_lines"][0]["x"], 73)


class FocusSubjectPromptTests(SimpleTestCase):
    def test_generate_insight_text_includes_focus_subject_when_present(self):
        captured = {}

        class StubCompletions:
            def create(self, **kwargs):
                captured["messages"] = kwargs["messages"]
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content="Generated insight")
                        )
                    ]
                )

        processor = StoryProcessor.__new__(StoryProcessor)
        processor.logger = SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None)
        processor.ai_client = SimpleNamespace(
            chat=SimpleNamespace(completions=StubCompletions())
        )
        processor.is_data_based = True
        processor.focus = SimpleNamespace(focus_subject="Focus on the WTI/Brent spread")
        processor.story = SimpleNamespace(
            ai_model="test-model",
            context_values='{"context_data": {}}',
            content="",
            prompt_text=None,
            template=SimpleNamespace(
                prompt_text="Write an oil market insight.",
                temperature=0.2,
            ),
        )
        processor._replace_reference_period_expression = lambda value: value

        ok = StoryProcessor._generate_insight_text(processor)

        self.assertTrue(ok)
        self.assertIn(
            "Focus subject: Focus on the WTI/Brent spread",
            captured["messages"][0]["content"],
        )


class DirectContextStoryTests(SimpleTestCase):
    def _build_processor(self, context_values):
        processor = StoryProcessor.__new__(StoryProcessor)
        processor.logger = SimpleNamespace(
            info=lambda *a, **k: None,
            warning=lambda *a, **k: None,
            error=lambda *a, **k: None,
        )
        processor.story = SimpleNamespace(
            context_values=context_values,
            content="stale content",
            summary="stale summary",
            title="stale title",
            prompt_text="stale prompt",
            template=SimpleNamespace(
                id=11,
                story_source=StoryTemplate.STORY_SOURCE_CONTEXT,
                prompt_text=None,
                default_title=None,
                default_lead=None,
                summary=None,
                create_title=True,
                create_lead=True,
            ),
        )
        processor.template = processor.story.template
        processor._replace_reference_period_expression = lambda value: value
        processor._fit_story_title = lambda value: value
        return processor

    def test_promptless_story_reads_full_article_from_context_json(self):
        processor = self._build_processor(
            {
                "context_data": {
                    "article": {
                        "data": {
                            "title": "Interactive oil outlook",
                            "lead": "Lead written during the interactive session.",
                            "text": "The complete article is already available in the context payload.",
                        }
                    }
                }
            }
        )

        ok = StoryProcessor._populate_story_from_context(processor)

        self.assertTrue(ok)
        self.assertEqual(processor.story.title, "Interactive oil outlook")
        self.assertEqual(
            processor.story.summary,
            "Lead written during the interactive session.",
        )
        self.assertEqual(
            processor.story.content,
            "The complete article is already available in the context payload.",
        )
        self.assertIsNone(processor.story.prompt_text)

    def test_promptless_story_keeps_context_title_and_lead_without_llm(self):
        """A list payload selects the record matching the story's language, and the
        title and lead survive without any model call."""
        processor = self._build_processor(
            {
                "context_data": {
                    "article": {
                        "data": [
                            {
                                "language": "en",
                                "title": "AI co-written market recap",
                                "lead": "Short lead stored directly in JSON.",
                                "text": "Body text stored directly in the story payload.",
                            }
                        ]
                    }
                }
            }
        )

        self.assertTrue(StoryProcessor._populate_story_from_context(processor))

        self.assertEqual(processor.story.title, "AI co-written market recap")
        self.assertEqual(processor.story.summary, "Short lead stored directly in JSON.")
        self.assertEqual(
            processor.story.content, "Body text stored directly in the story payload."
        )
        self.assertIsNone(processor.story.prompt_text)


class StoryTemplateValidationTests(SimpleTestCase):
    def test_llm_story_source_requires_prompt_text(self):
        template = StoryTemplate(
            story_source=StoryTemplate.STORY_SOURCE_LLM,
            prompt_text="",
        )

        with self.assertRaises(ValidationError) as exc_info:
            template.clean()

        self.assertEqual(
            exc_info.exception.message_dict,
            {"prompt_text": ["Prompt text is required when story source is set to LLM."]},
        )

    def test_context_story_source_allows_blank_prompt_text(self):
        template = StoryTemplate(
            story_source=StoryTemplate.STORY_SOURCE_CONTEXT,
            prompt_text="",
        )

        template.clean()


class FocusTitleFallbackTests(SimpleTestCase):
    def test_generate_title_uses_focus_title_when_create_title_is_false(self):
        processor = StoryProcessor.__new__(StoryProcessor)
        processor.logger = SimpleNamespace(info=lambda *a, **k: None)
        processor.focus = SimpleNamespace(
            default_title="Focus-specific fallback title",
            default_lead="Focus-specific fallback lead",
        )
        processor.story = SimpleNamespace(
            title=None,
            template=SimpleNamespace(
                create_title=False,
                default_title="Template default title",
                title="Template label",
            ),
        )
        processor._replace_reference_period_expression = lambda value: value
        processor._fit_story_title = lambda value: value

        ok = StoryProcessor.generate_title(processor)

        self.assertTrue(ok)
        self.assertEqual(processor.story.title, "Focus-specific fallback title")

    def test_context_mode_title_fallback_uses_focus_title(self):
        processor = StoryProcessor.__new__(StoryProcessor)
        processor.logger = SimpleNamespace(info=lambda *a, **k: None)
        processor.focus = SimpleNamespace(
            default_title="Context fallback focus title",
            default_lead="Context fallback focus lead",
        )
        processor.story = SimpleNamespace(
            title=None,
            context_values={"context_data": {}},
            template=SimpleNamespace(
                story_source=StoryTemplate.STORY_SOURCE_CONTEXT,
                default_title="Template default title",
                title="Template label",
            ),
        )
        processor._replace_reference_period_expression = lambda value: value
        processor._fit_story_title = lambda value: value

        ok = StoryProcessor.generate_title(processor)

        self.assertTrue(ok)
        self.assertEqual(processor.story.title, "Context fallback focus title")

    def test_generate_lead_uses_focus_default_lead(self):
        processor = StoryProcessor.__new__(StoryProcessor)
        processor.logger = SimpleNamespace(info=lambda *a, **k: None)
        processor.focus = SimpleNamespace(default_lead="Focus lead fallback")
        processor.template = SimpleNamespace(create_lead=False, default_lead="Template lead")
        processor.story = SimpleNamespace(
            summary=None,
            template=SimpleNamespace(
                story_source=StoryTemplate.STORY_SOURCE_CONTEXT,
                default_lead="Template lead",
                summary="Template summary",
            ),
            context_values={"context_data": {}},
        )
        processor._replace_reference_period_expression = lambda value: value

        ok = StoryProcessor.generate_lead(processor)

        self.assertTrue(ok)
        self.assertEqual(processor.story.summary, "Focus lead fallback")


class EiaOilImportTests(SimpleTestCase):

    def test_daily_rows_can_use_custom_dataset_label(self):
        rows = _build_daily_rows(
            next(series for series in SERIES if series.series == "RWTC"),
            [(date(2026, 1, 1), Decimal("70.0"))],
            source_label="dataset_82_eia",
        )

        self.assertEqual(rows[0]["source"], "dataset_82_eia")

    @patch("reports.services.eia_api._fetch_eia_daily_rows")
    def test_fetch_prices_df_fetches_from_api(
        self,
        mock_fetch_eia_daily_rows,
    ):
        mock_fetch_eia_daily_rows.return_value = {
            "RWTC": [(date(2026, 1, 1), Decimal("70.0"))],
            "RBRTE": [(date(2026, 1, 1), Decimal("80.0"))],
        }

        df = fetch_eia_prices_df(
            source_label="dataset_82_eia",
            series_selection=["RWTC", "RBRTE"],
        )

        self.assertEqual(len(df), 2)
        self.assertEqual(set(df["quote_type"]), {"daily_close"})
        mock_fetch_eia_daily_rows.assert_called_once()

    def test_recent_filter_keeps_only_last_week_dates(self):
        filtered = _filter_recent_daily_rows(
            {
                "RWTC": [
                    (date(2026, 3, 10), Decimal("70.0")),
                    (date(2026, 3, 15), Decimal("72.0")),
                    (date(2026, 3, 21), Decimal("74.0")),
                ]
            },
            as_of=date(2026, 3, 21),
            days=7,
        )

        self.assertEqual(
            filtered["RWTC"],
            [
                (date(2026, 3, 15), Decimal("72.0")),
                (date(2026, 3, 21), Decimal("74.0")),
            ],
        )

    def test_daily_rows_are_built_with_daily_timestamps(self):
        rows = _build_daily_rows(
            next(series for series in SERIES if series.series == "RWTC"),
            [(date(2026, 3, 20), Decimal("71.25"))],
            source_label="dataset_82_eia",
        )

        self.assertEqual(rows[0]["quote_type"], "daily_close")
        self.assertEqual(rows[0]["price_timestamp"], datetime(2026, 3, 20, tzinfo=UTC))
        self.assertEqual(rows[0]["commodity_code"], "RWTC")

    def test_resolve_series_configs_accepts_registry_codes(self):
        series = resolve_series_configs(
            [
                "RWTC",
                "EER_EPMRU_PF4_Y35NY_DPG",
                "EER_EPLLPA_PF4_Y44MB_DPG",
            ]
        )

        self.assertEqual(
            [item.series for item in series],
            [
                "RWTC",
                "EER_EPMRU_PF4_Y35NY_DPG",
                "EER_EPLLPA_PF4_Y44MB_DPG",
            ],
        )
        self.assertEqual(series[1].unit, "gallon")
        self.assertEqual(series[2].commodity, "Propane")

    def test_resolve_series_configs_accepts_custom_metadata(self):
        series = resolve_series_configs(
            [
                {
                    "series": "RAC2D",
                    "commodity": "Regular Gasoline",
                    "market": "New York Harbor",
                    "unit": "gallon",
                }
            ]
        )

        self.assertEqual(series[0].series, "RAC2D")
        self.assertEqual(series[0].commodity, "Regular Gasoline")
        self.assertEqual(series[0].unit, "gallon")

    def test_available_series_catalog_lists_all_builtin_eia_series(self):
        series = list_available_series()

        self.assertEqual(len(series), 11)
        self.assertEqual(series[0]["series"], "RWTC")
        self.assertEqual(series[-1]["series"], "EER_EPLLPA_PF4_Y44MB_DPG")

    def test_resolve_series_configs_defaults_to_all_available_series(self):
        series = resolve_series_configs(None)

        self.assertEqual(len(series), len(AVAILABLE_SERIES))
        self.assertEqual([item.series for item in series], [item.series for item in AVAILABLE_SERIES])

    @patch("reports.services.eia_api.requests.get")
    def test_fetch_daily_rows_raises_clear_error_for_non_json_response(self, mock_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.side_effect = ValueError("not json")
        response.headers = {"content-type": "text/html"}
        response.text = "<html><body>not json</body></html>"
        response.url = "https://www.eia.gov/dnav/pet/PET_PRI_SPT_S1_D.htm"
        mock_get.return_value = response

        with self.assertRaises(CommandError) as exc:
            _fetch_eia_daily_rows(
                api_url="https://www.eia.gov/dnav/pet/PET_PRI_SPT_S1_D.htm",
                api_key="test-key",
                series_configs=[next(series for series in SERIES if series.series == "RWTC")],
                start_date=date(2026, 3, 15),
                end_date=date(2026, 3, 21),
            )

        self.assertIn("did not return JSON", str(exc.exception))

class DatasetSourceConnectorTests(SimpleTestCase):
    @patch("reports.services.dataset_sync.OdsDatasetConnector")
    def test_factory_selects_ods_connector(self, mock_connector):
        dataset = SimpleNamespace(source="ods")

        create_dataset_processor(dataset)

        mock_connector.assert_called_once_with(dataset)

    @patch("reports.services.dataset_sync.EiaDatasetConnector")
    def test_factory_selects_eia_connector(self, mock_connector):
        dataset = SimpleNamespace(source="eia")

        create_dataset_processor(dataset)

        mock_connector.assert_called_once_with(dataset)

    @patch("reports.services.dataset_sync.UrlDatasetConnector")
    def test_factory_selects_url_connector(self, mock_connector):
        dataset = SimpleNamespace(source="url")

        create_dataset_processor(dataset)

        mock_connector.assert_called_once_with(dataset)

    def test_factory_rejects_unknown_connector(self):
        dataset = SimpleNamespace(source="worldbank")

        with self.assertRaises(ValueError):
            create_dataset_processor(dataset)

    @patch("reports.services.dataset_sync.fetch_eia_prices_df")
    def test_eia_connector_fetches_dataframe(self, mock_fetch_df):
        mock_fetch_df.return_value = pd.DataFrame([{"commodity_code": "RWTC"}])
        dataset = SimpleNamespace(
            id=82,
            name="Commodity Price EIA",
            source="eia",
            source_identifier="eia_pet_pri_spt_s1_d",
            source_url="https://api.eia.gov/v2/petroleum/pri/spt/data/",
            fields_selection=["RWTC", "RBRTE"],
            target_table_name="commodity_price",
        )

        connector = EiaDatasetConnector(dataset)
        df = connector.fetch_dataframe()

        self.assertEqual(len(df), 1)
        mock_fetch_df.assert_called_once_with(
            api_url="https://api.eia.gov/v2/petroleum/pri/spt/data/",
            source_label="eia_pet_pri_spt_s1_d",
            series_selection=["RWTC", "RBRTE"],
            recent_days=7,
            logger=connector.logger,
        )
        self.assertEqual(
            connector.get_unique_fields(),
            ["commodity_code", "price_timestamp", "quote_type"],
        )

    @patch("reports.services.dataset_sync.fetch_eia_prices_df")
    def test_eia_connector_normalizes_comma_separated_series_selection(self, mock_fetch_df):
        mock_fetch_df.return_value = pd.DataFrame([{"commodity_code": "RWTC"}])
        dataset = SimpleNamespace(
            id=83,
            name="Commodity Price EIA",
            source="eia",
            source_identifier="eia_pet_pri_spt_s1_d",
            source_url="https://api.eia.gov/v2/petroleum/pri/spt/data/",
            fields_selection="RWTC, RBRTE",
            target_table_name="commodity_price",
        )

        connector = EiaDatasetConnector(dataset)
        connector.fetch_dataframe()

        mock_fetch_df.assert_called_once_with(
            api_url="https://api.eia.gov/v2/petroleum/pri/spt/data/",
            source_label="eia_pet_pri_spt_s1_d",
            series_selection=["RWTC", "RBRTE"],
            recent_days=7,
            logger=connector.logger,
        )

    @patch("reports.services.dataset_sync.fetch_eia_prices_df")
    def test_eia_connector_normalizes_json_series_selection(self, mock_fetch_df):
        mock_fetch_df.return_value = pd.DataFrame([{"commodity_code": "RWTC"}])
        dataset = SimpleNamespace(
            id=84,
            name="Commodity Price EIA",
            source="eia",
            source_identifier="eia_pet_pri_spt_s1_d",
            source_url="https://api.eia.gov/v2/petroleum/pri/spt/data/",
            fields_selection='["RWTC", "RBRTE"]',
            target_table_name="commodity_price",
        )

        connector = EiaDatasetConnector(dataset)
        connector.fetch_dataframe()

        mock_fetch_df.assert_called_once_with(
            api_url="https://api.eia.gov/v2/petroleum/pri/spt/data/",
            source_label="eia_pet_pri_spt_s1_d",
            series_selection=["RWTC", "RBRTE"],
            recent_days=7,
            logger=connector.logger,
        )

    @patch("reports.services.dataset_sync.fetch_eia_prices_df")
    def test_eia_connector_accepts_series_selection_attribute(self, mock_fetch_df):
        mock_fetch_df.return_value = pd.DataFrame([{"commodity_code": "RWTC"}])
        dataset = SimpleNamespace(
            id=85,
            name="Commodity Price EIA",
            source="eia",
            source_identifier="eia_pet_pri_spt_s1_d",
            source_url="https://api.eia.gov/v2/petroleum/pri/spt/data/",
            series_selection=["RWTC", "RBRTE"],
            target_table_name="commodity_price",
        )

        connector = EiaDatasetConnector(dataset)
        connector.fetch_dataframe()

        mock_fetch_df.assert_called_once_with(
            api_url="https://api.eia.gov/v2/petroleum/pri/spt/data/",
            source_label="eia_pet_pri_spt_s1_d",
            series_selection=["RWTC", "RBRTE"],
            recent_days=7,
            logger=connector.logger,
        )

    @patch("reports.services.dataset_sync.fetch_eia_prices_df")
    def test_eia_connector_falls_back_from_empty_series_selection(self, mock_fetch_df):
        mock_fetch_df.return_value = pd.DataFrame([{"commodity_code": "RWTC"}])
        dataset = SimpleNamespace(
            id=86,
            name="Commodity Price EIA",
            source="eia",
            source_identifier="eia_pet_pri_spt_s1_d",
            source_url="https://api.eia.gov/v2/petroleum/pri/spt/data/",
            series_selection=[],
            fields_selection=["RWTC", "RBRTE"],
            target_table_name="commodity_price",
        )

        connector = EiaDatasetConnector(dataset)
        connector.fetch_dataframe()

        mock_fetch_df.assert_called_once_with(
            api_url="https://api.eia.gov/v2/petroleum/pri/spt/data/",
            source_label="eia_pet_pri_spt_s1_d",
            series_selection=["RWTC", "RBRTE"],
            recent_days=7,
            logger=connector.logger,
        )

    @patch("reports.services.dataset_sync.fetch_eia_prices_df")
    def test_eia_connector_defaults_to_all_registered_series(self, mock_fetch_df):
        mock_fetch_df.return_value = pd.DataFrame([{"commodity_code": "RWTC"}])
        dataset = SimpleNamespace(
            id=87,
            name="Commodity Price EIA",
            source="eia",
            source_identifier="eia_pet_pri_spt_s1_d",
            source_url="https://api.eia.gov/v2/petroleum/pri/spt/data/",
            series_selection=[],
            fields_selection=[],
            target_table_name="commodity_price",
        )

        connector = EiaDatasetConnector(dataset)
        connector.fetch_dataframe()

        mock_fetch_df.assert_called_once_with(
            api_url="https://api.eia.gov/v2/petroleum/pri/spt/data/",
            source_label="eia_pet_pri_spt_s1_d",
            series_selection=[item.series for item in AVAILABLE_SERIES],
            recent_days=7,
            logger=connector.logger,
        )

    @patch("reports.services.dataset_sync.requests.get")
    def test_url_connector_fetches_csv_dataframe(self, mock_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.iter_content.return_value = [
            "\ufeff ID , Observed_At , VALUE \n".encode("utf-8"),
            b"1,2026-03-19,11\n2,2026-03-20,12\n",
        ]
        mock_get.return_value = response
        dataset = SimpleNamespace(
            id=90,
            name="CSV URL",
            source="url",
            source_url="https://example.com/data.csv",
        )

        connector = UrlDatasetConnector(dataset)
        df = connector.fetch_dataframe()

        self.assertEqual(list(df.columns), ["id", "observed_at", "value"])
        self.assertEqual(len(df), 2)
        self.assertEqual(connector.get_write_mode(), "replace")
        mock_get.assert_called_once_with(
            "https://example.com/data.csv",
            stream=True,
            timeout=(10, 60),
        )

    @patch("reports.services.dataset_sync.requests.get")
    def test_url_connector_persists_csv_in_chunks(self, mock_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.iter_content.return_value = [
            b"id,observed_at,value\n",
            b"1,2026-03-19,11\n2,2026-03-20,12\n",
        ]
        mock_get.return_value = response
        dataset = SimpleNamespace(
            id=90,
            name="CSV URL",
            source="url",
            source_url="https://example.com/data.csv",
        )
        dbclient = Mock()
        dbclient.replace_table_from_csv.return_value = 2

        connector = UrlDatasetConnector(dataset)
        written = connector.persist_data(
            dbclient=dbclient,
            table_name="csv_url",
            schema="opendata",
        )

        self.assertEqual(written, 2)
        dbclient.replace_table_from_csv.assert_called_once()
        _, kwargs = dbclient.replace_table_from_csv.call_args
        self.assertEqual(kwargs["sep"], None)
        self.assertEqual(kwargs["engine"], "python")
        normalized = kwargs["chunk_transform"](
            pd.DataFrame([[1, 2]], columns=['\ufeff "ID" ', " Value "])
        )
        self.assertEqual(list(normalized.columns), ["id", "value"])

    def test_url_connector_normalizes_wrapped_quotes_in_column_names(self):
        normalized = UrlDatasetConnector._normalize_dataframe_columns(
            pd.DataFrame([[1]], columns=['\ufeff "Jahr" '])
        )

        self.assertEqual(list(normalized.columns), ["jahr"])


class OdsConnectorTimestampNormalizationTests(SimpleTestCase):
    def test_download_ods_data_handles_mixed_dst_offsets(self):
        connector = OdsDatasetConnector.__new__(OdsDatasetConnector)
        connector.dataset = SimpleNamespace(
            base_url="data.bs.ch",
            source_identifier="100051",
            source_timestamp_field="event_time",
            db_timestamp_field="event_time",
        )
        connector.has_timestamp = True
        connector.logger = Mock()

        with tempfile.TemporaryDirectory() as tmpdir:
            filename = Path(tmpdir) / "100051.parquet"
            csv_path = Path(tmpdir) / "100051.csv"
            csv_path.write_text(
                "event_time;value\n"
                "2026-01-01T00:00:00+01:00;1\n"
                "2026-07-01T00:00:00+02:00;2\n",
                encoding="utf-8",
            )

            df = connector.download_ods_data(filename)

        self.assertIsInstance(df, pd.DataFrame)
        self.assertEqual(
            df["event_time"].dt.strftime("%Y-%m-%dT%H:%M:%S%z").tolist(),
            [
                "2026-01-01T00:00:00+0100",
                "2026-07-01T00:00:00+0200",
            ],
        )


class DatasetPersistenceTests(SimpleTestCase):
    @patch("reports.services.dataset_sync.DjangoPostgresClient")
    def test_streamed_connector_persistence_uses_direct_persist(self, mock_dbclient_cls):
        mock_dbclient = mock_dbclient_cls.return_value
        dataset = SimpleNamespace(
            id=93,
            name="CSV URL",
            target_table_name="commodity_prices",
            post_create_sql_commands=None,
            post_import_sql_commands=None,
        )
        processor = SimpleNamespace(
            persist_data=Mock(return_value=2),
        )

        service = DatasetSyncService()
        ok = service._persist_connector_data(dataset, processor)

        self.assertTrue(ok)
        processor.persist_data.assert_called_once_with(
            dbclient=mock_dbclient,
            table_name="commodity_prices",
            schema="opendata",
        )

    @patch("reports.services.dataset_sync.DjangoPostgresClient")
    def test_shared_dataframe_persistence_uses_upsert(self, mock_dbclient_cls):
        mock_dbclient = mock_dbclient_cls.return_value
        mock_dbclient.table_exists.return_value = True
        mock_dbclient.upsert_dataframe.return_value = 2
        dataset = SimpleNamespace(
            id=82,
            name="EIA",
            target_table_name="commodity_price",
            post_create_sql_commands=None,
            post_import_sql_commands=None,
        )
        processor = SimpleNamespace(
            get_unique_fields=lambda: ["commodity_code", "price_timestamp", "quote_type"],
            get_update_fields=lambda columns: [col for col in columns if col not in {"commodity_code", "price_timestamp", "quote_type"}],
        )
        df = pd.DataFrame(
            [
                {
                    "commodity_code": "RWTC",
                    "price_timestamp": datetime(2026, 3, 20, tzinfo=UTC),
                    "quote_type": "daily_close",
                    "price": Decimal("70.0"),
                },
                {
                    "commodity_code": "RBRTE",
                    "price_timestamp": datetime(2026, 3, 20, tzinfo=UTC),
                    "quote_type": "daily_close",
                    "price": Decimal("72.0"),
                },
            ]
        )

        service = DatasetSyncService()
        ok = service._persist_connector_dataframe(dataset, processor, df)

        self.assertTrue(ok)
        mock_dbclient.upsert_dataframe.assert_called_once()

    @patch("reports.services.dataset_sync.DjangoPostgresClient")
    def test_shared_dataframe_persistence_creates_table_when_missing(self, mock_dbclient_cls):
        mock_dbclient = mock_dbclient_cls.return_value
        mock_dbclient.table_exists.return_value = False
        mock_dbclient.create_table_from_dataframe.return_value = 2
        dataset = SimpleNamespace(
            id=91,
            name="CSV URL",
            target_table_name="commodity_prices",
            post_create_sql_commands=None,
            post_import_sql_commands=None,
        )
        processor = SimpleNamespace(
            get_unique_fields=lambda: ["id"],
            get_update_fields=lambda columns: [col for col in columns if col != "id"],
        )
        df = pd.DataFrame(
            [
                {"id": 1, "value": Decimal("10.0")},
                {"id": 2, "value": Decimal("11.0")},
            ]
        )

        service = DatasetSyncService()
        ok = service._persist_connector_dataframe(dataset, processor, df)

        self.assertTrue(ok)
        mock_dbclient.create_table_from_dataframe.assert_called_once()
        mock_dbclient.ensure_unique_index.assert_called_once_with(
            table_name="commodity_prices",
            unique_fields=["id"],
            schema="opendata",
        )
        mock_dbclient.upsert_dataframe.assert_not_called()

    @patch("reports.services.dataset_sync.DjangoPostgresClient")
    def test_shared_dataframe_persistence_replaces_table_for_replace_mode(self, mock_dbclient_cls):
        mock_dbclient = mock_dbclient_cls.return_value
        mock_dbclient.replace_table_from_dataframe.return_value = 2
        dataset = SimpleNamespace(
            id=92,
            name="CSV URL",
            target_table_name="commodity_prices",
            post_create_sql_commands=None,
            post_import_sql_commands=None,
        )
        processor = SimpleNamespace(get_write_mode=lambda: "replace")
        df = pd.DataFrame(
            [
                {"id": 1, "value": Decimal("10.0")},
                {"id": 2, "value": Decimal("11.0")},
            ]
        )

        service = DatasetSyncService()
        ok = service._persist_connector_dataframe(dataset, processor, df)

        self.assertTrue(ok)
        mock_dbclient.replace_table_from_dataframe.assert_called_once_with(
            df=df,
            table_name="commodity_prices",
            schema="opendata",
        )
        mock_dbclient.upsert_dataframe.assert_not_called()


class DatasetSyncSkipTests(SimpleTestCase):
    def test_yearly_ods_dataset_without_table_runs_initial_import(self):
        dataset = SimpleNamespace(
            source="ods",
            source_identifier="100508",
            target_table_name="ds_100508",
            data_update_frequency=SimpleNamespace(id=PeriodEnum.YEARLY.value),
            year_field="jahr",
            import_month=None,
            import_day=None,
            import_type=SimpleNamespace(id=ImportTypeEnum.NEW_YEAR.value),
            post_import_sql_commands=None,
            save=Mock(),
        )

        connector = OdsDatasetConnector.__new__(OdsDatasetConnector)
        connector.dataset = dataset
        connector.logger = Mock()
        connector.dbclient = Mock()
        connector.files_path = Path("/tmp")
        connector.target_table_exists = False
        connector.dataset_covers_period = Mock(return_value=True)
        connector._sync_new_table = Mock(return_value=True)
        connector._sync = Mock(return_value=False)

        ok = connector.synchronize()

        self.assertTrue(ok)
        connector._sync_new_table.assert_called_once()
        connector._sync.assert_not_called()
        dataset.save.assert_called_once()

    @patch("reports.services.dataset_sync.create_dataset_processor")
    def test_skip_datasets_are_ignored_before_connector_dispatch(self, mock_create_processor):
        dataset = SimpleNamespace(
            id=99,
            name="Local table",
            import_type=SimpleNamespace(id=ImportTypeEnum.SKIP.value),
        )

        service = DatasetSyncService()
        ok = service.synchronize_dataset(dataset)

        self.assertTrue(ok)
        mock_create_processor.assert_not_called()

    @patch.object(DatasetSyncService, "synchronize_dataset")
    @patch("reports.services.dataset_sync.Dataset.objects.filter")
    def test_synchronize_datasets_omits_explicit_skip_dataset(
        self,
        mock_filter,
        mock_synchronize_dataset,
    ):
        class FakeQuerySet:
            def __init__(self, items):
                self.items = list(items)

            def filter(self, **kwargs):
                filtered = self.items
                for key, value in kwargs.items():
                    filtered = [
                        item for item in filtered if getattr(item, key) == value
                    ]
                return FakeQuerySet(filtered)

            def exclude(self, **kwargs):
                filtered = self.items
                for key, value in kwargs.items():
                    filtered = [
                        item for item in filtered if getattr(item, key) != value
                    ]
                return FakeQuerySet(filtered)

            def order_by(self, *args):
                return self

            def count(self):
                return len(self.items)

            def exists(self):
                return bool(self.items)

            def first(self):
                return self.items[0] if self.items else None

            def __iter__(self):
                return iter(self.items)

        skipped_dataset = SimpleNamespace(
            id=100,
            name="Manual table",
            active=True,
            import_type_id=ImportTypeEnum.SKIP.value,
        )
        mock_filter.return_value = FakeQuerySet([skipped_dataset])

        service = DatasetSyncService()
        results = service.synchronize_datasets(dataset_id=100)

        self.assertTrue(results["success"])
        self.assertEqual(results["total_datasets"], 0)
        self.assertEqual(results["failed"], 0)
        self.assertEqual(results["details"][0]["skipped"], True)
        mock_synchronize_dataset.assert_not_called()

    @patch.object(DatasetSyncService, "cleanup_temp_files")
    @patch.object(DatasetSyncService, "synchronize_dataset")
    @patch("reports.services.dataset_sync.Dataset.objects.filter")
    def test_synchronize_datasets_keep_files_skips_cleanup(
        self,
        mock_filter,
        mock_synchronize_dataset,
        mock_cleanup_temp_files,
    ):
        class FakeQuerySet:
            def __init__(self, items):
                self.items = list(items)

            def exclude(self, **kwargs):
                filtered = self.items
                for key, value in kwargs.items():
                    filtered = [
                        item for item in filtered if getattr(item, key) != value
                    ]
                return FakeQuerySet(filtered)

            def order_by(self, *args):
                return self

            def count(self):
                return len(self.items)

            def exists(self):
                return bool(self.items)

            def __iter__(self):
                return iter(self.items)

        dataset = SimpleNamespace(
            id=101,
            name="ODS dataset",
            active=True,
            import_type_id=ImportTypeEnum.NEW_TIMESTAMP.value,
        )
        mock_filter.return_value = FakeQuerySet([dataset])
        mock_synchronize_dataset.return_value = True

        service = DatasetSyncService()
        results = service.synchronize_datasets(keep_files=True)

        self.assertTrue(results["success"])
        self.assertEqual(results["successful"], 1)
        mock_cleanup_temp_files.assert_not_called()


class StoryGenerationLanguageTests(SimpleTestCase):
    @patch("reports.management.commands.generate_stories.StoryGenerationService")
    def test_generate_stories_command_passes_language_code(self, mock_service_cls):
        mock_service = mock_service_cls.return_value
        mock_service.generate_stories.return_value = {
            "success": True,
            "successful": 0,
            "failed": 0,
            "skipped": 0,
            "details": [],
        }

        out = StringIO()
        call_command(
            "generate_stories",
            "--date",
            "2026-03-21",
            "--lang",
            "en",
            stdout=out,
        )

        mock_service.generate_stories.assert_called_once_with(
            template_id=None,
            story_focus_id=None,
            published_date=date(2026, 3, 21),
            force=False,
            language_code="en",
        )

    @patch("reports.management.commands.generate_stories.StoryGenerationService")
    def test_generate_stories_command_rejects_invalid_language_code(self, mock_service_cls):
        out = StringIO()

        call_command("generate_stories", "--lang", "it", stdout=out)

        self.assertIn("Invalid language code 'it'", out.getvalue())
        mock_service_cls.assert_not_called()

    @patch("reports.services.story_generation.StoryProcessor")
    def test_story_generation_service_passes_language_code_to_processor(self, mock_processor_cls):
        processor = mock_processor_cls.return_value
        processor.story = SimpleNamespace(id=42)
        processor.generate_story.return_value = True
        focus = SimpleNamespace(
            id=7,
            filter_value=None,
            story_template=SimpleNamespace(id=3, title="Template"),
        )

        service = StoryGenerationService()
        result = service.generate_story(
            focus=focus,
            published_date=date(2026, 3, 21),
            force=False,
            language_code="en",
        )

        self.assertTrue(result["success"])
        mock_processor_cls.assert_called_once_with(
            date(2026, 3, 21),
            focus.story_template,
            False,
            focus=focus,
            language_code="en",
        )

    def test_story_processor_skips_variants_for_english_only(self):
        processor = StoryProcessor.__new__(StoryProcessor)
        processor.requested_language_id = LanguageEnum.ENGLISH.value

        self.assertFalse(processor._should_generate_language_variants())

    @patch("reports.services.story_processor.Language.objects.exclude")
    def test_story_processor_limits_variants_to_requested_language(self, mock_exclude):
        ordered_languages = Mock()
        filtered_languages = Mock()
        mock_exclude.return_value.order_by.return_value = ordered_languages
        ordered_languages.filter.return_value = filtered_languages

        processor = StoryProcessor.__new__(StoryProcessor)
        processor.requested_language_id = LanguageEnum.GERMAN.value

        result = processor._get_requested_variant_languages()

        ordered_languages.filter.assert_called_once_with(id=LanguageEnum.GERMAN.value)
        self.assertIs(result, filtered_languages)


class GraphicRenderingTests(SimpleTestCase):
    def test_attach_graphic_chart_ids_normalizes_stale_vis_references(self):
        graphic = SimpleNamespace(
            content_html=(
                '<style>#vis.vega-embed{width:100%}</style>'
                '<div id="chart-79-b491c7f4"></div>'
                "<script>"
                "const el = document.getElementById('vis');"
                'vegaEmbed("#chart-79-b491c7f4", spec)'
                "</script>"
            )
        )

        _attach_graphic_chart_ids([graphic])

        self.assertEqual(graphic.chart_id, "chart-79-b491c7f4")
        self.assertIn("#chart-79-b491c7f4.vega-embed", graphic.content_html)
        self.assertIn(
            "document.getElementById('chart-79-b491c7f4')",
            graphic.content_html,
        )

    @patch("reports.views._resolve_story_for_language")
    def test_get_story_graphics_falls_back_to_english_variant(self, mock_resolve_story):
        empty_graphics = Mock()
        empty_graphics.exists.return_value = False
        english_graphics = Mock()
        english_graphics.exists.return_value = True
        english_story = SimpleNamespace(
            id=75,
            story_graphics=SimpleNamespace(defer=Mock(return_value=english_graphics)),
        )
        translated_story = SimpleNamespace(
            id=90,
            language_id=LanguageEnum.GERMAN.value,
            story_graphics=SimpleNamespace(defer=Mock(return_value=empty_graphics)),
        )
        mock_resolve_story.return_value = english_story

        graphics = _get_story_graphics(translated_story)

        self.assertIs(graphics, english_graphics)

    @patch("reports.visualizations.plotting.create_line_chart")
    def test_generate_chart_binds_the_option_to_the_given_chart_id(self, mock_create_line_chart):
        """Post-ECharts, chart builders return an option dict rather than an Altair
        chart, and generate_chart renders it into a container bound to chart_id.
        This previously asserted on Vega placeholder rewriting, which no longer
        happens."""
        mock_create_line_chart.return_value = {
            "series": [{"type": "line", "data": [1, 2, 3]}]
        }

        html = generate_chart(pd.DataFrame({"x": [], "y": []}), {"type": "line"}, "chart-123")

        self.assertIn('id="chart-123"', html)
        self.assertIn('getElementById("chart-123")', html)
        self.assertIn('__echartsInstances["chart-123"]', html)
        self.assertNotIn("vega", html.lower())


class MarketEventsImportHelpersTests(SimpleTestCase):
    def test_split_list_parses_semicolon_values(self):
        self.assertEqual(_split_list("oil; gold ; middle-east"), ["oil", "gold", "middle-east"])
        self.assertEqual(_split_list(""), [])

    def test_parse_bool_accepts_common_truthy_values(self):
        self.assertTrue(_parse_bool("true"))
        self.assertTrue(_parse_bool("Yes"))
        self.assertFalse(_parse_bool("false"))

    def test_parse_int_returns_none_for_empty_values(self):
        self.assertEqual(_parse_int("92"), 92)
        self.assertIsNone(_parse_int(""))


class StoryTableGenerationTests(TestCase):
    def setUp(self):
        period_category = LookupCategory.objects.create(
            id=PERIOD_CATEGORY_ID, name="Period", description=""
        )
        direction_category = LookupCategory.objects.create(
            id=PERIOD_DIRECTION_CATEGORY_ID, name="PeriodDirection", description=""
        )
        period = Period.objects.create(
            category=period_category, value="Daily", description="", sort_order=0
        )
        direction = PeriodDirection.objects.create(
            category=direction_category, value="Backward", description="", sort_order=0
        )
        self.template = StoryTemplate.objects.create(
            title="Template",
            description="",
            reference_period=period,
            period_direction=direction,
            prompt_text="prompt",
            active=True,
        )
        self.focus = StoryTemplateFocus.objects.create(
            story_template=self.template,
            filter_value=None,
        )
        self.story = Story.objects.create(
            templatefocus=self.focus,
            title="Story",
            summary="Summary",
            content="Content",
            published_date=date(2026, 2, 8),
            reference_period_start=date(2026, 2, 7),
            reference_period_end=date(2026, 2, 7),
        )
        self.table_template = StoryTemplateTable.objects.create(
            story_template=self.template,
            title="Oil Stats",
            sql_command="SELECT 1",
            sort_order=0,
        )

    def test_generate_table_replaces_missing_values_with_blank_strings(self):
        class StubDbClient:
            def run_query(self, sql, params):
                return pd.DataFrame(
                    [
                        {
                            "Metric": "Average",
                            "WTI": 64.51,
                            "WTI DATE": None,
                            "Brent Date": pd.NaT,
                        }
                    ]
                )

        processor = StoryProcessor.__new__(StoryProcessor)
        processor.dbclient = StubDbClient()
        processor.story = self.story
        processor.logger = None
        processor._replace_sql_expressions = lambda sql: sql
        processor._get_sql_command_params = lambda sql: {}
        processor._replace_reference_period_expression = lambda value: value

        table = StoryTable(story=self.story, table_template=self.table_template)

        ok = StoryProcessor.generate_table(processor, table)

        self.assertTrue(ok)
        saved_table = StoryTable.objects.get(
            story=self.story,
            table_template=self.table_template,
        )
        # generate_table stores the rows as a JSON string (see StoryProcessor), and
        # download_story_table_csv json.loads it back, so parse before comparing.
        self.assertEqual(
            json.loads(saved_table.data),
            [
                {
                    "Metric": "Average",
                    "WTI": 64.51,
                    "WTI DATE": "",
                    "Brent Date": "",
                }
            ],
        )


class PressReviewKeywordMatchTests(SimpleTestCase):
    def test_case_insensitive_and_word_boundary(self):
        self.assertEqual(keyword_matches("Die Basler Zeitung berichtet.", ["Basel"]), [])
        self.assertEqual(
            keyword_matches("Die Stadt Basel plant ein neues Projekt.", ["Basel", "Bern"]),
            ["Basel"],
        )

    def test_umlaut_normalization(self):
        self.assertEqual(
            keyword_matches("Neue Spitäler in der Region", ["Spitaeler"]), ["Spitaeler"]
        )

    def test_or_logic_multiple_matches(self):
        matches = keyword_matches("Wohnen und Klima sind Basel-Themen", ["Wohnen", "Klima", "Museen"])
        self.assertEqual(sorted(matches), ["Klima", "Wohnen"])


class PressReviewRelevanceParsingTests(SimpleTestCase):
    def test_parse_valid_response(self):
        score, reason = _parse_response(
            '{"score": 8, "reason": "Directly about Basel housing policy."}'
        )
        self.assertEqual(score, 8)
        self.assertEqual(reason, "Directly about Basel housing policy.")

    def test_parse_response_embedded_in_prose(self):
        text = 'Sure, here is the rating:\n{"score": 3, "reason": "Minor mention."}\nThanks.'
        score, reason = _parse_response(text)
        self.assertEqual(score, 3)

    def test_parse_response_missing_json_raises(self):
        with self.assertRaises(ValueError):
            _parse_response("no json here")

    def test_parse_response_out_of_range_raises(self):
        with self.assertRaises(ValueError):
            _parse_response('{"score": 15, "reason": "too high"}')


class PressReviewHarvestServiceTests(TestCase):
    """Ports pressreview's proven mandatory/topic/local-source filter behavior."""

    def setUp(self):
        self.source = PressReviewSource.objects.create(
            name="Test Source", rss_url="https://example.test/rss", active=True, local=False
        )
        self.local_source = PressReviewSource.objects.create(
            name="Local Source", rss_url="https://example.test/local-rss", active=True, local=True
        )
        PressReviewKeyword.objects.create(keyword="Basel", active=True, required=True)
        PressReviewKeyword.objects.create(keyword="Wohnen", active=True, required=False)

    def test_harvest_applies_mandatory_topic_and_local_exemption(self):
        entries_by_url = {
            self.source.rss_url: [
                {
                    "title": "Wohnen wird teurer in Basel",
                    "summary": "Ein Bericht ueber steigende Mieten.",
                    "link": "https://example.test/basel-wohnen",
                },
                {
                    "title": "Sport News",
                    "summary": "Ein Fussballspiel in Zuerich.",
                    "link": "https://example.test/sport",
                },
                {
                    "title": "Wohnen in der Schweiz allgemein",
                    "summary": "Kein Bezug zur Stadt.",
                    "link": "https://example.test/general-wohnen",
                },
            ],
            self.local_source.rss_url: [
                {
                    "title": "Neues Kulturzentrum eroeffnet",
                    "summary": "Wohnen und Kultur im neuen Zentrum.",
                    "link": "https://example.test/local-wohnen",
                },
            ],
        }

        def fake_session_get(url, timeout=None):
            response = Mock()
            response.raise_for_status.return_value = None
            response.content = url.encode()
            return response

        def fake_feedparser_parse(content):
            feed = Mock()
            feed.entries = entries_by_url.get(content.decode(), [])
            return feed

        with patch("reports.services.press_review_service.requests.Session") as session_cls, \
                patch(
                    "reports.services.press_review_service.feedparser.parse",
                    side_effect=fake_feedparser_parse,
                ):
            session_cls.return_value.get.side_effect = fake_session_get
            result = PressReviewHarvestService().harvest()

        self.assertEqual(result["articles_new"], 2)
        self.assertTrue(
            PressReviewArticle.objects.filter(link="https://example.test/basel-wohnen").exists()
        )
        self.assertTrue(
            PressReviewArticle.objects.filter(link="https://example.test/local-wohnen").exists()
        )
        self.assertFalse(
            PressReviewArticle.objects.filter(link="https://example.test/sport").exists()
        )
        self.assertFalse(
            PressReviewArticle.objects.filter(link="https://example.test/general-wohnen").exists()
        )

        basel_article = PressReviewArticle.objects.get(link="https://example.test/basel-wohnen")
        self.assertIn("Basel", basel_article.matched_keywords)
        self.assertIn("Wohnen", basel_article.matched_keywords)

        self.assertEqual(PressReviewHarvestLog.objects.count(), 1)


NEWS_SITEMAP_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
  <url>
    <loc>https://example.test/article-one</loc>
    <news:news>
      <news:publication><news:name>Example</news:name><news:language>en</news:language></news:publication>
      <news:publication_date>2026-07-31T09:00:00.000Z</news:publication_date>
      <news:title>Wohnen in Basel wird teurer</news:title>
      <news:keywords>housing, Basel</news:keywords>
    </news:news>
  </url>
  <url>
    <loc>https://example.test/article-two</loc>
    <news:news>
      <news:publication><news:name>Example</news:name><news:language>en</news:language></news:publication>
      <news:publication_date>2026-07-30T08:30:00Z</news:publication_date>
      <news:title>Sport results roundup</news:title>
    </news:news>
  </url>
  <url>
    <loc>https://example.test/not-a-news-entry</loc>
  </url>
</urlset>
"""


class PressReviewNewsSitemapParserTests(SimpleTestCase):
    """Google News sitemaps replace RSS for publishers that stopped maintaining feeds."""

    def test_parses_entries_into_the_feed_entry_shape(self):
        entries = parse_news_sitemap(NEWS_SITEMAP_XML)

        # The third <url> has no <news:news> block and must be ignored.
        self.assertEqual(len(entries), 2)
        first = entries[0]
        self.assertEqual(first["title"], "Wohnen in Basel wird teurer")
        self.assertEqual(first["link"], "https://example.test/article-one")
        self.assertEqual(first["tags_text"], "housing, Basel")
        # Sitemaps carry no article body — scoring works from the headline alone.
        self.assertEqual(first["summary"], "")

    def test_publication_dates_are_timezone_aware(self):
        entries = parse_news_sitemap(NEWS_SITEMAP_XML)

        for entry in entries:
            self.assertIsNotNone(entry["published_dt"])
            self.assertIsNotNone(entry["published_dt"].tzinfo)
        self.assertEqual(entries[0]["published_dt"].year, 2026)

    def test_entries_without_news_block_are_skipped(self):
        links = [entry["link"] for entry in parse_news_sitemap(NEWS_SITEMAP_XML)]
        self.assertNotIn("https://example.test/not-a-news-entry", links)


class PressReviewSitemapHarvestTests(TestCase):
    """A sitemap source flows through the same keyword filter and storage as RSS."""

    def setUp(self):
        self.source = PressReviewSource.objects.create(
            name="Sitemap Source",
            rss_url="https://example.test/sitemap/news.xml",
            feed_type=PressReviewSource.FEED_TYPE_NEWS_SITEMAP,
            active=True,
            local=True,
        )
        PressReviewKeyword.objects.create(keyword="Wohnen", active=True, required=False)

    def test_harvest_stores_articles_from_a_news_sitemap(self):
        def fake_get(url, timeout=None):
            response = Mock()
            response.raise_for_status.return_value = None
            response.content = NEWS_SITEMAP_XML
            return response

        with patch("reports.services.press_review_service.requests.Session") as session_cls, \
                patch(
                    "reports.services.press_review_service.settings."
                    "PRESSREVIEW_HARVEST_MAX_AGE_DAYS",
                    36500,
                ):
            session_cls.return_value.get.side_effect = fake_get
            result = PressReviewHarvestService().harvest()

        self.assertEqual(result["articles_new"], 1)
        article = PressReviewArticle.objects.get()
        self.assertEqual(article.link, "https://example.test/article-one")
        self.assertEqual(article.title, "Wohnen in Basel wird teurer")
        self.assertIn("Wohnen", article.matched_keywords)
        self.assertIsNotNone(article.published_date)


class PressReviewUserTopicHarvestTests(TestCase):
    """A user's own topics must widen the harvest, not just re-rank what was collected."""

    def setUp(self):
        self.source = PressReviewSource.objects.create(
            name="Source",
            rss_url="https://example.test/sitemap-topics.xml",
            feed_type=PressReviewSource.FEED_TYPE_NEWS_SITEMAP,
            active=True,
            local=True,
        )
        PressReviewKeyword.objects.create(keyword="housing", active=True, required=False)
        self.user = CustomUser.objects.create_user(
            email="topics@example.test", first_name="T", last_name="T"
        )

    SITEMAP = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
  <url><loc>https://example.test/war-story</loc><news:news>
    <news:publication><news:name>X</news:name><news:language>en</news:language></news:publication>
    <news:publication_date>2026-07-31T09:00:00Z</news:publication_date>
    <news:title>Signs the war is expanding</news:title>
  </news:news></url>
  <url><loc>https://example.test/other-story</loc><news:news>
    <news:publication><news:name>X</news:name><news:language>en</news:language></news:publication>
    <news:publication_date>2026-07-31T09:00:00Z</news:publication_date>
    <news:title>Local sports roundup</news:title>
  </news:news></url>
</urlset>
"""

    def _harvest(self):
        def fake_get(url, timeout=None):
            response = Mock()
            response.raise_for_status.return_value = None
            response.content = self.SITEMAP
            return response

        with patch("reports.services.press_review_service.requests.Session") as session_cls, \
                patch(
                    "reports.services.press_review_service.settings."
                    "PRESSREVIEW_HARVEST_MAX_AGE_DAYS",
                    36500,
                ):
            session_cls.return_value.get.side_effect = fake_get
            return PressReviewHarvestService().harvest()

    def test_topic_not_in_global_list_is_not_collected_without_a_user(self):
        self._harvest()
        self.assertFalse(
            PressReviewArticle.objects.filter(link="https://example.test/war-story").exists()
        )

    def test_a_user_topic_widens_the_harvest(self):
        UserPressReviewKeyword.objects.create(user=self.user, keyword="war")

        self._harvest()

        article = PressReviewArticle.objects.get(link="https://example.test/war-story")
        self.assertIn("war", article.matched_keywords)
        # Unrelated articles are still filtered out.
        self.assertFalse(
            PressReviewArticle.objects.filter(link="https://example.test/other-story").exists()
        )

    def test_extra_keywords_collect_articles_for_unsaved_topics(self):
        """The tool passes topics a user is still trying out into the harvest."""
        result = self._harvest_with(extra_keywords=["war"])

        self.assertEqual(result["articles_new"], 1)
        self.assertTrue(
            PressReviewArticle.objects.filter(link="https://example.test/war-story").exists()
        )

    def test_recently_fetched_sources_are_skipped(self):
        self.source.last_fetched_at = timezone.now()
        self.source.save(update_fields=["last_fetched_at"])

        result = self._harvest_with(extra_keywords=["war"], min_interval_minutes=15)

        self.assertEqual(result["sources_checked"], 0)
        self.assertEqual(PressReviewArticle.objects.count(), 0)

    def _harvest_with(self, **kwargs):
        def fake_get(url, timeout=None):
            response = Mock()
            response.raise_for_status.return_value = None
            response.content = self.SITEMAP
            return response

        with patch("reports.services.press_review_service.requests.Session") as session_cls, \
                patch(
                    "reports.services.press_review_service.settings."
                    "PRESSREVIEW_HARVEST_MAX_AGE_DAYS",
                    36500,
                ):
            session_cls.return_value.get.side_effect = fake_get
            return PressReviewHarvestService().harvest(**kwargs)

    def test_user_topics_do_not_duplicate_global_keywords(self):
        UserPressReviewKeyword.objects.create(user=self.user, keyword="Housing")
        PressReviewArticle.objects.all().delete()

        self._harvest()

        # 'Housing' differs only by case from the global 'housing'; it must not be
        # applied twice and produce a doubled matched_keywords entry.
        for article in PressReviewArticle.objects.all():
            matched = [m.strip().casefold() for m in article.matched_keywords.split(",")]
            self.assertEqual(len(matched), len(set(matched)))


class PressReviewSourceSelectionTests(TestCase):
    """An empty per-user source selection means 'all active sources'."""

    def setUp(self):
        self.included = PressReviewSource.objects.create(
            name="Included", rss_url="https://example.test/included"
        )
        self.excluded = PressReviewSource.objects.create(
            name="Excluded", rss_url="https://example.test/excluded"
        )
        self.included_article = PressReviewArticle.objects.create(
            source=self.included, title="Included article", link="https://example.test/a"
        )
        self.excluded_article = PressReviewArticle.objects.create(
            source=self.excluded, title="Excluded article", link="https://example.test/b"
        )
        self.user = CustomUser.objects.create_user(
            email="source-selection@example.test", first_name="S", last_name="S"
        )
        self.user.press_review_frequency = CustomUser.PRESS_REVIEW_FREQUENCY_DAILY
        self.user.save(update_fields=["press_review_frequency"])
        UserPressReviewKeyword.objects.create(user=self.user, keyword="Wohnen")

    def test_empty_selection_includes_all_sources(self):
        for article in (self.included_article, self.excluded_article):
            UserPressReviewArticleScore.objects.create(
                user=self.user, article=article, score=9
            )

        with patch("reports.services.press_review_service.EmailMultiAlternatives") as mail_cls:
            mail_cls.return_value.send.return_value = None
            result = PressReviewMailer().send_digests_for_date()

        self.assertEqual(result["total_articles"], 2)

    def test_selection_restricts_digest_to_chosen_sources(self):
        for article in (self.included_article, self.excluded_article):
            UserPressReviewArticleScore.objects.create(
                user=self.user, article=article, score=9
            )
        self.user.press_review_sources.set([self.included])

        with patch("reports.services.press_review_service.EmailMultiAlternatives") as mail_cls:
            mail_cls.return_value.send.return_value = None
            result = PressReviewMailer().send_digests_for_date()

        self.assertEqual(result["total_articles"], 1)
        # The deselected source's score stays unsent, so it is not silently consumed.
        self.assertTrue(
            UserPressReviewArticleScore.objects.get(
                user=self.user, article=self.included_article
            ).digest_sent
        )
        self.assertFalse(
            UserPressReviewArticleScore.objects.get(
                user=self.user, article=self.excluded_article
            ).digest_sent
        )


class PressReviewThresholdTests(TestCase):
    """The relevance threshold is a per-user dial applied at send time."""

    def setUp(self):
        self.source = PressReviewSource.objects.create(
            name="Source", rss_url="https://example.test/threshold"
        )
        self.user = CustomUser.objects.create_user(
            email="threshold@example.test", first_name="T", last_name="T"
        )
        self.user.press_review_frequency = CustomUser.PRESS_REVIEW_FREQUENCY_DAILY
        self.user.save(update_fields=["press_review_frequency"])
        UserPressReviewKeyword.objects.create(user=self.user, keyword="Wohnen")
        for index, score in enumerate((10, 7, 4, 2)):
            article = PressReviewArticle.objects.create(
                source=self.source,
                title=f"Article scoring {score}",
                link=f"https://example.test/threshold-{index}",
            )
            UserPressReviewArticleScore.objects.create(
                user=self.user, article=article, score=score
            )

    def _send(self):
        with patch("reports.services.press_review_service.EmailMultiAlternatives") as mail_cls:
            mail_cls.return_value.send.return_value = None
            return PressReviewMailer().send_digests_for_date()

    def test_new_user_defaults_to_the_site_wide_threshold(self):
        self.assertEqual(
            self.user.press_review_threshold,
            settings.PRESSREVIEW_RELEVANCE_THRESHOLD,
        )

    def test_threshold_controls_how_many_articles_are_sent(self):
        self.user.press_review_threshold = 7
        self.user.save(update_fields=["press_review_threshold"])
        self.assertEqual(self._send()["total_articles"], 2)  # scores 10 and 7

    def test_lower_threshold_widens_the_net(self):
        self.user.press_review_threshold = 3
        self.user.save(update_fields=["press_review_threshold"])
        self.assertEqual(self._send()["total_articles"], 3)  # 10, 7 and 4

    def test_threshold_is_per_user(self):
        strict = self.user
        strict.press_review_threshold = 10
        strict.save(update_fields=["press_review_threshold"])

        lenient = CustomUser.objects.create_user(
            email="lenient@example.test", first_name="L", last_name="L"
        )
        lenient.press_review_threshold = 1
        lenient.press_review_frequency = CustomUser.PRESS_REVIEW_FREQUENCY_DAILY
        lenient.save(
            update_fields=["press_review_threshold", "press_review_frequency"]
        )
        UserPressReviewKeyword.objects.create(user=lenient, keyword="Wohnen")
        for article in PressReviewArticle.objects.all():
            UserPressReviewArticleScore.objects.create(
                user=lenient, article=article, score=4
            )

        result = self._send()
        # strict user gets only the 10; lenient user gets all four of their 4s.
        self.assertEqual(result["total_sent"], 2)
        self.assertEqual(result["total_articles"], 5)


class PressReviewDigestCapTests(TestCase):
    """Articles are never pruned, so one digest is capped and the rest stays queued."""

    def setUp(self):
        self.source = PressReviewSource.objects.create(
            name="Source", rss_url="https://example.test/cap"
        )
        self.user = CustomUser.objects.create_user(
            email="cap@example.test", first_name="C", last_name="C"
        )
        self.user.press_review_frequency = CustomUser.PRESS_REVIEW_FREQUENCY_DAILY
        self.user.save(update_fields=["press_review_frequency"])
        UserPressReviewKeyword.objects.create(user=self.user, keyword="Wohnen")
        for index in range(5):
            article = PressReviewArticle.objects.create(
                source=self.source,
                title=f"Article {index}",
                link=f"https://example.test/cap-{index}",
            )
            UserPressReviewArticleScore.objects.create(
                user=self.user, article=article, score=9
            )

    def _send(self):
        with patch("reports.services.press_review_service.EmailMultiAlternatives") as mail_cls:
            mail_cls.return_value.send.return_value = None
            return PressReviewMailer().send_digests_for_date()

    @override_settings(PRESSREVIEW_DIGEST_MAX_ITEMS=2)
    def test_cap_limits_one_digest_and_reports_the_remainder(self):
        result = self._send()
        self.assertEqual(result["total_articles"], 2)
        self.assertEqual(result["total_held_back"], 3)

    @override_settings(PRESSREVIEW_DIGEST_MAX_ITEMS=2)
    def test_held_back_articles_go_out_on_later_runs(self):
        sent = 0
        for _ in range(3):
            sent += self._send()["total_articles"]
        # Nothing is dropped: all five arrive across successive runs.
        self.assertEqual(sent, 5)
        self.assertFalse(
            UserPressReviewArticleScore.objects.filter(
                user=self.user, digest_sent=False
            ).exists()
        )


class PressReviewRescoreTests(TestCase):
    """Editing topics leaves old scores stale, so re-scoring must clear and redo them."""

    def setUp(self):
        self.source = PressReviewSource.objects.create(
            name="Source", rss_url="https://example.test/rescore"
        )
        self.user = CustomUser.objects.create_user(
            email="rescore@example.test", first_name="R", last_name="R"
        )
        UserPressReviewKeyword.objects.create(user=self.user, keyword="Wohnen")
        self.articles = [
            PressReviewArticle.objects.create(
                source=self.source,
                title=f"Article {index}",
                link=f"https://example.test/rescore-{index}",
            )
            for index in range(3)
        ]
        for article in self.articles:
            UserPressReviewArticleScore.objects.create(
                user=self.user, article=article, score=2, reason="old topics"
            )

    def test_plain_rating_skips_already_scored_articles(self):
        """The gap that makes re-scoring necessary: existing scores are never revisited."""
        with patch.object(PressReviewRelevanceService, "_call_llm") as call_llm:
            result = PressReviewRelevanceService().rate_user(self.user)

        call_llm.assert_not_called()
        self.assertEqual(result["rated"], 0)

    def test_rescore_clears_and_recomputes_every_score(self):
        with patch.object(
            PressReviewRelevanceService,
            "_call_llm",
            return_value='{"score": 9, "reason": "new topics"}',
        ):
            result = PressReviewRelevanceService().rescore_user(self.user)

        self.assertEqual(result["rated"], 3)
        self.assertEqual(result["remaining"], 0)
        scores = UserPressReviewArticleScore.objects.filter(user=self.user)
        self.assertEqual(scores.count(), 3)
        self.assertTrue(all(s.score == 9 and s.reason == "new topics" for s in scores))

    def test_rescore_is_bounded_and_reports_the_remainder(self):
        with patch.object(
            PressReviewRelevanceService,
            "_call_llm",
            return_value='{"score": 9, "reason": "new topics"}',
        ):
            result = PressReviewRelevanceService().rescore_user(self.user, limit=2)

        self.assertEqual(result["rated"], 2)
        self.assertEqual(result["remaining"], 1)
        # The unscored remainder is exactly what the next scheduled run looks for.
        self.assertEqual(
            UserPressReviewArticleScore.objects.filter(user=self.user).count(), 2
        )

    def test_leftover_articles_are_picked_up_by_the_scheduled_run(self):
        with patch.object(
            PressReviewRelevanceService,
            "_call_llm",
            return_value='{"score": 9, "reason": "new topics"}',
        ):
            PressReviewRelevanceService().rescore_user(self.user, limit=2)
            PressReviewRelevanceService().rate_user(self.user)

        self.assertEqual(
            UserPressReviewArticleScore.objects.filter(user=self.user).count(), 3
        )

    def test_rescore_without_topics_does_nothing(self):
        self.user.press_review_keywords.all().delete()

        with patch.object(PressReviewRelevanceService, "_call_llm") as call_llm:
            result = PressReviewRelevanceService().rescore_user(self.user)

        call_llm.assert_not_called()
        self.assertEqual(result["rated"], 0)

    def test_rescore_endpoint_rejects_get(self):
        self.client.force_login(self.user)
        # LocaleMiddleware redirects the unprefixed URL to /en/..., so follow it;
        # otherwise this asserts on the redirect and never reaches require_POST.
        response = self.client.get(reverse("press_review_rescore"), follow=True)
        self.assertEqual(response.status_code, 405)


class PressReviewPruningTests(TestCase):
    """Retention pruning bounds table growth; scores cascade with their article."""

    def setUp(self):
        self.source = PressReviewSource.objects.create(
            name="Source", rss_url="https://example.test/prune"
        )
        self.user = CustomUser.objects.create_user(
            email="prune@example.test", first_name="P", last_name="P"
        )
        self.old = PressReviewArticle.objects.create(
            source=self.source, title="Old", link="https://example.test/prune-old"
        )
        self.recent = PressReviewArticle.objects.create(
            source=self.source, title="Recent", link="https://example.test/prune-recent"
        )
        # harvested_date is auto_now_add, so backdate through the queryset.
        PressReviewArticle.objects.filter(pk=self.old.pk).update(
            harvested_date=timezone.now() - timedelta(days=120)
        )
        for article in (self.old, self.recent):
            UserPressReviewArticleScore.objects.create(
                user=self.user, article=article, score=9
            )

    def test_prunes_only_articles_past_the_retention_window(self):
        result = PressReviewHarvestService().prune_stale_articles(retention_days=90)

        self.assertEqual(result["deleted_articles"], 1)
        self.assertFalse(PressReviewArticle.objects.filter(pk=self.old.pk).exists())
        self.assertTrue(PressReviewArticle.objects.filter(pk=self.recent.pk).exists())

    def test_scores_cascade_with_the_pruned_article(self):
        PressReviewHarvestService().prune_stale_articles(retention_days=90)

        self.assertFalse(
            UserPressReviewArticleScore.objects.filter(article_id=self.old.pk).exists()
        )
        self.assertTrue(
            UserPressReviewArticleScore.objects.filter(article_id=self.recent.pk).exists()
        )

    def test_dry_run_deletes_nothing(self):
        result = PressReviewHarvestService().prune_stale_articles(
            retention_days=90, dry_run=True
        )

        self.assertEqual(result["would_delete_articles"], 1)
        self.assertEqual(result["deleted_articles"], 0)
        self.assertEqual(PressReviewArticle.objects.count(), 2)

    def test_zero_retention_disables_pruning(self):
        result = PressReviewHarvestService().prune_stale_articles(retention_days=0)

        self.assertFalse(result["enabled"])
        self.assertEqual(PressReviewArticle.objects.count(), 2)


class PressReviewFrequencyTests(TestCase):
    """Digest frequency is a single per-user choice: none, daily or weekly."""

    def setUp(self):
        self.source = PressReviewSource.objects.create(
            name="Source", rss_url="https://example.test/freq"
        )
        self.article = PressReviewArticle.objects.create(
            source=self.source, title="An article", link="https://example.test/freq-a"
        )

    def _user(self, email, frequency):
        user = CustomUser.objects.create_user(
            email=email, first_name="F", last_name="F"
        )
        user.press_review_frequency = frequency
        user.save(update_fields=["press_review_frequency"])
        UserPressReviewKeyword.objects.create(user=user, keyword="Wohnen")
        UserPressReviewArticleScore.objects.create(
            user=user, article=self.article, score=9
        )
        return user

    def _send(self, frequency):
        with patch("reports.services.press_review_service.EmailMultiAlternatives") as mail_cls:
            mail_cls.return_value.send.return_value = None
            return PressReviewMailer().send_digests_for_date(frequency=frequency)

    def test_daily_run_only_mails_daily_users(self):
        daily = self._user("daily@example.test", CustomUser.PRESS_REVIEW_FREQUENCY_DAILY)
        weekly = self._user("weekly@example.test", CustomUser.PRESS_REVIEW_FREQUENCY_WEEKLY)

        result = self._send(CustomUser.PRESS_REVIEW_FREQUENCY_DAILY)

        self.assertEqual(result["total_sent"], 1)
        self.assertTrue(
            UserPressReviewArticleScore.objects.get(user=daily).digest_sent
        )
        # The weekly user's score is untouched, waiting for the weekly run.
        self.assertFalse(
            UserPressReviewArticleScore.objects.get(user=weekly).digest_sent
        )

    def test_weekly_run_only_mails_weekly_users(self):
        weekly = self._user("weekly@example.test", CustomUser.PRESS_REVIEW_FREQUENCY_WEEKLY)
        self._user("daily@example.test", CustomUser.PRESS_REVIEW_FREQUENCY_DAILY)

        result = self._send(CustomUser.PRESS_REVIEW_FREQUENCY_WEEKLY)

        self.assertEqual(result["total_sent"], 1)
        self.assertTrue(
            UserPressReviewArticleScore.objects.get(user=weekly).digest_sent
        )

    def test_frequency_none_never_receives_a_digest(self):
        opted_out = self._user("none@example.test", CustomUser.PRESS_REVIEW_FREQUENCY_NONE)

        for frequency in (
            CustomUser.PRESS_REVIEW_FREQUENCY_DAILY,
            CustomUser.PRESS_REVIEW_FREQUENCY_WEEKLY,
        ):
            self.assertEqual(self._send(frequency)["total_sent"], 0)

        self.assertFalse(
            UserPressReviewArticleScore.objects.get(user=opted_out).digest_sent
        )

    def test_scoring_skips_opted_out_users(self):
        self._user("none@example.test", CustomUser.PRESS_REVIEW_FREQUENCY_NONE)
        # A second, unscored article so there would be work to do if not skipped.
        PressReviewArticle.objects.create(
            source=self.source, title="Another", link="https://example.test/freq-b"
        )

        with patch.object(
            PressReviewRelevanceService, "_call_llm"
        ) as call_llm:
            result = PressReviewRelevanceService().rate_all_users()

        call_llm.assert_not_called()
        self.assertEqual(result["rated"], 0)


class MapColorBinTests(SimpleTestCase):
    """Value->colour binning for marker maps (settings-driven, not hand-written SQL)."""

    THRESHOLDS = [-1.2, -0.8, -0.4, 0, 0.4, 0.8, 1.2]
    COLORS = [
        "#b2182b", "#d6604d", "#f4a582", "#fddbc7",
        "#d1e5f0", "#92c5de", "#4393c3", "#2166ac",
    ]

    def _bins(self):
        return _parse_color_bins(
            {"thresholds": self.THRESHOLDS, "colors": self.COLORS}
        )

    def test_values_map_to_expected_bins(self):
        thresholds, colors, _ = self._bins()
        cases = {
            -2.0: "#b2182b",
            -0.69: "#f4a582",
            -0.001: "#fddbc7",
            0.55: "#92c5de",
            5.0: "#2166ac",
        }
        for value, expected in cases.items():
            self.assertEqual(_color_for_value(value, thresholds, colors), expected, value)

    def test_threshold_values_land_in_exactly_one_bin(self):
        """A value equal to a threshold belongs to the bin starting at it."""
        thresholds, colors, _ = self._bins()
        # -1.2 is the 1st threshold, so it must NOT fall in the "below first" bin.
        self.assertEqual(_color_for_value(-1.2, thresholds, colors), "#d6604d")
        self.assertEqual(_color_for_value(0, thresholds, colors), "#d1e5f0")
        self.assertEqual(_color_for_value(1.2, thresholds, colors), "#2166ac")

    def test_non_numeric_values_get_no_colour(self):
        thresholds, colors, _ = self._bins()
        for value in (None, "", "n/a", float("nan")):
            self.assertIsNone(_color_for_value(value, thresholds, colors))

    def test_colour_count_must_exceed_threshold_count_by_one(self):
        with self.assertRaises(ValueError):
            _parse_color_bins(
                {"thresholds": self.THRESHOLDS, "colors": self.COLORS[:-1]}
            )

    def test_thresholds_must_ascend(self):
        with self.assertRaises(ValueError):
            _parse_color_bins({"thresholds": [0, -1], "colors": ["#a", "#b", "#c"]})

    def test_missing_spec_returns_none(self):
        self.assertIsNone(_parse_color_bins(None))
        self.assertIsNone(_parse_color_bins({"colors": self.COLORS}))

    def test_map_applies_binned_colours_and_legend(self):
        rows = [
            {"lat": 47.564, "lon": 7.624, "change_5y": -0.69},
            {"lat": 47.556, "lon": 7.590, "change_5y": -1.40},
        ]
        html = create_map_markers(
            rows,
            {
                "lat": "lat", "lon": "lon",
                "marker_style": "circle", "marker_color": "change_5y",
                "color_bins": {"thresholds": self.THRESHOLDS, "colors": self.COLORS},
                "legend": True, "legend_title": "5y change",
            },
        )
        self.assertIn("#f4a582", html)
        self.assertIn("#b2182b", html)
        self.assertIn("odi-legend", html)
        self.assertIn("5y change", html)

    def test_literal_colour_field_still_works_without_bins(self):
        """Existing map graphics pass a colour string directly; must not regress."""
        html = create_map_markers(
            [{"lat": 47.5, "lon": 7.6, "color": "#ff0000"}],
            {"lat": "lat", "lon": "lon", "marker_style": "circle", "marker_color": "color"},
        )
        self.assertIn("#ff0000", html)
        self.assertNotIn("odi-legend", html)

    def test_invalid_spec_reports_error_instead_of_silently_defaulting(self):
        html = create_map_markers(
            [{"lat": 47.5, "lon": 7.6, "change_5y": -0.5}],
            {
                "lat": "lat", "lon": "lon",
                "marker_style": "circle", "marker_color": "change_5y",
                "color_bins": {"thresholds": self.THRESHOLDS, "colors": self.COLORS[:-1]},
            },
        )
        self.assertIn("chart-error", html)


class WebImportBoundaryTests(SimpleTestCase):
    """Serving a page must not drag in the ETL / LLM stack.

    reports/services/__init__.py once imported every service eagerly, so a single
    `from .services.database_client import ...` in views loaded pandas, pyarrow,
    wordcloud, matplotlib, anthropic and openai too. That put ~160 MB of unused
    libraries into every web worker and pushed the dynos past their 512 MB memory
    quota (hundreds of R14 errors). Nothing but this test stops it recurring the
    next time an import is added to the request path.
    """

    # Cost measured per library on this project, in MB of RSS.
    HEAVY_MODULES = {
        "pandas": 86, "pyarrow": 41, "wordcloud": 43, "matplotlib": 35,
        "anthropic": 36, "openai": 36, "sqlalchemy": 27, "numpy": 17,
        "feedparser": 11,
    }

    def _modules_loaded_by(self, target: str) -> set:
        """Import `target` in a clean interpreter and report which heavy libs load."""
        code = (
            "import django, os, sys\n"
            "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'report_generator.settings')\n"
            "django.setup()\n"
            f"__import__({target!r})\n"
            f"print(','.join(m for m in {sorted(self.HEAVY_MODULES)!r} if m in sys.modules))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, cwd=str(settings.BASE_DIR),
        )
        self.assertEqual(
            result.returncode, 0,
            f"could not import {target} in a subprocess:\n{result.stderr[-2000:]}",
        )
        return {m for m in result.stdout.strip().split(",") if m}

    def test_importing_views_does_not_load_the_etl_stack(self):
        loaded = self._modules_loaded_by("reports.views")
        if loaded:
            cost = sum(self.HEAVY_MODULES[m] for m in loaded)
            self.fail(
                f"reports.views imports {sorted(loaded)} at module level, adding "
                f"~{cost} MB to every web worker. Move the import inside the "
                f"function that needs it (see _format_dataset_cell_value or "
                f"press_review_view for the pattern)."
            )

    def test_importing_urls_does_not_load_the_etl_stack(self):
        """URL loading happens at startup, so it must stay light too."""
        loaded = self._modules_loaded_by("reports.urls")
        self.assertEqual(loaded, set(), f"reports.urls pulls in {sorted(loaded)}")

    def test_services_package_stays_lazy(self):
        """`reports.services` must not import its submodules eagerly."""
        loaded = self._modules_loaded_by("reports.services")
        self.assertEqual(
            loaded, set(),
            f"importing reports.services loaded {sorted(loaded)} — the package "
            "should expose names lazily via __getattr__, not import them.",
        )
