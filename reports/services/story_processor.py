"""
Story Processing Classes
Contains the migrated Story class and related functionality from data_news.py
"""

import uuid
import json
import logging
import calendar
import re
import pandas as pd
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, Tuple
from decimal import Decimal
from django.conf import settings
from openai import OpenAI
from ..visualizations.plotting import generate_chart
from django.db.models import Max

from reports.services.database_client import DjangoPostgresClient
from reports.models.story_context import StoryTemplateContext
from reports.models.story_log import StoryLog
from reports.models.story_context import StoryTemplate
from reports.models.story import Story
from reports.models.story_table import StoryTable
from reports.models.graphic import Graphic
from reports.models.story_template import StoryTemplateFocus
from dateutil.relativedelta import relativedelta
from reports.models.lookups import PeriodDirectionEnum
from reports.constants.reference_period import ReferencePeriod


LLM_FORMATTING_INSTRUCTIONS = """
Format the output as plain Markdown.
Do not use bold or italic text for emphasis.
Avoid using bullet points, numbered lists, or subheadings.
Write in concise, complete sentences.
Ensure that the structure is clean and easy to read using only paragraphs.
""".strip()


class DecimalEncoder(json.JSONEncoder):
    """Custom JSON encoder that converts Decimal objects to float"""

    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()   # 'YYYY-MM-DD' or ISO datetime
        return super().default(obj)


def to_datetime_obj(d) -> Optional[datetime]:
    """Normalize various date-like inputs to a datetime (or None)."""
    if d is None:
        return None
    if isinstance(d, pd.Timestamp):
        return d.to_pydatetime()
    if isinstance(d, datetime):
        return d
    if isinstance(d, date):
        return datetime.combine(d, datetime.min.time())
    try:
        return pd.to_datetime(d).to_pydatetime()
    except Exception:
        return None


def to_date_obj(d) -> date:
    """Normalize various date-like inputs to a date (or None)."""
    dt = to_datetime_obj(d)
    return dt.date() if dt is not None else None


# Season mapping
month_to_season = {
    1: 4,
    2: 4,
    12: 4,  # Winter
    3: 1,
    4: 1,
    5: 1,  # Spring
    6: 2,
    7: 2,
    8: 2,  # Summer
    9: 3,
    10: 3,
    11: 3,  # Fall
}

season_dates = {
    1: ((3, 1), (5, 31)),  # Spring
    2: ((6, 1), (8, 31)),  # Summer
    3: ((9, 1), (11, 30)),  # Fall
    4: ((12, 1), (2, 28)),  # Winter
}


