"""
Story Processing Classes
Contains the migrated Story class and related functionality from data_news.py
"""

import uuid
import json
import logging
import calendar
import pandas as pd
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, Tuple
from decimal import Decimal
from enum import Enum
from django.db import models
from django.conf import settings
from openai import OpenAI
from ..visualizations.altair_charts import generate_chart
from django.db.models import Max
from reports.services.database_client import DjangoPostgresClient
from reports.services.utils import ensure_date
from reports.models.story_context import StoryTemplateContext
from reports.models.story_log import StoryLog
from reports.models.story_context import StoryTemplate
from reports.models.story import Story
from reports.models.story_table import StoryTable
from reports.models.graphic import Graphic
from dateutil.relativedelta import relativedelta


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
        return super().default(obj)


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


class ReferencePeriod(Enum):
    """Enum for reference period types"""

    DAILY = 35
    MONTHLY = 36
    SEASONAL = 37
    YEARLY = 38
    ALLTIME = 39
    DECADAL = 44  # For backward compatibility
    IRREGULAR = 56  # For backward compatibility
    WEEKLY = 70  # For backward compatibility

    @classmethod
    def get_name(cls, value: int) -> str:
        """Get the name of the period from its value"""
        for period in cls:
            if period.value == value:
                return period.name.lower()
        return "unknown"


