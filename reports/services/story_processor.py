"""
Story Processing Classes
Contains the migrated Story class and related functionality from data_news.py
"""

from email import utils
import numpy as np
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
from sqlalchemy import column
from ..visualizations.altair_charts import generate_chart

from django.db import transaction
from reports.services.database_client import DjangoPostgresClient
from reports.services.utils import SQL_TEMPLATES, ensure_date
from reports.models import (
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
        self, template: StoryTemplate, published_date: date, force_generation: bool = False
    ):
        print(f"{template.id} {template.title}")
        self.logger = logging.getLogger(
            f"StoryProcessor.{template.title}"
        )
        self.dbclient = DjangoPostgresClient()
        self.most_recent_day = self._get_most_recent_day(published_date, template)
        self.season, self.season_year = self._get_season(published_date, template)
        reference_period_start, reference_period_end = (
            self._get_reference_period(published_date, template)
        )
        
        self.story = (
            Story.objects
            .filter(
                template=template,
                reference_period_start=reference_period_start,
                reference_period_end=reference_period_end
            )
            .first()
            or Story()  # creates a new, empty instance if no match
        )
        if self.story.id is None:
            self.story.template = template
            
            self.story.reference_period_start, self.story.reference_period_end = (
                self._get_reference_period(published_date, template)
            )
        
        self.story.published_date = published_date
        self.story.prompt_text = self.story.template.prompt_text
        self.force_generation = force_generation
        
        self.reference_period = template.reference_period.id
        self.year = self.story.reference_period_start.year
        self.month = self.story.reference_period_start.month
        self.reference_period_expression = self._get_reference_period_expression()
        self.last_published_date = self._get_last_published_date()
        self.is_data_based = StoryTemplateContext.objects.filter(story_template=template).exists()
        if self.is_data_based:
            self.story.context_values = self._get_context_data()

        self.story.ai_model = getattr(settings, "DEFAULT_AI_MODEL", "gpt-4o")
        
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
        result = result.replace(":reference_period_end", str(self.story.reference_period_end))
        result = result.replace(
            ":reference_period_month", str(calendar.month_name[self.month])
        )
        result = result.replace(":reference_period_year", str(self.year))
        result = result.replace(":reference_period_previous_year", str(self.year - 1))
        result = result.replace(":reference_period_season", self._season_name())
        result = result.replace(":reference_period", self.reference_period_expression)
        result = result.replace(":published_date", self.story.published_date.strftime("%Y-%m-%d"))
        return result

    def story_is_due(self) -> bool:
        """
        Check if the story should be generated
        is_due is determined by:
        has _sql_data: if the required data exists, for example a yearly report for 2024 cann only be generated if there is data for 2024 in the data source. 
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
                    cmd = self._replace_reference_period_expression(self.story.template.publish_conditions)
                    params = self._get_sql_command_params(cmd)
                    df = self.dbclient.run_query(self.story.template.publish_conditions, params)
                    return df.iloc[0, 0] == 1
                else:
                    return True  # no conditions defined, so we assume they are met

            if self.story.template.has_data_sql:
                params = self._get_sql_command_params(self.story.template.has_data_sql)
                df = self.dbclient.run_query(self.story.template.has_data_sql, params)
                has_data = df.iloc[0, 0] > 0
            else:
                has_data = True

            if (
                self.story.template.reference_period_id == ReferencePeriod.MONTHLY.value
            ):  # monthly
                regular_due_date = ensure_date(self.story.reference_period_start + relativedelta(months=1))
            elif (
                self.story.template.reference_period_id == ReferencePeriod.SEASONAL.value
            ):  # seasonal
                season = month_to_season[self.month]
                month, day = season_dates[season][0]
                regular_due_date = date(
                    self.story.reference_period_start.year, month, day
                )  # ✅ use `date(...)`
            elif (
                self.story.template.reference_period_id == ReferencePeriod.YEARLY.value
            ):  # yearly
                regular_due_date = self.story.reference_period_start.replace(day=1, month=1)
            else:
                regular_due_date = self.story.reference_period_start

            if self.force_generation:
                is_due = has_data
                date_is_due = True
                publish_conditions_met = True
            elif not self.is_data_based:
                is_due = get_publish_conditions_result()
            else:
                # check if the regular due date has passed without publishing the story
                date_is_due = (
                    True
                    if (self.last_published_date is None or self.story.template.reference_period_id == self.story.template.reference_period_id == ReferencePeriod.IRREGULAR.value)
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
        tables = StoryTemplateTable.objects.filter(story_template=self.story.template)  # Use StoryTemplateTable
        for table in tables:
            sql_cmd = table.sql_command
            params = self._get_sql_command_params(sql_cmd)
            try:
                df = self.dbclient.run_query(sql_cmd, params)
                data = df.to_dict(orient="records")
                story_table = StoryTable.objects.filter(
                    story=self.story, table_template=table
                ).first() or StoryTable(story=self.story, table_template=table)
                story_table.title = self._replace_reference_period_expression(table.title)
                story_table.data = json.dumps(data, indent=2, ensure_ascii=False, cls=DecimalEncoder)
                story_table.sort_order = table.sort_order
                story_table.save()  

            except Exception as e:
                self.logger.error(f"Error generating table {table.id}: {e}")
                continue

    def generate_graphics(self) -> list:
        """Generate graphics for the story template and save them directly to database"""
        
        
        try:
            graphic_templates = StoryTemplateGraphic.objects.filter(
                story_template_id=self.story.template.id
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
                    settings['type'] = template.graphic_type

                    # Generate chart HTML
                    self.logger.info(f"Generating chart for: {template.title}")
                    col = settings['y']
                    data[col] = pd.to_numeric(data[col], errors='coerce')
                    chart_html = generate_chart(
                        data=data,
                        settings=settings,
                        chart_id=chart_id
                    )
                    
                    # Create and save Graphic object directly to database
                    story_graphic = (
                        Graphic.objects
                        .filter(story=self.story, graphic_template=template)
                        .first()
                        or Graphic(
                            story=self.story,
                            graphic_template=template
                        )
                    )
                    story_graphic.title=self._replace_reference_period_expression(template.title)
                    story_graphic.content_html=chart_html
                    data = data.map(str)
                    story_graphic.data=json.dumps(data.to_dict(orient="records"), indent=2, ensure_ascii=False, cls=DecimalEncoder)
                    story_graphic.sort_order=template.sort_order
                    story_graphic.save()
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
                f"Initializing story generation for {self.story.template.title} ({self.story.published_date.strftime('%Y-%m-%d')})"
            )
            
            # Generate content
            self.logger.info("Generating story content...")
            self.story.content = self._generate_insight_text()
            
            if not self.story.content:
                self.logger.warning(f"Empty content generated for story {self.story.template.title}")
                return False
            
            self.logger.info("Generating summary...")
            # Generate lead (summary) and an engaging title using the unified LLM helper
            if self.story.template.create_lead:
                self.story.summary = self.generate_summary(self.story.content, kind="lead")
            else:
                self.story.summary = self.story.template.summary

            if self.story.template.create_title:
                self.story.title = self.generate_summary(self.story.content, kind="title")
            else:
                self.story.title = self.story.template.title
            self.logger.info("Saving story to database...")
            try:
                self.story.full_clean()  # This validates the model
            except Exception as validation_error:
                self.logger.error(f"Validation error: {validation_error}")
                # Print all fields and their values for debugging
                for field in self.story._meta.fields:
                    self.logger.info(f"Field '{field.name}': {getattr(self.story, field.name, None)}")
                return False
                
            self.story.save()
            self.logger.info("Generating tables...")
            self.generate_tables()                
            self.logger.info("Generating graphics...")
            self.story.graphics = self.generate_graphics()
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
        try:
            # Use Django ORM to get the maximum publish_date for this template
            last_log = StoryLog.objects.filter(
                story__template=self.story.template  # Use 'story_template' instead of 'story_template_id'
            ).aggregate(last_published_date=models.Max("publish_date"))

            return last_log["last_published_date"]
        except Exception as e:
            self.logger.error(f"Error getting last published date: {e}")
            return None

    def _get_season(self, published_date: datetime, template: StoryTemplate) -> Tuple[int, int]:
        """Get season and season year based on reference period"""
        if self.most_recent_day:
            day = self.most_recent_day
        else:
            day = published_date - timedelta(days=1)

        if template.reference_period_id == ReferencePeriod.DAILY.value:  # daily
            season = month_to_season[day.month]
        elif (
            template.reference_period_id == ReferencePeriod.MONTHLY.value
        ):  # monthly
            month = day.month - 1 if day.month > 1 else 12
            season = month_to_season[month]
        elif (
            template.reference_period_id == ReferencePeriod.SEASONAL.value
        ):  # seasonal
            season = month_to_season[published_date.month] - 1
            if season < 1:
                season = 4
        else:
            season = None

        season_year = published_date.year if published_date.month >= 3 else published_date.year - 1
        return season, season_year

    def _get_reference_period(self, published_date: datetime, template: StoryTemplate) -> Tuple[datetime, datetime]:
        """Get the reference period start and end dates"""
        if template.reference_period_id in (
            ReferencePeriod.DAILY.value,
            ReferencePeriod.IRREGULAR.value,
        ):  # daily, irregular
            # Use most_recent_day if available, otherwise use published_date minus 1 day
            if self.most_recent_day:
                period_start = self.most_recent_day
                period_end = self.most_recent_day
            else:
                fallback_date = published_date - timedelta(days=1)
                period_start = datetime.combine(fallback_date, datetime.min.time())
                period_end = datetime.combine(fallback_date, datetime.min.time())
        elif (
            template.reference_period_id == ReferencePeriod.WEEKLY.value
        ):  # weekly
            period_start = published_date - pd.DateOffset(days=published_date.weekday() + 7)
            period_end = published_date
        elif (
            template.reference_period_id == ReferencePeriod.MONTHLY.value
        ):  # monthly
            if published_date.month > 1:
                month = published_date.month - 1
                year = published_date.year
            else:
                month = 12
                year = published_date.year - 1
            period_start = datetime(year, month, 1)
            period_end = datetime(year, month, calendar.monthrange(year, month)[1])
        elif (
            template.reference_period_id == ReferencePeriod.SEASONAL.value
        ):  # seasonal
            
            start_month, start_day = season_dates[self.season][0]
            end_month, end_day = season_dates[self.season][1]
            start_year = (
                published_date.year - 1
                if self.season == 4
                else published_date.year
            )
            period_start = datetime(start_year, start_month, start_day)
            end_year = published_date.year
            period_end = datetime(end_year, end_month, end_day)
            period_end += pd.DateOffset(days=1)
        elif (
            template.reference_period_id == ReferencePeriod.YEARLY.value
        ):  # yearly
            year = published_date.year - 1
            period_start = datetime(year, 1, 1)
            period_end = period_start + pd.DateOffset(years=1)
        elif (
            template.reference_period_id == ReferencePeriod.IRREGULAR.value
        ):  # yearly
            period_start = published_date - pd.DateOffset(years=1)
            period_end = published_date - pd.DateOffset(days=1)
        else:
            period_start = published_date
            period_end = published_date
            self.logger.warning(
                f"Unknown reference period: {template['reference_period_id']}"
            )
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
        context_data = (
            StoryTemplateContext.objects.filter(story_template_id=self.story.template.id)
            .order_by("sort_order")
        )

        for context_item in context_data:
            key = self._replace_reference_period_expression(context_item.key)
            key = key.replace(" ",   "_").lower()
            result[key] = {}
            result[key]['description'] = context_item.description
            
            cmd = context_item.sql_command
            params = self._get_sql_command_params(cmd)
            df = self.dbclient.run_query(cmd, params)
            if df.empty:
                self.logger.warning(
                    f"No data found for context key: {context_item.key}"
                )
            elif len(df) > 1:
                result[key]['data'] = df.to_dict(orient="records")
            else:
                df = df.iloc[0].to_frame().T
                result[key]['data'] = df.to_dict(orient="records")

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

    def _generate_insight_text(self) -> Optional[str]:
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
                            "```json\n"
                            + self.story.context_values
                            + "\n```"
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
                        "content": (self._replace_reference_period_expression(self.story.template.prompt_text)
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

            return response.choices[0].message.content

        except Exception as e:
            self.logger.error(f"Error generating report text with OpenAI: {e}")
            return None

    def generate_summary(self, insight_text: str, kind: str = "lead") -> Optional[str]:
        """
        Generic LLM helper to produce different short outputs.
        kind: "lead" -> one- or two-sentence summary
              "title" -> single-line engaging analytical title
        """
        try:
            api_key = getattr(settings, "OPENAI_API_KEY", None)
            if not api_key:
                self.logger.error("OpenAI API key not configured")
                return None

            client = OpenAI(api_key=api_key)

            # Kind-specific instructions
            if kind == "title":
                system = "You are a concise editorial assistant producing sharp, data-driven titles"
                user_instruction = (
                    f""".Write a single-line analytical headline (max 10–12 words). 
                    Prefer compact forms over wordiness. 
                    Keep neutral, factual tone. 
                    Return only the title."""
                )
                max_tokens = 60
                temperature = min(max(getattr(self.story.template, "temperature", 0.7), 0.2), 1.0)
            else:  # lead (default)
                system = "Generate a concise one- or two-sentence summary of the provided insight text."
                user_instruction = (
                    "Summarize the following insight text in one or two clear sentences."
                )
                max_tokens = 200
                temperature = getattr(self.story.template, "temperature", 0.2)

            # Construct messages
            messages = [
                {"role": "system", "content": f"{system}\n\n{LLM_FORMATTING_INSTRUCTIONS}"},
                {"role": "user", "content": f"{user_instruction}\n\nInsight text:\n\n{insight_text}"},
            ]

            response = client.chat.completions.create(
                model=self.story.ai_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            raw = response.choices[0].message.content.strip()
            # For title return first non-empty line trimmed
            if kind == "title":
                title_line = next((ln.strip() for ln in raw.splitlines() if ln.strip()), "")
                if not title_line:
                    return None
                return title_line if len(title_line) <= 140 else title_line[:137].rstrip() + "..."

            # For lead return the first paragraph/line(s)
            return next((p.strip() for p in raw.split("\n\n") if p.strip()), raw)

        except Exception as e:
            self.logger.error(f"Error generating {kind} with OpenAI: {e}")
            return None

