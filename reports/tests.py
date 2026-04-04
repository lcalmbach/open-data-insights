from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
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
from reports.models.subscription import StoryTemplateSubscription
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
            focus_filter="",
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

        response = self.client.get(reverse("stories"), {"story": self.story.id})
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

        response = self.client.get(reverse("stories"), {"story": self.story.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["rating_count"], 2)
        self.assertAlmostEqual(float(response.context["rating_avg"]), 4.5)
        self.assertEqual(response.context["rating_stars_full"], 4)
        self.assertEqual(response.context["rating_stars_half"], 1)

    def test_rate_story_creates_new_record_each_time(self):
        self.client.force_login(self.user)

        url = reverse("rate_story", args=(self.story.id,))
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

        response = self.client.get(reverse("home"))
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

        response = self.client.get(reverse("home"))

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

        response = self.client.get(reverse("home"), {"page": 2})

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

        response = self.client.get(reverse("home"), {"page": 3})

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
            focus_filter="district = 'A'",
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

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertIn(image_story, response.context["recent_stories"])
        self.assertContains(response, "https://example.com/card-image.jpg")
        self.assertNotContains(response, "Lead that should not appear in the card")
        self.assertContains(response, "Lead that should remain visible in the card")

    def test_home_view_counts_only_active_accessible_subscriptions(self):
        self.client.force_login(self.user)
        StoryTemplateSubscription.objects.create(
            user=self.user,
            story_template=self.template,
        )

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

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_subscription_count"], 1)
        self.assertEqual(response.context["available_subscriptions"], 1)
        self.assertContains(response, "1/1")

    def test_view_story_uses_story_detail_template(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("view_story", args=(self.story.id,)))

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
        region_category = LookupCategory.objects.create(
            id=REGION_CATEGORY_ID, name="Region", description=""
        )
        topic_category = LookupCategory.objects.create(
            id=TOPIC_CATEGORY_ID, name="Topic", description=""
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
        response = self.client.get(reverse("stories"), {"region": self.switzerland.id})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [story.id for story in response.context["stories"]],
            [self.story_energy.id],
        )

    def test_topic_filter_includes_descendant_topics(self):
        response = self.client.get(reverse("stories"), {"topic": self.energy.id})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [story.id for story in response.context["stories"]],
            [self.story_energy.id],
        )

    def test_search_matches_story_content(self):
        response = self.client.get(reverse("stories"), {"search": "consumption rose"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [story.id for story in response.context["stories"]],
            [self.story_energy.id],
        )

    def test_home_view_filters_by_region(self):
        response = self.client.get(reverse("home"), {"region": self.switzerland.id})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["featured_story"].id, self.story_energy.id)
        self.assertEqual(response.context["recent_stories"], [])

    def test_home_view_filters_by_time_frequency(self):
        response = self.client.get(reverse("home"), {"reference_period": "day"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["featured_story"].id, self.story_energy.id)
        self.assertEqual(response.context["recent_stories"], [])
        self.assertEqual(response.context["filter_summary"]["reference_period"], "Day")

    def test_home_view_filters_by_template(self):
        response = self.client.get(
            reverse("home"),
            {"template": self.template_population.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["featured_story"].id, self.story_population.id)
        self.assertEqual(response.context["recent_stories"], [])
        self.assertEqual(
            response.context["filter_summary"]["template"].id,
            self.template_population.id,
        )

    def test_stories_view_filters_by_time_frequency(self):
        response = self.client.get(reverse("stories"), {"reference_period": "month"})

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

    def test_focus_filter_placeholder_replaced(self):
        from datetime import date

        from reports.services.story_processor import StoryProcessor

        self.template.focus_filter_fields = "region"
        self.template.save(update_fields=["focus_filter_fields"])
        focus = StoryTemplateFocus.objects.create(
            story_template=self.template,
            filter_value="Zurich",
        )
        processor = StoryProcessor(anchor_date=date(2026, 2, 7), template=self.template, focus=focus)
        sql = "SELECT 1 WHERE :focus_filter AND %(year)s = 2026"
        replaced = processor._replace_sql_expressions(sql)
        self.assertIn("Zurich", replaced)
        self.assertIn("region", replaced)
        self.assertNotIn(":focus_filter", replaced)

    def test_default_focus_replaces_to_noop(self):
        from datetime import date

        from reports.services.story_processor import StoryProcessor

        self.template.focus_filter_fields = "region"
        self.template.save(update_fields=["focus_filter_fields"])
        focus = StoryTemplateFocus.objects.create(
            story_template=self.template,
            filter_value=None,
        )
        processor = StoryProcessor(anchor_date=date(2026, 2, 7), template=self.template, focus=focus)
        replaced = processor._replace_sql_expressions("SELECT 1 WHERE :focus_filter")
        self.assertIn("1=1", replaced)


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

        spec = chart.to_dict()

        self.assertEqual(len(spec["layer"]), 4)
        self.assertEqual(spec["layer"][1]["mark"]["type"], "rule")
        self.assertEqual(spec["layer"][1]["encoding"]["x"]["field"], "x")
        self.assertEqual(spec["layer"][1]["mark"]["color"], "red")
        self.assertEqual(spec["layer"][1]["mark"]["strokeWidth"], 2)
        self.assertNotIn("strokeDash", spec["layer"][1]["mark"])

        self.assertEqual(spec["layer"][2]["mark"]["type"], "text")
        self.assertEqual(spec["layer"][2]["mark"]["text"], "average")
        self.assertEqual(spec["layer"][2]["encoding"]["x"]["field"], "x")

        self.assertEqual(spec["layer"][3]["mark"]["type"], "rule")
        self.assertEqual(spec["layer"][3]["encoding"]["y"]["field"], "y")
        self.assertEqual(spec["layer"][3]["mark"]["color"], "blue")
        self.assertEqual(spec["layer"][3]["mark"]["strokeDash"], [6, 4])


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
            story_graphics=SimpleNamespace(all=Mock(return_value=english_graphics)),
        )
        translated_story = SimpleNamespace(
            id=90,
            language_id=LanguageEnum.GERMAN.value,
            story_graphics=SimpleNamespace(all=Mock(return_value=empty_graphics)),
        )
        mock_resolve_story.return_value = english_story

        graphics = _get_story_graphics(translated_story)

        self.assertIs(graphics, english_graphics)

    @patch("reports.visualizations.plotting.create_line_chart")
    def test_generate_chart_rewrites_all_vis_placeholders(self, mock_create_line_chart):
        chart = Mock()
        chart.to_html.return_value = (
            '<style>#vis.vega-embed{width:100%}</style>'
            '<div id="vis"></div>'
            "<script>"
            "const el = document.getElementById('vis');"
            'vegaEmbed("#vis", spec)'
            "</script>"
        )
        mock_create_line_chart.return_value = chart

        html = generate_chart(pd.DataFrame({"x": [], "y": []}), {"type": "line"}, "chart-123")

        self.assertIn('id="chart-123"', html)
        self.assertIn("#chart-123.vega-embed", html)
        self.assertIn("document.getElementById('chart-123')", html)
        self.assertIn('vegaEmbed("#chart-123"', html)


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
        self.assertEqual(
            saved_table.data,
            [
                {
                    "Metric": "Average",
                    "WTI": 64.51,
                    "WTI DATE": "",
                    "Brent Date": "",
                }
            ],
        )