class StoryProcessor:
    """
    Migrated Story class from data_news.py
    Handles story generation, AI integration, and database operations
    """

    def __init__(
        self,
        template: StoryTemplate = None,
        published_date: date = None,
        force_generation: bool = False,
        story: Story = None,
    ):
        # verify if either template or story is provided
        if not template and not story:
            raise ValueError("Either template or story must be provided")
        # verify that published_date is provided if template is provided
        if template and not published_date:
            raise ValueError("published_date must be provided if template is provided")

        self.dbclient = DjangoPostgresClient()
        self.force_generation = force_generation
        if story:
            self.story = story
            template = story.template
            published_date = story.published_date
            self.most_recent_day = self._get_most_recent_day(published_date, template)
            self.season, self.season_year = self._get_season(published_date, template)
            reference_period_start = story.reference_period_start
            reference_period_end = story.reference_period_end
        else:
            self.most_recent_day = self._get_most_recent_day(published_date, template)
            if self.most_recent_day:
                reference_period_start, reference_period_end = (
                    self._get_reference_period(self.most_recent_day, template)
                )
                self.season, self.season_year = self._get_season(
                    reference_period_start, template
                )
                self.story = (
                    Story.objects.filter(
                        template=template,
                        reference_period_start=reference_period_start,
                        reference_period_end=reference_period_end,
                    ).first()
                    or Story()  # creates a new, empty instance if no match
                )
                if self.story.id is None:
                    self.story.template = template

                    (
                        self.story.reference_period_start,
                        self.story.reference_period_end,
                    ) = self._get_reference_period(published_date, template)

                self.story.ai_model = getattr(settings, "DEFAULT_AI_MODEL", "gpt-4o")
                self.story.published_date = published_date

        self.logger = logging.getLogger(
            f"StoryProcessor.{template.id} {template.title}"
        )
        self.reference_period = template.reference_period.id
        self.year = self.story.reference_period_start.year
        self.month = self.story.reference_period_start.month
        self.reference_period_expression = self._get_reference_period_expression()
        self.last_reference_period_start_date = self._get_last_published_date()
        self.is_data_based = StoryTemplateContext.objects.filter(
            story_template=template
        ).exists()

    def _get_reference_period_expression(self) -> str:
        """
        Generates a human-readable string representation of the reference period for the story.

        Returns:
            str: A formatted string describing the reference period, which may be:
                - "YYYY-MM-DD" for daily periods,
                - "Month YYYY" for monthly periods,
                - "Season YYYY" for seasonal periods,
                - "YYYY" for yearly periods,
                - "All Time" for all-time periods,
                - "Decadal YYYYs" for decadal periods,
                or an empty string if the reference period does not match any known type.
        """
        if self.reference_period == ReferencePeriod.DAILY.value:
            return self.story.reference_period_start.strftime("%Y-%m-%d")
        elif self.reference_period == ReferencePeriod.WEEKLY.value:
            return f'{self.story.reference_period_start.strftime("%Y-%m-%d")} - {self.story.reference_period_end.strftime("%Y-%m-%d")}'
        elif self.reference_period == ReferencePeriod.MONTHLY.value:
            month_id = self.story.reference_period_start.month
            return f"{calendar.month_name[month_id]} {self.year}"
        elif self.reference_period == ReferencePeriod.SEASONAL.value:
            return f"{self._season_name()} {self.season_year}"
        elif self.reference_period == ReferencePeriod.YEARLY.value:
            return str(self.year)
        elif self.reference_period == ReferencePeriod.ALLTIME.value:
            return "All Time"
        elif self.reference_period == ReferencePeriod.DECADAL.value:
            return f"Decadal {self.year // 10 * 10}s"
        return ""

    def _replace_reference_period_expression(self, expression: str) -> str:
        """Replace reference period expression in SQL command"""
        result = expression.replace(
            ":reference_period_start", str(self.story.reference_period_start)
        )
        result = result.replace(
            ":reference_period_end", str(self.story.reference_period_end)
        )
        result = result.replace(
            ":reference_period_month", str(calendar.month_name[self.month])
        )
        result = result.replace(":reference_period_year", str(self.year))
        result = result.replace(":reference_period_previous_year", str(self.year - 1))
        result = result.replace(":reference_period_season", self._season_name())
        result = result.replace(":reference_period", self.reference_period_expression)
        result = result.replace(
            ":published_date", self.story.published_date.strftime("%Y-%m-%d")
        )
        return result

    def story_is_due(self) -> bool:
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

            def get_publish_conditions_result() -> bool:
                """
                Checks whether all publish conditions defined in the story template are met.

                Returns:
                    bool: True if all conditions are met, False otherwise.
                """
                if self.story.template.publish_conditions:
                    cmd = self._replace_reference_period_expression(
                        self.story.template.publish_conditions
                    )
                    params = self._get_sql_command_params(cmd)
                    df = self.dbclient.run_query(
                        self.story.template.publish_conditions, params
                    )
                    return df.iloc[0, 0] == 1
                else:
                    return True  # no conditions defined, so we assume they are met

            has_data = True
            story_exists = False
            publish_conditions_met = True
            result = False

            if self.story.template.has_data_sql:
                params = self._get_sql_command_params(self.story.template.has_data_sql)
                df = self.dbclient.run_query(self.story.template.has_data_sql, params)
                has_data = df.iloc[0, 0] > 0
            if self.force_generation:
                result = has_data
            elif not self.is_data_based:
                story_exists = Story.objects.filter(
                    template=self.story.template,
                    reference_period_start=self.story.reference_period_start,
                ).exists()
                result = not story_exists
            else:
                story_exists = Story.objects.filter(
                    template=self.story.template,
                    reference_period_start=self.story.reference_period_start,
                ).exists()
                publish_conditions_met = get_publish_conditions_result()
                result = has_data and not story_exists and publish_conditions_met
            # print(f"Story is due: {is_due}, has_data: {has_data}, date_is_due: {date_is_due}, publish_conditions_met: {publish_conditions_met}, regular_due_date: {regular_due_date}, last_published_date: {self.last_reference_period_start_date}")
            return result

        except Exception as e:
            self.logger.error(f"Error checking if story is due: {e}")
            return False

    def generate_table(self, table: StoryTable):
        table_template = table.table_template
        sql_cmd = table_template.sql_command
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
        table_templates = self.story.template.story_template_tables.all()
        self.logger.info(f"Found {table_templates.count()} table templates to process")

        for table_template in table_templates:
            tables = StoryTable.objects.filter(
                story=self.story, table_template=table_template
            )
            if not tables.exists():
                table = StoryTable(story=self.story, table_template=table_template)
            else:
                if tables.count() > 1:
                    # delete all but the last table
                    for t in tables[:-1]:
                        t.delete()
                table = tables.first()
            self.generate_table(table)

    def generate_graphic(self, graphic: Graphic):
        try:
            graphic_template = graphic.graphic_template
            sql_command = graphic_template.sql_command
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
                f"Initializing story generation for {self.story.template.title} ({self.story.published_date.strftime('%Y-%m-%d')})"
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
                self.dbclient.run_action_query(self.story.template.post_publish_command)

            self.logger.info("Story generation completed successfully")
            return True
        except Exception as e:
            self.logger.error(f"Error generating story: {e}")
            import traceback

            self.logger.error(traceback.format_exc())
            return False

    def _get_most_recent_day(self, published_date, template) -> Optional[datetime]:
        """
        Retrieves the most recent day related to the current story from the database.
        Executes a SQL query defined in the template to fetch the most recent date,
        using the story's published_date as a parameter. Returns the date as a
        pandas.Timestamp if available, otherwise returns None.
        Returns:
            Optional[datetime]: The most recent day as a datetime object, or None if
            not found or if an error occurs during the query.
        """

        most_recent_day_sql = template.most_recent_day_sql
        if most_recent_day_sql:
            try:
                params = {"published_date": published_date}
                df = self.dbclient.run_query(most_recent_day_sql, params)
                return (
                    pd.to_datetime(df.iloc[0, 0])
                    if not df.empty and df.iloc[0, 0] is not None
                    else None
                )
            except Exception as e:
                return None
        else:
            return None

    def _get_last_published_date(self) -> Optional[datetime]:
        """Get the last published date for this template"""
        return Story.objects.filter(template=self.story.template).aggregate(
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
        self, published_date: datetime, template: StoryTemplate
    ) -> Tuple[datetime, datetime]:
        """Get the reference period start and end dates relative to published_date.

        This consolidates forward/backward logic: compute the period containing an
        anchor date (most_recent_day if available, else published_date) and then
        shift that period by -1 (backward) or +1 (forward) depending on
        template.period_direction.
        Returns date objects (period_start, period_end).
        """

        def to_datetime_obj(d):
            if d is None:
                return None
            if isinstance(d, pd.Timestamp):
                return d.to_pydatetime()
            if isinstance(d, date) and not isinstance(d, datetime):
                return datetime.combine(d, datetime.min.time())
            if isinstance(d, datetime):
                return d
            try:
                return pd.to_datetime(d).to_pydatetime()
            except Exception:
                return None

        anchor = self.most_recent_day if self.most_recent_day is not None else published_date
        anchor_dt = to_datetime_obj(anchor) or to_datetime_obj(published_date)

        # Determine the base period that contains anchor_dt
        if template.reference_period_id in (ReferencePeriod.DAILY.value, ReferencePeriod.IRREGULAR.value):
            base_start = anchor_dt
            base_end = anchor_dt
            unit = 'days'
        elif template.reference_period_id == ReferencePeriod.WEEKLY.value:
            # week starting on Monday that contains anchor
            week_start = anchor_dt - pd.DateOffset(days=anchor_dt.weekday())
            base_start = week_start
            base_end = week_start + pd.DateOffset(days=6)
            unit = 'weeks'
        elif template.reference_period_id == ReferencePeriod.MONTHLY.value:
            base_start = datetime(anchor_dt.year, anchor_dt.month, 1)
            base_end = datetime(anchor_dt.year, anchor_dt.month, calendar.monthrange(anchor_dt.year, anchor_dt.month)[1])
            unit = 'months'
        elif template.reference_period_id == ReferencePeriod.SEASONAL.value:
            season_idx, season_year = self._get_season(anchor_dt, template)
            sm, sd = season_dates[season_idx][0]
            em, ed = season_dates[season_idx][1]
            start_year = season_year
            end_year = start_year if em >= sm else start_year + 1
            base_start = datetime(start_year, sm, sd)
            base_end = datetime(end_year, em, ed)
            base_end += pd.DateOffset(days=1)
            unit = 'season'
        elif template.reference_period_id == ReferencePeriod.YEARLY.value:
            base_start = datetime(anchor_dt.year, 1, 1)
            base_end = datetime(anchor_dt.year, 12, 31)
            unit = 'years'
        else:
            # fallback: single-day period at anchor
            base_start = anchor_dt
            base_end = anchor_dt
            unit = 'days'

        # Decide shift direction: backward -> -1, else +1
        direction = getattr(template, 'period_direction', None)
        dir_val = 'backward' if direction is None else str(direction.value).lower()
        shift = 0 if dir_val == 'backward' else 1

        # Apply the shift
        if unit == 'days':
            period_start = base_start + pd.DateOffset(days=shift)
            period_end = base_end + pd.DateOffset(days=shift)
        elif unit == 'weeks':
            period_start = base_start + pd.DateOffset(days=7 * shift)
            period_end = base_end + pd.DateOffset(days=7 * shift)
        elif unit == 'months':
            period_start = base_start + relativedelta(months=shift)
            # recompute end as last day of the target month
            period_end = datetime(period_start.year, period_start.month, calendar.monthrange(period_start.year, period_start.month)[1])
        elif unit == 'season':
            # compute new season index/year
            cur_season, cur_season_year = self._get_season(anchor_dt, template)
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
        elif unit == 'years':
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

            cmd = context_item.sql_command
            params = self._get_sql_command_params(cmd)
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

        if "%(period_start_date)s" in cmd:
            params["period_start_date"] = (
                self.story.reference_period_start.strftime("%Y-%m-%d")
                if self.story.reference_period_start
                else self.story.published_date.strftime("%Y-%m-%d")
            )
        if "%(published_date)s" in cmd:
            params["published_date"] = self.story.published_date.strftime("%Y-%m-%d")
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
            # Get OpenAI API key from settings
            api_key = getattr(settings, "OPENAI_API_KEY", None)
            if not api_key:
                self.logger.error("OpenAI API key not configured")
                return None

            # Initialize OpenAI client
            client = OpenAI(api_key=api_key)

            if self.is_data_based:
                messages = [
                    {
                        "role": "system",
                        "content": f"{self.story.template.prompt_text}\n\n{LLM_FORMATTING_INSTRUCTIONS}",
                    },
                    {
                        "role": "user",
                        "content": (
                            "Below is the statistical data in JSON format.\n\n"
                            "```json\n" + self.story.context_values + "\n```"
                        ),
                    },
                ]
            else:
                messages = [
                    {
                        "role": "system", 
                        "content": self.story.template.system_prompt
                    },
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
            response = client.chat.completions.create(
                model=self.story.ai_model,
                messages=messages,
                temperature=self.story.template.temperature,
                max_tokens=3000,
            )
            self.story.content = (response.choices[0].message.content or "").strip()
            self.story.prompt_text = messages[1]
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
            api_key = getattr(settings, "OPENAI_API_KEY", None)
            if not api_key:
                self.logger.error("OpenAI API key not configured")
                return None

            client = OpenAI(api_key=api_key)
            # Kind-specific instructions
            if kind == "title":
                system = "You are a concise editorial assistant producing sharp, data-driven insight titles"
                user_instruction = (
                    self.story.template.title_prompt
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

            response = client.chat.completions.create(
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
        if self.story.template.create_lead:
            self.story.summary = self._generate_summary(kind="lead")
        else:
            self.story.summary = self._replace_reference_period_expression(
                self.story.template.summary
            )