class StoryProcessor:
    """
    Migrated Story class from data_news.py
    Handles story generation, AI integration, and database operations
    """

    def __init__(
        self,
        published_date: date,
        template: StoryTemplate = None,
        force_generation: bool = False,
        story: Story = None,
        focus: StoryTemplateFocus | None = None,
    ):
        # verify if either template or story is provided
        if not template and not story:
            raise ValueError("Either template or story must be provided")
        
        self.dbclient = DjangoPostgresClient()
        self.force_generation = force_generation
        self.published_date = published_date
        self.template = template
        self.focus = focus
        template_id = getattr(self.template, "id", None)
        focus_id = getattr(self.focus, "id", None)
        template_title = getattr(self.template, "title", "") or ""
        self.logger = logging.getLogger(f"StoryProcessor.{template_id}.{focus_id} {template_title}")

        # If there is an existing story, reuse it and regenerate its content.
        if story:
            self.story = story

        else:
            most_recent_date_with_data = self._get_most_recent_day(template) or published_date
            # add a day for yearly, monthly or sesonal updated data: in such cases the data is set to e.g. 31.12. for yearly, 
            # which would result in the previous year being picked for backward looking stories. By adding a day, we ensure that the current 
            # year is picked as anchor date for the reference period calculation.
            anchor_date = most_recent_date_with_data if template.reference_period.value == 'day' else most_recent_date_with_data + timedelta(days=1)
            self.reference_period_start, self.reference_period_end = (
                self._get_reference_period(anchor_date, template)
            )
            self.season, self.season_year = self._get_season(
                self.reference_period_start, template
            )
            self.season, self.season_year = self._get_season(
                self.reference_period_start, template
            )   
            # safe access to year/month
            self.year = (
                self.reference_period_start.year
                if self.reference_period_start
                else datetime.now().year
            )
            self.month = (
                self.reference_period_start.month
                if self.reference_period_start
                else datetime.now().month
            )
            # self.last_reference_period_start_date = self._get_last_published_date()
            self.is_data_based = StoryTemplateContext.objects.filter(
                story_template=template
            ).exists()
            # true means: insight does not exist for refernece period and conditions are met
            if self.story_is_due(self.reference_period_start):
                self.story = (
                    Story.objects.filter(
                        templatefocus=focus if focus is not None else template.default_focus,
                        reference_period_start=self.reference_period_start,
                        reference_period_end=self.reference_period_end,
                    ).first()
                    or Story()  # creates a new, empty instance if no match
                )
                if self.story.id is None:
                    self.focus = focus if focus is not None else template.default_focus
                    if self.focus is None:
                        raise ValueError(
                            f"StoryTemplate {getattr(template, 'id', None)} has no default focus row"
                        )
                    self.story.templatefocus = self.focus
                    self.story.reference_period_start = self.reference_period_start
                    self.story.reference_period_end = self.reference_period_end
                    self.story.published_date = self.published_date
                else:
                    # Existing story found: ensure focus/templatefocus are set for downstream logic.
                    self.focus = self.story.templatefocus
            else:
                self.story = None  # not due, so we won't generate a story


            if self.story:
                self.template = template

                if not getattr(self.story, "ai_model", None):
                    self.story.ai_model = getattr(settings, "DEFAULT_AI_MODEL", "gpt-4o")
                self.ai_client = self.get_ai_client()


    def get_ai_client(self) -> OpenAI:
        if self.story.ai_model == "deepseek-chat":
            api_key = getattr(settings, "DEEPSEEK_API_KEY", None)
            return OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        else:
            api_key = getattr(settings, "OPENAI_API_KEY", None)
            return OpenAI(api_key=api_key)


    def _replace_reference_period_expression(self, expression: str) -> str:
        """Replace reference period expression in SQL command"""
        result = expression.replace(
            ":reference_period_start", str(self.story.reference_period_start)
        )
        result = result.replace(
            ":reference_period_end", str(self.story.reference_period_end)
        )
        # Safe month name lookup
        month_name = (
            calendar.month_name[self.month] if 1 <= self.month <= 12 else "Unknown"
        )
        result = result.replace(":reference_period_month", month_name)
        result = result.replace(":reference_period_year", str(self.year))
        result = result.replace(":reference_period_previous_year", str(self.year - 1))
        result = result.replace(":reference_period_season", self._season_name())
        result = result.replace(":reference_period", self.story.reference_period_expression)
        result = result.replace(
            ":published_date", self.story.published_date.strftime("%Y-%m-%d")
        )
        result = result.replace(":filter_value", self.focus.filter_value if self.focus and self.focus.filter_value else "")
        result = result.replace(":filter_expression", self.focus.filter_expression if self.focus and self.focus.filter_expression else "")
        return result

    def _get_focus_filter_expression(self) -> str:
        """
        Return the SQL snippet used to restrict queries to the current focus.

        Templates should embed `:focus_filter` in their SQL where a focus condition
        is expected.
        - For default/no-filter focuses, substitute `1=1` (no-op).
        - For filtered focuses, build an expression from
          `template.focus_filter_fields` and `focus.filter_value`.
        """
        if not self.focus:
            return "1=1"

        filter_value = (getattr(self.focus, "filter_value", None) or "").strip()
        if not filter_value:
            return "1=1"

        focus_fields_raw = (getattr(self.template, "focus_filter_fields", None) or "").strip()
        if not focus_fields_raw:
            return "1=1"

        def quote_ident(ident: str) -> str:
            parts = [p.strip() for p in ident.split(".") if p.strip()]
            if not parts:
                raise ValueError("empty identifier")
            for part in parts:
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part):
                    raise ValueError(f"invalid identifier part: {part!r}")
            return ".".join(f'"{p}"' for p in parts)

        fields: list[str] = []
        for raw in focus_fields_raw.split(","):
            name = raw.strip()
            if not name:
                continue
            try:
                fields.append(quote_ident(name))
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("Invalid focus_filter_fields entry %r: %s", name, exc)

        if not fields:
            return "1=1"

        value_sql = filter_value.replace("'", "''")
        clauses = [f"{field} = '{value_sql}'" for field in fields]
        if len(clauses) == 1:
            return clauses[0]
        return "(" + " OR ".join(clauses) + ")"

    def _replace_sql_expressions(self, sql: str) -> str:
        """
        Replace placeholders in SQL statements, including reference period
        expressions and the `:focus_filter` token.
        """
        if not sql:
            return sql
        result = self._replace_reference_period_expression(sql)
        return result.replace(":focus_filter", self._get_focus_filter_expression())

    def story_is_due(self, reference_period_start) -> bool:
        """
        Check if the story should be generated
        is_due is determined by:
        has _sql_data: if the required data exists, for example a yearly report for 2024 can only be generated if there is data for 2024 in the data source.
                       if not has_sql_data conditions are set , the data is assumed to exist
        date_is_due:   the day and month for
        publish_conditions_met:  some insights may be created daily, but the insigth is only generated if a condition is met, e.g. the temperature is above the 95th percentile
                                 for all days for this month.
        force                 :  overrides all other conditions and forces the story to be generated.
        """
        try:

            def _get_publish_conditions_result() -> bool:
                """
                Checks whether all publish conditions defined in the story template are met.

                Returns:
                    bool: True if all conditions are met, False otherwise.
                """
                publish_conditions = getattr(self.focus, "publish_conditions", None) if self.focus else None
                if publish_conditions:
                    params = self._get_sql_command_params(publish_conditions)
                    df = self.dbclient.run_query(
                        publish_conditions, params
                    )
                    if df is not None:
                        return df.iloc[0, 0] == 1
                    else:
                        return False    
                else:
                    return True  # no conditions defined, so we assume they are met

            story_exists = False
            publish_conditions_met = True

            if self.force_generation:
                return True
            
            story_exists = Story.objects.filter(
                templatefocus=self.focus,
                reference_period_start=reference_period_start,
            ).exists()
            publish_conditions_met = (
                _get_publish_conditions_result() if not story_exists else False
            )
            return not story_exists and publish_conditions_met
        # print(f"Story is due: {is_due}, has_data: {has_data}, date_is_due: {date_is_due}, publish_conditions_met: {publish_conditions_met}, regular_due_date: {regular_due_date}, last_published_date: {self.last_reference_period_start_date}")

        except Exception as e:
            self.logger.error(f"Error checking if story is due: {e}")
            return False

    def generate_table(self, table: StoryTable):
        table_template = table.table_template
        sql_cmd = self._replace_sql_expressions(table_template.sql_command)
        params = self._get_sql_command_params(sql_cmd)
        try:
            df = self.dbclient.run_query(sql_cmd, params)
            data = df.to_dict(orient="records")
            story_table = StoryTable.objects.filter(
                story=self.story, table_template=table_template
            ).first() or StoryTable(story=self.story, table_template=table_template)
            story_table.title = self._replace_reference_period_expression(
                table_template.title
            )
            story_table.data = json.dumps(
                data, indent=2, ensure_ascii=False, cls=DecimalEncoder
            )
            story_table.sort_order = table_template.sort_order
            story_table.save()
            return True
        except Exception as e:
            self.logger.error(f"Error generating table {table_template.id}: {e}")
            return False

    def _generate_tables(self):
        """Generate tables for the story"""
        from django.db import transaction

        table_templates = self.story.template.story_template_tables.all()
        self.logger.info(f"Found {table_templates.count()} table templates to process")

        for table_template in table_templates:
            with transaction.atomic():
                tables = StoryTable.objects.filter(
                    story=self.story, table_template=table_template
                )
                if not tables.exists():
                    table = StoryTable(story=self.story, table_template=table_template)
                else:
                    if tables.count() > 1:
                        # Keep only the first, delete the rest
                        table = tables.first()
                        tables.exclude(id=table.id).delete()
                    else:
                        table = tables.first()
                self.generate_table(table)

    def generate_graphic(self, graphic: Graphic):
        try:
            graphic_template = graphic.graphic_template
            sql_command = self._replace_sql_expressions(graphic_template.sql_command)
            if not sql_command:
                self.logger.warning(
                    f"Empty SQL command for graphic template: {graphic_template.title}"
                )
                return

            # Replace parameters in SQL
            params = self._get_sql_command_params(sql_command)
            self.logger.info(f"Executing SQL for graphic: {graphic_template.title}")

            # Execute SQL to get data
            data = self.dbclient.run_query(sql_command, params)

            if data is None or len(data) == 0:
                self.logger.warning(
                    f"No data returned for graphic template: {graphic_template.title}"
                )
                return

            # Generate unique chart ID
            chart_id = f"chart-{graphic_template.id}-{uuid.uuid4().hex[:8]}"
            # Use settings from template
            settings = graphic_template.settings
            settings["type"] = graphic_template.graphic_type

            # Generate chart HTML
            self.logger.info(f"Generating chart for: {graphic_template.title}")
            if "y" in settings:
                col = settings["y"]
                data[col] = pd.to_numeric(data[col], errors="coerce")
            chart_html = generate_chart(data=data, settings=settings, chart_id=chart_id)

            graphic.title = self._replace_reference_period_expression(
                graphic_template.title
            )
            graphic.content_html = chart_html
            data = data.map(str)
            graphic.data = json.dumps(
                data.to_dict(orient="records"),
                indent=2,
                ensure_ascii=False,
                cls=DecimalEncoder,
            )
            graphic.sort_order = graphic_template.sort_order
            graphic.save()

            self.logger.info(
                f"Successfully generated and saved graphic: {graphic_template.title} {graphic.id}"
            )
            return True

        except Exception as e:
            self.logger.error(
                f"Error generating graphic '{graphic_template.title}': {str(e)}"
            )
            import traceback

            self.logger.error(traceback.format_exc())
            return False

    def _generate_graphics(self) -> list:
        """Generate graphics for the story template and save them directly to database"""
        graphic_templates = self.story.template.graphic_templates.all()
        self.logger.info(
            f"Found {graphic_templates.count()} graphic templates to process"
        )

        for graphic_template in graphic_templates:
            graphics = Graphic.objects.filter(
                story=self.story, graphic_template=graphic_template
            )
            if not graphics.exists():
                graphic = Graphic(story=self.story, graphic_template=graphic_template)
            else:
                if graphics.count() > 1:
                    # delete all but the last graphic
                    for g in graphics[:-1]:
                        g.delete()
                graphic = graphics.first()
            self.generate_graphic(graphic)

    def generate_story(self) -> bool:
        """Generate the complete story"""
        try:
            self.logger.info(
                "Initializing story generation (template_id=%s, template_title=%s, focus_id=%s, focus_value=%s, published_date=%s, story_id=%s)",
                getattr(getattr(self.story, "template", None), "id", None),
                getattr(getattr(self.story, "template", None), "title", ""),
                getattr(getattr(self.story, "templatefocus", None), "id", None),
                getattr(getattr(self.story, "templatefocus", None), "filter_value", None) or "",
                getattr(self.story, "published_date", None).strftime("%Y-%m-%d") if getattr(self.story, "published_date", None) else "",
                getattr(self.story, "id", None),
            )
            if self.is_data_based:
                self.story.context_values = self._get_context_data()

            # Generate content
            self.logger.info("Generating story content...")
            # generate main content
            self._generate_insight_text()
            if not self.story.content:
                raise RuntimeError(
                    f"Failed to generate story content for template {self.story.template.id}"
                )
            self.logger.info("Generating lead...")
            self.generate_lead()
            self.logger.info("Generating title...")
            self.generate_title()

            self.logger.info("Saving story to database...")
            try:
                self.story.full_clean()  # This validates the model
            except Exception as validation_error:
                self.logger.error(f"Validation error: {validation_error}")
                # Print all fields and their values for debugging
                for field in self.story._meta.fields:
                    self.logger.info(
                        f"Field '{field.name}': {getattr(self.story, field.name, None)}"
                    )
                return False

            self.story.save()
            self.logger.info("Generating tables...")
            self._generate_tables()
            self.logger.info("Generating graphics...")
            self._generate_graphics()
            self._save_log_record()

            # Execute post-publish commands
            if self.story.template.post_publish_command:
                self.logger.info("Executing post-publish command...")
                cmd = self._replace_sql_expressions(self.story.template.post_publish_command)
                self.dbclient.run_action_query(cmd)

            self.logger.info("Story generation completed successfully")
            return True
        except Exception as e:
            self.logger.exception(
                "Error generating story (template_id=%s, focus_id=%s, story_id=%s, reference_period_start=%s, reference_period_end=%s)",
                getattr(getattr(self.story, "template", None), "id", None) if getattr(self, "story", None) else getattr(self.template, "id", None),
                getattr(getattr(self.story, "templatefocus", None), "id", None) if getattr(self, "story", None) else getattr(self.focus, "id", None),
                getattr(getattr(self, "story", None), "id", None),
                getattr(getattr(self, "reference_period_start", None), "isoformat", lambda: None)(),
                getattr(getattr(self, "reference_period_end", None), "isoformat", lambda: None)(),
            )
            return False

    def _get_most_recent_day(self, template) -> Optional[datetime]:
        """
        Retrieves the most recent day related to the current story from the database.
        Executes a SQL query defined in the template to fetch the most recent date,
        using the story's published_date as a parameter. Returns the date as a
        pandas.Timestamp if available, otherwise returns None.
        Returns:
            Optional[datetime]: The most recent day as a datetime object, or None if
            not found or if an error occurs during the query.
        """

        if template.most_recent_day_sql:
            params= {}
            try:
                params = params = self._get_sql_command_params(template.most_recent_day_sql)
                df = self.dbclient.run_query(template.most_recent_day_sql, params)
                if not df.empty and df.iloc[0, 0] is not None:
                    # return a date object for consistency with DB DateFields
                    return to_date_obj(pd.to_datetime(df.iloc[0, 0]))
                return None
            except Exception as e:
                return None
        else:
            return None

    def _get_last_published_date(self) -> Optional[datetime]:
        """Get the last published date for this template"""
        return Story.objects.filter(templatefocus=self.story.templatefocus).aggregate(
            Max("reference_period_start")
        )["reference_period_start__max"]

    def _get_season(
        self, reference_period_start: datetime, template: StoryTemplate
    ) -> Tuple[int, int]:
        """Get season and season year based on reference period"""

        season = month_to_season[reference_period_start.month]
        season_year = (
            reference_period_start.year
            if reference_period_start.month >= 3
            else reference_period_start.year - 1
        )
        return season, season_year

    def _get_reference_period(
        self, anchor_date: datetime, template: StoryTemplate
    ) -> Tuple[datetime, datetime]:
        """Get the reference period start and end dates relative to published_date.

        This consolidates forward/backward logic: compute the period containing an
        anchor date (most_recent_day if available, else published_date) and then
        shift that period by -1 (backward) or +1 (forward) depending on
        template.period_direction.
        Returns date objects (period_start, period_end).
        """

        # Determine the base period that contains anchor_date
        if template.reference_period_id in (
            ReferencePeriod.DAILY.value,
            ReferencePeriod.IRREGULAR.value,
        ):
            base_start = anchor_date
            base_end = anchor_date
            unit = "days"
        elif template.reference_period_id == ReferencePeriod.WEEKLY.value:
            # week starting on Monday that contains anchor
            week_start = anchor_date - pd.DateOffset(days=anchor_date.weekday())
            base_start = week_start
            base_end = week_start + pd.DateOffset(days=6)
            unit = "weeks"
        elif template.reference_period_id == ReferencePeriod.MONTHLY.value:
            base_start = datetime(anchor_date.year, anchor_date.month, 1)
            base_end = datetime(
                anchor_date.year,
                anchor_date.month,
                calendar.monthrange(anchor_date.year, anchor_date.month)[1],
            )
            unit = "months"
        elif template.reference_period_id == ReferencePeriod.SEASONAL.value:
            season_idx, season_year = self._get_season(anchor_date, template)
            sm, sd = season_dates[season_idx][0]
            em, ed = season_dates[season_idx][1]
            start_year = season_year
            end_year = start_year if em >= sm else start_year + 1
            base_start = datetime(start_year, sm, sd)
            base_end = datetime(end_year, em, ed)
            base_end += pd.DateOffset(days=1)
            unit = "season"
        elif template.reference_period_id == ReferencePeriod.YEARLY.value:
            base_start = datetime(anchor_date.year, 1, 1)
            base_end = datetime(anchor_date.year, 12, 31)
            unit = "years"
        else:
            # fallback: single-day period at anchor
            base_start = anchor_date
            base_end = anchor_date
            unit = "days"

        shift = 0
        if template.period_direction_id == PeriodDirectionEnum.Forward.value:
            shift = 1
        elif template.period_direction_id == PeriodDirectionEnum.Backward.value:    
            shift = -1
        
        # Apply the shift
        if unit == "days":
            period_start = base_start + pd.DateOffset(days=shift)
            period_end = base_end + pd.DateOffset(days=shift)
        elif unit == "weeks":
            period_start = base_start + pd.DateOffset(days=7 * shift)
            period_end = base_end + pd.DateOffset(days=7 * shift)
        elif unit == "months":
            period_start = base_start + relativedelta(months=shift)
            # recompute end as last day of the target month
            period_end = datetime(
                period_start.year,
                period_start.month,
                calendar.monthrange(period_start.year, period_start.month)[1],
            )
        elif unit == "season":
            # compute new season index/year
            cur_season, cur_season_year = self._get_season(anchor_date, template)
            new_index = cur_season - 1 + shift
            new_year = cur_season_year + (new_index // 4)
            new_season = (new_index % 4) + 1
            sm, sd = season_dates[new_season][0]
            em, ed = season_dates[new_season][1]
            start_year = new_year
            end_year = start_year if em >= sm else start_year + 1
            period_start = datetime(start_year, sm, sd)
            period_end = datetime(end_year, em, ed)
            period_end += pd.DateOffset(days=1)
        elif unit == "years":
            period_start = base_start + relativedelta(years=shift)
            period_end = datetime(period_start.year, 12, 31)
        else:
            period_start = base_start + pd.DateOffset(days=shift)
            period_end = base_end + pd.DateOffset(days=shift)

        # normalize to date objects
        if isinstance(period_start, datetime):
            period_start = period_start.date()
        if isinstance(period_end, datetime):
            period_end = period_end.date()

        return period_start, period_end

    def _season_name(self) -> str:
        """Get season name from season number"""
        season_names = {1: "Spring", 2: "Summer", 3: "Fall", 4: "Winter"}
        return season_names.get(self.season, "Unknown Season")

    def _get_context_data(self) -> dict:
        """File "/home/lcalm/Work/Dev/data_news_agent/src/data_news.py", line 329, in get_context_data
        Retrieves the comparisons for the story from the database.
        This method queries the database for the comparisons defined in the story configuration.

        Returns:
            dict: A dictionary containing the comparisons for the story.
        """
        result = {}
        context_data = StoryTemplateContext.objects.filter(
            story_template_id=self.story.template.id
        ).order_by("sort_order")

        for context_item in context_data:
            key = self._replace_reference_period_expression(context_item.key)
            key = key.replace(" ", "_").lower()
            result[key] = {}
            result[key]["description"] = context_item.description

            cmd = self._replace_sql_expressions(context_item.sql_command)
            params = self._get_sql_command_params(cmd)
            self.logger.info(f"Running context query for key: {key}")
            df = self.dbclient.run_query(cmd, params)
            if df.empty:
                self.logger.warning(
                    f"No data found for context key: {context_item.key}"
                )
            elif len(df) > 1:
                result[key]["data"] = df.to_dict(orient="records")
            else:
                df = df.iloc[0].to_frame().T
                result[key]["data"] = df.to_dict(orient="records")

        result = json.dumps(
            {"context_data": result}, indent=2, ensure_ascii=False, cls=DecimalEncoder
        )
        return result

    def _get_sql_command_params(self, cmd: str) -> Dict[str, Any]:
        """Get parameters for SQL command"""
        params = {}
        if not cmd:
            return params

        # Guard against invalid named-parameter syntax like `%()s`.
        if "%()s" in cmd:
            raise ValueError(
                "Invalid SQL parameter placeholder `%()s`. "
                "Use a named placeholder like `%(filter_value)s` or `%(bfs_nr)s`."
            )

        if "%(period_start_date)s" in cmd:
            params["period_start_date"] = (
                self.reference_period_start.strftime("%Y-%m-%d")
                if self.reference_period_start
                else self.published_date.strftime("%Y-%m-%d")
            )
        if "%(period_end_date)s" in cmd:
            params["period_end_date"] = (
                self.reference_period_end.strftime("%Y-%m-%d")
                if self.reference_period_end
                else self.published_date.strftime("%Y-%m-%d")
            )
        if "%(published_date)s" in cmd:
            params["published_date"] = self.published_date.strftime("%Y-%m-%d")
        if "%(month)s" in cmd:
            params["month"] = self.month
        if "%(season_year)s" in cmd:
            params["season_year"] = self.year
        if "%(year)s" in cmd:
            params["year"] = self.year
        if "%(previous_year)s" in cmd:
            params["previous_year"] = self.year - 1
        if "%(season)s" in cmd:
            params["season"] = month_to_season[self.month]
        if "%(filter_value)s" in cmd:
            raw = self.focus.filter_value if self.focus and self.focus.filter_value else ""
            raw = str(raw).strip()
            params["filter_value"] = int(raw) if raw.isdigit() else raw
        if "%(filter_expression)s" in cmd:
            params["filter_expression"] = (
                self.focus.filter_expression
                if self.focus and self.focus.filter_expression
                else ""
            )
        if "%(bfs_nr)s" in cmd:
            raw = self.focus.filter_value if self.focus and self.focus.filter_value else ""
            raw = str(raw).strip()
            params["bfs_nr"] = int(raw) if raw.isdigit() else raw


        return params

    def _save_log_record(self):
        """Save a log record for the story generation"""
        try:
            # Use Django ORM to create the log record
            StoryLog.objects.create(
                reference_period_start=self.story.reference_period_start,
                reference_period_end=self.story.reference_period_end,
                story=self.story,
                publish_date=self.story.published_date,
            )
            self.logger.info("Log record for story generation was successfully saved.")
        except Exception as e:
            self.logger.error(f"Error saving log record: {e}")
            raise

    def _generate_insight_text(self) -> bool:
        """Generate story text using OpenAI API"""
        try:
            message = self._replace_reference_period_expression(
                self.story.template.prompt_text
            )  # Prepare messages for chat completion
            
            #if self.focus.additional_context:
            #    message += f"\n\nAdditional context: {self.focus.additional_context}"
            
            if self.is_data_based:
                messages = [
                    {
                        "role": "system",
                        "content": f"{message}\n\n{LLM_FORMATTING_INSTRUCTIONS}",
                    },
                    {
                        "role": "user",
                        "content": (
                            "Write an insight about the following data in JSON format.\n\n"
                            "```json\n" + self.story.context_values + "\n```"
                        ),
                    },
                ]
            else:
                messages = [
                    {"role": "system", "content": self.story.template.system_prompt},
                    {
                        "role": "user",
                        "content": (
                            self._replace_reference_period_expression(
                                self.story.template.prompt_text
                            )
                        ),
                    },
                ]

                # Generate response
            response = self.ai_client.chat.completions.create(
                model=self.story.ai_model,
                messages=messages,
                temperature=self.story.template.temperature,
                max_tokens=3000,
            )
            self.story.content = (response.choices[0].message.content or "").strip()
            self.story.prompt_text = messages
            if not self.story.content:
                self.logger.warning(
                    f"Empty content generated for story {self.story.template.title}"
                )
            return bool(self.story.content)

        except Exception as e:
            self.logger.error(f"Error generating report text with OpenAI: {e}")
            return None

    def _generate_summary(self, kind: str) -> Optional[str]:
        try:
            # Kind-specific instructions
            if kind == "title":
                system = "You are a concise editorial assistant producing sharp, data-driven insight titles"
                user_instruction = (
                    self._replace_reference_period_expression(self.story.template.title_prompt)
                    if self.story.template.title_prompt
                    else (
                        f""".Write a single-line analytical headline (max 10–12 words). 
                    Prefer compact forms over wordiness. 
                    Keep neutral, factual tone. 
                    Return only the title."""
                    )
                )
                max_tokens = 60
                temperature = min(
                    max(getattr(self.story.template, "temperature", 0.5), 0.2), 1.0
                )
            else:  # lead (default)
                system = "Generate a concise one- or two-sentence summary of the provided insight text."
                user_instruction = (
                    self.story.template.lead_prompt
                    if self.story.template.lead_prompt
                    else "Summarize the following insight text in one or two clear sentences."
                )
                max_tokens = 200
                temperature = getattr(self.story.template, "temperature", 0.2)

            # Construct messages
            messages = [
                {
                    "role": "system",
                    "content": f"{system}\n\n{LLM_FORMATTING_INSTRUCTIONS}",
                },
                {
                    "role": "user",
                    "content": f"{user_instruction}\n\nInsight text:\n\n{self.story.content}",
                },
            ]

            response = self.ai_client.chat.completions.create(
                model=self.story.ai_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            return response.choices[0].message.content.strip()

        except Exception as e:
            self.logger.error(f"Error generating {kind} with OpenAI: {e}")
            return None

    def generate_title(self) -> Optional[str]:
        """Generate title using the unified LLM helper"""
        self.logger.info("Generating title...")
        # Generate lead (summary) and an engaging title using the unified LLM helper

        if self.story.template.create_title:
            self.story.title = self._generate_summary(kind="title")
        else:
            self.story.title = self._replace_reference_period_expression(
                self.story.template.default_title
            )
        return bool(self.story.title)

    def generate_lead(self) -> Optional[str]:
        """
        Generic LLM helper to produce different short outputs.
        kind: "lead" -> one- or two-sentence summary
              "title" -> single-line engaging analytical title
        """
        self.logger.info("Generating lead...")
        if self.template.create_lead and self.template.default_lead:
            self.story.summary = self._replace_reference_period_expression(self.template.default_lead)
        elif self.template.create_lead:
            self.story.summary = self._generate_summary(kind="lead")
        else:
            self.story.summary = self._replace_reference_period_expression(
                self.story.template.summary
            )
