"""
Story Processing Classes
Contains the migrated Story class and related functionality from data_news.py
"""

import uuid
import altair as alt
import json
import logging
import calendar
import pandas as pd
from datetime import datetime, timezone, date, timedelta
from dateutil.relativedelta import relativedelta
from typing import Optional, Dict, Any, Tuple
from decimal import Decimal
from enum import Enum
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from openai import OpenAI
from ..visualizations.altair_charts import generate_chart

from django.db import transaction
from reports.services.database_client import DjangoPostgresClient
from reports.services.utils import SQL_TEMPLATES
from reports.models import (
    StoryTemplatePeriodOfInterestValues,
    StoryTemplateContext,
    StoryLog,
    StoryTemplate,
    Story,
    StoryTemplateTable,
    StoryTemplateGraphic,
    StoryTable,
    Graphic,
)

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
    IRREGULAR = 57  # For backward compatibility

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
        self, template: StoryTemplate, published_date: date, force_generation: bool = False
    ):
        self.logger = logging.getLogger(
            f"StoryProcessor.{template.title}"
        )
        self.story = Story()
        self.template = template  # Now a StoryTemplate model instance
        self.story.published_date = published_date
        self.most_recent_day = self._get_most_recent_day()
        self.story.template = template
        self.story.prompt_text = self.template.prompt_text
        self.story.reference_period_start, self.story.reference_period_end = (
            self._get_reference_period()
        )
        self.force_generation = force_generation
        self.dbclient = DjangoPostgresClient()
        self.season, self.season_year = self._get_season()
        self.reference_period = template.reference_period.id
        self.year = self.story.reference_period_start.year
        self.month = self.story.reference_period_start.month
        self.reference_period_expression = self._get_reference_period_expression()
        self.last_published_date = self._get_last_published_date()
        self.story.reference_values = self._init_reference_values()
        self.story.context_values = self._get_context_data()
        
        self.story.title = self._replace_reference_period_expression(template.title)
        self.story.ai_model = getattr(settings, "DEFAULT_AI_MODEL", "gpt-4o")
        
        self.story.content = None  # Will be filled when story is generated
        self.story.summary = None  # Will be filled when story is generated
        self.tables = []
        self.graphics = []
        
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
        result = result.replace(":reference_period_end", str(self.story.reference_period_end))
        result = result.replace(
            ":reference_period_month", str(calendar.month_name[self.month])
        )
        result = result.replace(":reference_period_year", str(self.year))
        result = result.replace(":reference_period_season", self._season_name())
        result = result.replace(":reference_period", self.reference_period_expression)
        return result

    def story_is_due(self) -> bool:
        """Check if the story should be generated"""
        try:

            def get_publish_conditions_result() -> bool:
                """
                Checks whether all publish conditions defined in the story template are met.

                Returns:
                    bool: True if all conditions are met, False otherwise.
                """
                if self.publish_conditions:
                    params = self._get_sql_command_params(self.publish_conditions)
                    df = self.dbclient.run_query(self.publish_conditions, params)
                    return df.iloc[0, 0] == 1
                else:
                    return True  # no conditions defined, so we assume they are met

            if self.has_data_sql:
                params = self._get_sql_command_params(self.has_data_sql)
                df = self.dbclient.run_query(self.has_data_sql, params)
                has_data = df.iloc[0]["cnt"] > 0
            else:
                has_data = True

            if (
                self.template.reference_period_id == ReferencePeriod.MONTHLY.value
            ):  # monthly
                regular_due_date = (
                    self.story.reference_period_start + relativedelta(months=1)
                ).date()
            elif (
                self.template.reference_period_id == ReferencePeriod.SEASONAL.value
            ):  # seasonal
                season = month_to_season[self.month]
                month, day = season_dates[season][0]
                regular_due_date = date(
                    self.story.reference_period_start.year, month, day
                )  # ✅ use `date(...)`
            elif (
                self.template.reference_period_id == ReferencePeriod.YEARLY.value
            ):  # yearly
                regular_due_date = self.story.reference_period_start.replace(day=1, month=1)
            else:
                regular_due_date = self.story.reference_period_start

            if self.force_generation:
                is_due = has_data
                date_is_due = True
                publish_conditions_met = True
            else:
                # check if the regular due date has passed without publishing the story
                date_is_due = (
                    True
                    if self.last_published_date is None
                    else regular_due_date >= self.last_published_date
                )
                publish_conditions_met = get_publish_conditions_result()
                is_due = has_data and date_is_due and publish_conditions_met
            # print(f"Story is due: {is_due}, has_data: {has_data}, date_is_due: {date_is_due}, publish_conditions_met: {publish_conditions_met}, regular_due_date: {regular_due_date}, last_published_date: {self.last_published_date}")
            return is_due

        except Exception as e:
            self.logger.error(f"Error checking if story is due: {e}")
            return False

    def generate_tables(self) -> list:
        """Generate tables for the story"""
        tables = StoryTemplateTable.objects.filter(story_template=self.template)  # Use StoryTemplateTable
        for table in tables:
            sql_cmd = table.sql_command
            params = self._get_sql_command_params(sql_cmd)
            try:
                df = self.dbclient.run_query(sql_cmd, params)
                data = df.to_dict(orient="records")
                story_table = StoryTable.objects.create(
                    story=self.story,
                    title = self._replace_reference_period_expression(table.title),
                    table_template=table,
                    data=json.dumps(data, indent=2, ensure_ascii=False, cls=DecimalEncoder),
                    sort_order=table.sort_order,
                )
            except Exception as e:
                self.logger.error(f"Error generating table {table.id}: {e}")
                continue

    def generate_graphics(self) -> list:
        """Generate graphics for the story template and save them directly to database"""
        try:
            graphic_templates = StoryTemplateGraphic.objects.filter(
                story_template_id=self.template.id
            ).order_by('sort_order')
            
            self.logger.info(f"Found {graphic_templates.count()} graphic templates to process")
            
            for template in graphic_templates:
                try:
                    # Get SQL command
                    sql_command = template.sql_command
                    if not sql_command:
                        self.logger.warning(f"Empty SQL command for graphic template: {template.title}")
                        continue
                    
                    # Replace parameters in SQL
                    params = self._get_sql_command_params(sql_command)
                    self.logger.info(f"Executing SQL for graphic: {template.title}")
                    
                    # Execute SQL to get data
                    data = self.dbclient.run_query(sql_command, params)
                    
                    if data is None or len(data) == 0:
                        self.logger.warning(f"No data returned for graphic template: {template.title}")
                        continue
                    
                    # Generate unique chart ID
                    chart_id = f"chart-{template.id}-{uuid.uuid4().hex[:8]}"
                    
                    # Use settings from template
                    settings = template.settings
                    
                    # If settings are empty or invalid, create default settings
                    if not settings or not isinstance(settings, dict):
                        settings = {
                            'type': template.graphic_type.lower(),
                            'title': template.title
                        }
                        
                        # Generate default x/y settings from data columns
                        if isinstance(data, pd.DataFrame) and not data.empty:
                            columns = data.columns.tolist()
                            if len(columns) >= 2:
                                settings['x'] = columns[0]
                                settings['y'] = columns[1]
                                if len(columns) >= 3 and template.graphic_type.lower() in ['bar_stacked', 'area', 'scatter']:
                                    settings['color'] = columns[2]
                
                    # Generate chart HTML
                    self.logger.info(f"Generating chart for: {template.title}")
                    chart_html = generate_chart(
                        data=data,
                        settings=settings,
                        chart_id=chart_id
                    )
                    
                    # Create and save Graphic object directly to database
                    story_graphic = Graphic.objects.create(
                        story=self.story,
                        title=self._replace_reference_period_expression(template.title),
                        content_html=chart_html,
                        data=json.dumps(data.to_dict(orient="records"), indent=2, ensure_ascii=False, cls=DecimalEncoder),
                        sort_order=template.sort_order,
                        graphic_template=template
                    )
                    self.logger.info(f"Successfully generated and saved graphic: {template.title} {story_graphic.id}")
                    
                except Exception as e:
                    self.logger.error(f"Error generating graphic '{template.title}': {str(e)}")
                    import traceback
                    self.logger.error(traceback.format_exc())
            
        except Exception as e:
            self.logger.error(f"Error in generate_graphics: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return []

    def generate_story(self) -> bool:
        """Generate the complete story"""
        try:
            self.logger.info(
                f"Initializing story generation for {self.template.title} ({self.story.published_date.strftime('%Y-%m-%d')})"
            )
            
            # Generate content
            self.logger.info("Generating story content...")
            self.story.content = self._generate_report_text()
            
            if not self.story.content:
                self.logger.warning(f"Empty content generated for story {self.template.title}")
                return False
            
            self.logger.info("Generating summary...")
            self.story.summary = self._generate_lead(self.story.content)
            self.logger.info("Saving story to database...")
            try:
                self.story.full_clean()  # This validates the model
            except Exception as validation_error:
                self.logger.error(f"Validation error: {validation_error}")
                # Print all fields and their values for debugging
                for field in self.story._meta.fields:
                    self.logger.info(f"Field '{field.name}': {getattr(self.story, field.name, None)}")
                return False
                
            # Save with transaction
            # with transaction.atomic():
        
            self.story.save()
            self.logger.info("Generating tables...")
            self.generate_tables()                
            self.logger.info("Generating graphics...")
            self.graphics = self.generate_graphics()
            self._save_log_record()

            # Execute post-publish commands
            if self.template.post_publish_command:
                self.logger.info("Executing post-publish command...")
                self.dbclient.run_action_query(self.post_publish_command)

            self.logger.info("Story generation completed successfully")
            return True
        except Exception as e:
            self.logger.error(f"Error generating story: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False

    

    def _get_most_recent_day(self) -> Optional[datetime]:
        """
        Retrieves the most recent day related to the current story from the database.
        Executes a SQL query defined in the template to fetch the most recent date,
        using the story's published date as a parameter. Returns the date as a
        pandas.Timestamp if available, otherwise returns None.
        Returns:
            Optional[datetime]: The most recent day as a datetime object, or None if
            not found or if an error occurs during the query.
        """
        
        most_recent_day_sql = self.template.most_recent_day_sql
        if most_recent_day_sql:
            try:
                params = {"published_date": self.story.published_date}
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
        try:
            # Use Django ORM to get the maximum publish_date for this template
            last_log = StoryLog.objects.filter(
                story__template=self.template  # Use 'story_template' instead of 'story_template_id'
            ).aggregate(last_published_date=models.Max("publish_date"))

            return last_log["last_published_date"]
        except Exception as e:
            self.logger.error(f"Error getting last published date: {e}")
            return None

    def _get_season(self) -> Tuple[int, int]:
        """Get season and season year based on reference period"""
        if self.most_recent_day:
            day = self.most_recent_day
        else:
            day = self.story.published_date - timedelta(days=1)

        if self.template.reference_period_id == ReferencePeriod.DAILY.value:  # daily
            season = month_to_season[day.month]
        elif (
            self.template.reference_period_id == ReferencePeriod.MONTHLY.value
        ):  # monthly
            month = day.month - 1 if day.month > 1 else 12
            season = month_to_season[month]
        elif (
            self.template.reference_period_id == ReferencePeriod.SEASONAL.value
        ):  # seasonal
            season = month_to_season[self.story.published_date.month] - 1
            if season < 1:
                season = 4
        else:
            season = None

        season_year = self.story.published_date.year
        return season, season_year

    def _get_reference_period(self) -> Tuple[datetime, datetime]:
        """Get the reference period start and end dates"""
        if self.template.reference_period_id in (
            ReferencePeriod.DAILY.value,
            ReferencePeriod.IRREGULAR.value,
        ):  # daily, irregular
            # Use most_recent_day if available, otherwise use published_date minus 1 day
            if self.most_recent_day:
                period_start = self.most_recent_day
                period_end = self.most_recent_day
            else:
                fallback_date = self.story.published_date - timedelta(days=1)
                period_start = datetime.combine(fallback_date, datetime.min.time())
                period_end = datetime.combine(fallback_date, datetime.min.time())
        elif (
            self.template.reference_period_id == ReferencePeriod.MONTHLY.value
        ):  # monthly
            if self.story.published_date.month > 1:
                month = self.story.published_date.month - 1
                year = self.story.published_date.year
            else:
                month = 12
                year = self.story.published_date.year - 1
            period_start = datetime(year, month, 1)
            period_end = datetime(year, month, calendar.monthrange(year, month)[1])
        elif (
            self.template.reference_period_id == ReferencePeriod.SEASONAL.value
        ):  # seasonal
            start_month, start_day = season_dates[self.season][0]
            end_month, end_day = season_dates[self.season][1]
            start_year = (
                self.story.published_date.year - 1
                if self.season == 4
                else self.story.published_date.year
            )
            period_start = datetime(start_year, start_month, start_day)
            end_year = self.story.published_date.year
            period_end = datetime(end_year, end_month, end_day)
            period_end += pd.DateOffset(days=1)
        elif (
            self.template.reference_period_id == ReferencePeriod.YEARLY.value
        ):  # yearly
            year = self.story.published_date.year - 1
            period_start = datetime(year, 1, 1)
            period_end = period_start + pd.DateOffset(years=1)
        else:
            period_start = None
            period_end = None
            self.logger.warning(
                f"Unknown reference period: {self.template['reference_period_id']}"
            )

        return period_start, period_end

    def _season_name(self) -> str:
        """Get season name from season number"""
        season_names = {1: "Spring", 2: "Summer", 3: "Fall", 4: "Winter"}
        return season_names.get(self.season, "Unknown Season")

    def _init_reference_values(self) -> Dict[str, Any]:
        """Initialize measured values dictionary"""
        my_dict = {
            "period_of_interest": {
                "start": (
                    self.story.reference_period_start.strftime("%Y-%m-%d")
                    if self.story.reference_period_start
                    else None
                ),
                "end": (
                    self.story.reference_period_end.strftime("%Y-%m-%d")
                    if self.story.reference_period_end
                    else None
                ),
                "label": None,
                "type": None,
            }
        }

        # Set period label based on reference period type
        if self.story.template.reference_period_id == ReferencePeriod.DAILY.value:  # daily
            my_dict["period_of_interest"]["label"] = (
                self.story.reference_period_start.strftime("%Y-%m-%d")
            )
            my_dict["period_of_interest"]["type"] = "daily"
        elif (
            self.template.reference_period_id == ReferencePeriod.MONTHLY.value
        ):  # monthly
            my_dict["period_of_interest"][
                "label"
            ] = f'{self.story.reference_period_start.strftime("%B")} {self.story.reference_period_start.strftime("%Y")}'
            my_dict["period_of_interest"]["type"] = "monthly"
        elif (
            self.template.reference_period_id == ReferencePeriod.SEASONAL.value
        ):  # seasonal
            my_dict["period_of_interest"][
                "label"
            ] = f"{self._season_name()} {self.season_year}"
            my_dict["period_of_interest"]["type"] = "seasonally"

        my_dict["measured_values"] = self._get_period_of_interest_values()
        result = json.dumps(my_dict, indent=2, ensure_ascii=False, cls=DecimalEncoder)
        return result

    def _get_period_of_interest_values(self) -> Dict[str, Any]:
        """Get reference values for the story"""
        result = {}
        try:
            # Use Django ORM to fetch the period of interest values
            period_values = (
                StoryTemplatePeriodOfInterestValues.objects.filter(
                    story_template=self.template
                )
                .order_by("sort_order")
            )

            for period_value in period_values:
                cmd = period_value.sql_command
                params = self._get_sql_command_params(cmd)

                try:
                    value_df = self.dbclient.run_query(cmd, params)
                    if len(value_df) == 0:
                        result[period_value.title] = (
                            "No data available for this period."
                        )
                    elif len(value_df) > 1:
                        result[period_value.title] = value_df.to_dict(
                            orient="records"
                        )
                    else:
                        result[period_value.title] = value_df.iloc[0].to_dict()
                except Exception as sql_error:
                    self.logger.error(
                        f"SQL execution error for '{period_value.title}': {sql_error}"
                    )
                    self.logger.error(f"SQL command: {repr(cmd)}")
                    self.logger.error(f"Parameters: {params}")
                    result[period_value.title] = (
                        f"Error executing query: {sql_error}"
                    )

        except Exception as e:
            self.logger.error(f"Error getting reference values: {e}")

        return result

    def _get_context_data(self) -> dict:
        """File "/home/lcalm/Work/Dev/data_news_agent/src/data_news.py", line 329, in get_context_data
        Retrieves the comparisons for the story from the database.
        This method queries the database for the comparisons defined in the story configuration.

        Returns:
            dict: A dictionary containing the comparisons for the story.
        """
        result = {}
        # Use Django ORM to fetch the context data
        context_data = (
            StoryTemplateContext.objects.filter(story_template_id=self.template.id)
            .order_by("key")
        )

        for context_item in context_data:
            if context_item.key not in result:
                result[context_item.key] = {}
            node = result[context_item.key]

            cmd = context_item.sql_command
            params = self._get_sql_command_params(cmd)
            df = self.dbclient.run_query(cmd, params)
            if df.empty:
                self.logger.warning(
                    f"No data found for context key: {context_item.key}"
                )
            elif len(df) > 1:
                node[context_item.description] = df.to_dict(orient="records")
            else:
                df = df.iloc[0].to_frame().T
                node[context_item.description] = df.to_dict(orient="records")

        result = json.dumps({"context_data": result}, indent=2, ensure_ascii=False, cls=DecimalEncoder)
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

    def _generate_report_text(self) -> Optional[str]:
        """Generate story text using OpenAI API"""
        try:
            # Get OpenAI API key from settings
            api_key = getattr(settings, "OPENAI_API_KEY", None)
            if not api_key:
                self.logger.error("OpenAI API key not configured")
                return None

            # Initialize OpenAI client
            client = OpenAI(api_key=api_key)

            # Prepare the payload with both measured_values and context_data (matching original implementation)
            payload = {
                "measured_values": self.story.reference_values,
                "context_data": self.story.context_values,
            }

            messages = [
                {
                    "role": "system",
                    "content": f"{self.template.prompt_text}\n\n{LLM_FORMATTING_INSTRUCTIONS}",
                },
                {
                    "role": "user",
                    "content": (
                        "Below is the statistical data in JSON format.\n\n"
                        "```json\n"
                        + json.dumps(
                            payload, indent=2, ensure_ascii=False, cls=DecimalEncoder
                        )
                        + "\n```"
                    ),
                },
            ]

            # Generate response
            response = client.chat.completions.create(
                model=self.story.ai_model,
                messages=messages,
                temperature=self.template.temperature,
                max_tokens=2000,
            )

            return response.choices[0].message.content

        except Exception as e:
            self.logger.error(f"Error generating report text with OpenAI: {e}")
            return None

    def _generate_lead(self, insight_text: str) -> Optional[str]:
        """Generate lead (summary) using OpenAI API based on insight text"""
        try:
            # Get OpenAI API key from settings
            api_key = getattr(settings, "OPENAI_API_KEY", None)
            if not api_key:
                self.logger.error("OpenAI API key not configured")
                return None

            # Initialize OpenAI client
            client = OpenAI(api_key=api_key)
            # Prepare the prompt for summary generation
            summary_prompt = (
                "Summarize the following insight text in one or two sentences:\n\n"
                + insight_text
            ).strip()
            messages = [
                {
                    "role": "system",
                    "content": "Generate a concise summary of the provided insight text.",
                },
                {
                    "role": "user",
                    "content": summary_prompt,
                },
            ]

            # Generate response
            response = client.chat.completions.create(
                model=self.story.ai_model,
                messages=messages,
                temperature=self.template.temperature,
                max_tokens=2000,
            )

            return response.choices[0].message.content

        except Exception as e:
            self.logger.error(f"Error generating lead with OpenAI: {e}")
            return None

