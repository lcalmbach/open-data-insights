from datetime import date
from decimal import Decimal

import pandas as pd
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from types import SimpleNamespace

from account.models import CustomUser
from reports.models.lookups import (
    PERIOD_CATEGORY_ID,
    PERIOD_DIRECTION_CATEGORY_ID,
    LookupCategory,
    Period,
    PeriodDirection,
)
from reports.models.story import Story
from reports.models.story_rating import StoryRating
from reports.models.story_table import StoryTable
from reports.models.story_table_template import StoryTemplateTable
from reports.models.story_template import StoryTemplate
from reports.models.story_template import StoryTemplateFocus
from reports.management.commands.import_commodity_prices import (
    CommodityMapping,
    _aggregate_monthly_prices,
)
from reports.management.commands.import_eia_oil_prices import (
    _aggregate_monthly_rows,
    _excel_serial_to_date,
    SERIES,
)
from reports.management.commands.import_market_events import (
    _parse_bool,
    _parse_int,
    _split_list,
)
from reports.services.story_processor import StoryProcessor
from reports.visualizations.plotting import create_line_chart


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


class CommodityPriceAggregationTests(SimpleTestCase):
    def test_historical_quotes_are_aggregated_to_monthly_averages(self):
        mapping = CommodityMapping(
            code="WTI_USD",
            commodity="WTI",
            unit="barrel",
            market="NYMEX",
        )
        prices = [
            {
                "price": 50,
                "currency": "USD",
                "code": "WTI_USD",
                "created_at": "2026-01-01T00:00:00.000Z",
                "type": "daily_average_price",
                "unit": "barrel",
                "source": "internal",
            },
            {
                "price": 49,
                "currency": "USD",
                "code": "WTI_USD",
                "created_at": "2026-01-01T00:30:00.000Z",
                "type": "spot_price",
                "unit": "barrel",
                "source": "oilprice.business_insider",
            },
            {
                "price": 70,
                "currency": "USD",
                "code": "WTI_USD",
                "created_at": "2026-01-02T00:00:00.000Z",
                "type": "daily_average_price",
                "unit": "barrel",
                "source": "internal",
            },
            {
                "price": 80,
                "currency": "USD",
                "code": "WTI_USD",
                "created_at": "2026-02-01T00:00:00.000Z",
                "type": "daily_average_price",
                "unit": "barrel",
                "source": "internal",
            },
        ]

        rows = _aggregate_monthly_prices(mapping, prices)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].price, Decimal("60.000000"))
        self.assertEqual(rows[0].year, 2026)
        self.assertEqual(rows[0].month, 1)
        self.assertEqual(rows[0].price_timestamp.isoformat(), "2026-01-01T00:00:00+00:00")
        self.assertEqual(rows[0].metadata["daily_points"], 2)
        self.assertEqual(rows[0].quote_type, "monthly_average")
        self.assertEqual(rows[1].price, Decimal("80.000000"))


class EiaOilImportTests(SimpleTestCase):
    def test_excel_serial_date_conversion(self):
        self.assertEqual(_excel_serial_to_date("31414"), date(1986, 1, 2))

    def test_daily_rows_are_aggregated_to_monthly_eia_rows(self):
        wti_series = next(series for series in SERIES if series.commodity_code == "RWTC")
        rows = _aggregate_monthly_rows(
            wti_series,
            [
                (date(2026, 1, 1), Decimal("70.0")),
                (date(2026, 1, 2), Decimal("74.0")),
                (date(2026, 2, 1), Decimal("80.0")),
            ],
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["commodity"], "WTI")
        self.assertEqual(rows[0]["year"], 2026)
        self.assertEqual(rows[0]["month"], 1)
        self.assertEqual(rows[0]["price"], Decimal("72.000000"))
        self.assertEqual(rows[0]["currency"], "USD")
        self.assertEqual(rows[0]["price_timestamp"].isoformat(), "2026-01-01T00:00:00+00:00")
        self.assertEqual(rows[0]["metadata"]["daily_points"], 2)


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
