import json
from typing import Tuple
import pandas as pd
import numpy as np
import requests
import os
from pathlib import Path
from datetime import datetime, timezone
import calendar
import urllib.parse
from sqlalchemy import create_engine, text, MetaData, Table, select, desc
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from .utils import get_parquet_row_count, setup_logger, make_utc
import time
from tqdm import tqdm
import logging
from .sql_templates import templates
from openai import OpenAI
from decouple import config
import psycopg2
from datetime import timedelta
import math
from typing import Optional

url_ods_data = "https://{}/api/explore/v2.1/catalog/datasets/{}/exports/csv?lang=de&timezone=Europe%2FBerlin&use_labels=false&delimiter=%3B"
url_ods_metadata = "https://{}/api/explore/v2.1/catalog/datasets/{}"
url_last_record = (
    "https://{}/api/explore/v2.1/catalog/datasets/{}/records?limit=1&order_by={}%20desc"
)
cmd_last_postgres_record = (
    """SELECT COUNT(*) as cnt, MAX({}) as last_record_timestamp FROM opendata."{}" """
)
files_path = Path("./files")
url_azure_blob = "https://{}/api/explore/v2.1/catalog/datasets/{}/exports/azure_blob?lang=de&timezone=Europe%2FBerlin&use_labels=false&delimiter=%3B"
report_config_file = "./reports_config.json"
logger = setup_logger(name=__name__, log_file="logs/sync.log")
DEFAULT_AI_MODEL = "gpt-4o"
month_to_season = {
    1: 4,
    2: 4,
    12: 4,
    3: 1,
    4: 1,
    5: 1,
    6: 2,
    7: 2,
    8: 2,
    9: 3,
    10: 3,
    11: 3,
}


season_dates = {
    1: ((3, 1), (5, 31)),    # Spring
    2: ((6, 1), (8, 31)),    # Summer
    3: ((9, 1), (11, 30)),   # Fall
    4: ((12, 1), (2, 28)),   # Winter
}

# with open(report_config_file, "r", encoding="utf-8") as f:
#    report_config = json.load(f)


def is_unset(value):
    return value is None or (isinstance(value, float) and math.isnan(value))


class PostgresClient:
    def __init__(self):
        self.user = config("DB_USER")
        self.password = config("DB_PASSWORD")
        self.host = config("DB_HOST")
        self.port = config("DB_PORT")
        self.database = config("DB_NAME")
        self.schema = config("DB_DATA_SCHEMA")
        connection_string = f"postgresql+psycopg2://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}?options=-csearch_path%3D{self.schema}"
        self.engine = create_engine(connection_string)

    def run_query(self, query: str, params=None) -> pd.DataFrame:
        with self.engine.connect() as conn:
            return pd.read_sql_query(text(query), conn, params=params)

    def run_action_query(self, query: str, params=None) -> None:
        with self.engine.connect() as conn:
            conn.execute(text(query), params or {})
            conn.commit()  # If using a transactional database

    def table_exists(self, table_name: str, schema: str = "public") -> bool:
        query = f"""
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables 
                WHERE table_schema = :schema AND table_name = :table
            )
        """
        with self.engine.connect() as conn:
            result = conn.execute(
                text(query), {"schema": schema, "table": table_name}
            ).scalar()
        return result

    def list_tables(self, schema: str = "public") -> pd.DataFrame:
        query = f"""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = :schema
            AND table_type = 'BASE TABLE';
        """
        with self.engine.connect() as conn:
            result = conn.execute(text(query), {"schema": schema})
            return pd.DataFrame(result.fetchall(), columns=["table_name"])

    def get_target_last_record(self, table_name: str, timestamp_field: str) -> dict:
        metadata = MetaData(schema="opendata")

        try:
            my_table = Table(table_name, metadata, autoload_with=self.engine)
            stmt = select(my_table).order_by(desc(my_table.c[timestamp_field])).limit(1)
            with self.engine.connect() as conn:
                result = conn.execute(stmt).mappings().first()
                return result if result else pd.DataFrame()

        except SQLAlchemyError as e:
            logger.warning(f"Database error while accessing table '{table_name}': {e}")
            return (
                pd.DataFrame()
            )  # oder `raise` wenn du die Exception weiterreichen willst

    def upload_to_db(self, file_path: str, table_name: str):
        try:
            df = pd.read_parquet(file_path, engine="pyarrow")
            logger.info(f"{len(df)} records were read from {file_path}.")
            chunksize = 10000
            for start in tqdm(range(0, len(df), chunksize)):
                chunk = df.iloc[start : start + chunksize]
                chunk.to_sql(
                    table_name,
                    con=self.engine,
                    schema=self.schema,
                    if_exists="append",
                    index=False,
                    method="multi",
                )
            logger.info(f"data was uploaded to Table {table_name} successfully.")
        except Exception as e:
            logger.warning(f"Error uploading file to Postgres database: {e}")


class Story:
    def __init__(self, template: dict, date: datetime, force_generation: bool = False):
        self.id = None  # is filled when record is created in the database
        self.force_generation = force_generation
        self.template = template
        self.published_date = date
        self.dbclient = PostgresClient()
        most_recent_day_sql = self.template.get("most_recent_day_sql", None)

        self.most_recent_day = (
            self.get_most_recent_day(most_recent_day_sql)
            if most_recent_day_sql
            else None
        )
        
        self.season, self.season_year = self.get_season()
        self.has_data_sql = self.template.get("has_data_sql", None)
        self.publish_conditions = self.template.get("publish_conditions", {})
        self.content = None  # will be filled when the story is generated

        self.reference_period_start, self.reference_period_end = (
            self.get_reference_period()
        )
        self.data_is_published = self.is_published()
        self.measured_values = self.init_measured_values()
        self.context_values = {}
        self.context_values["context_data"] = self.get_context_data()
        self.title = self.get_title()

    def is_published(self) -> Optional[datetime]:
        sql = """SELECT count(*) as result 
            FROM report_generator.reports_storylog 
            where reference_period_start = :date
            and story_template_id = :template_id
        """

        params = {"template_id": self.template["id"], "date": self.reference_period_start}
        df = self.dbclient.run_query(sql, params)
        return df.iloc[0, 0]

    def get_most_recent_day(self, sql: str) -> Optional[datetime]:
        """
        Retrieves the most recent date from the database based on the provided SQL query and date parameter.

        Args:
            sql (str): The SQL query to execute. Should contain a placeholder for the date parameter.
            date (datetime): The date to use as a parameter in the SQL query.

        Returns:
            Optional[datetime]: The most recent date found in the query result, or None if the query is empty or returns no results.
        """
        if not sql:
            return None

        params = {"published_date": self.published_date}
        df = self.dbclient.run_query(sql, params)
        if df.empty:
            return None

        return df.iloc[0, 0]
    
    def get_sql_command_params(self, cmd: str) -> dict:
        params = {}
        if not cmd:
            return params  # empty dict if cmd is None or empty string
        if "period_start_date" in cmd:
            params["period_start_date"] = self.reference_period_start.strftime("%Y-%m-%d")
        if "published_date" in cmd:
            params["published_date"] = self.published_date.strftime("%Y-%m-%d")
        if ":month" in cmd:
            params["month"] = self.reference_period_start.month
        if ":year" in cmd:
            params["year"] = self.reference_period_start.year
        if ":season" in cmd:
            params["season"] = month_to_season[self.reference_period_start.month]
            params["season_year"] = self.season_year
        return params
    
    def season_name(self) -> str:
        """
        Returns the name of the season based on the season number.
        Args:
            season (int): The season number (1: Spring, 2: Summer, 3: Fall, 4: Winter).
        Returns:
            str: The name of the season.
        """
        if self.season == 1:
            return "Spring"
        elif self.season == 2:
            return "Summer"
        elif self.season == 3:
            return "Fall"
        elif self.season == 4:
            return "Winter"
        else:
            return "Unknown Season"
    
    def init_measured_values(self):
        """
        Initializes the measured values for the story.
        This method creates a dictionary with keys as the names of the measured values
        and values as empty strings. The keys are defined in the template.

        Returns:
            dict: A dictionary with measured values initialized to empty strings.
        """
        my_dict = {
            "period_of_interest": {
                "start": self.reference_period_start.strftime("%Y-%m-%d"),
                "end": self.reference_period_end.strftime("%Y-%m-%d"),
                "label": None,
                "type": None,
            }
        }
        if self.template["reference_period_id"] == 35:  # daily
            my_dict["period_of_interest"]["label"] = (
                self.reference_period_start.strftime("%Y-%m-%d")
            )
            my_dict["period_of_interest"]["type"] = "daily"

        elif self.template["reference_period_id"] == 36:  # monthly
            my_dict["period_of_interest"][
                "label"
            ] = f'{self.reference_period_start.strftime("%B")} {self.reference_period_start.strftime("%Y")}'
            my_dict["period_of_interest"]["type"] = "monthly"
        elif self.template["reference_period_id"] == 37:  # seasonal
            my_dict["period_of_interest"][
                "label"
            ] = f'{self.season_name()} {self.season_year}'
            my_dict["period_of_interest"]["type"] = "seasonally"
        my_dict["measured_values"] = self.get_reference_values()
        return my_dict

    def get_title(self):
        """
        Retrieves the title for the story from the template.
        The title is expected to be in the 'title' field of the template.

        Returns:
            str: The title of the story.
        """

        if self.template["reference_period_id"] == 35:  # daily
            return f"{self.template['title']} ({self.reference_period_start.strftime('%Y-%m-%d')})"
        elif self.template["reference_period_id"] == 36:  # monthly
            month_name = calendar.month_name[self.reference_period_start.month]
            return f"{self.template['title']} ({month_name}/{self.reference_period_start.year})"
        elif self.template["reference_period_id"] == 37:  # seasonal
            return f"{self.template['title']} ({self.season_name()} {self.reference_period_start.year})"
        elif self.template["reference_period_id"] == 38:  # yearly
            return f"{self.template['title']} ({self.reference_period_start.year})"
        else:
            return self.template['title']
            
    def get_reference_values(self) -> str:
        """
        Retrieves the reference values for the story from the database.
        This method queries the database for the reference values defined in the story configuration.

        Returns:
            dict: a string holding all reference period measured values to describe in the data story.
        """
        result = {}
        cmd = """SELECT title, sql_command
            FROM report_generator.reports_storytemplateperiodofinterestvalues
            WHERE story_template_id = :template_id
            ORDER BY sort_key
        """
        params = {"template_id": self.template["id"]}
        df = self.dbclient.run_query(cmd, params)
        for index, row in df.iterrows():
            cmd = row["sql_command"]
            params = self.get_sql_command_params(cmd)
            df = self.dbclient.run_query(cmd, params)
            if len(df) == 0:
                result[row["title"]] = "No data available for this period."
            elif len(df) > 1:
                result[row["title"]] = df.to_dict(orient="records")
            else:
                result[row["title"]] = df.iloc[0].to_dict()
        return result

    def get_season(self) ->Tuple[int, int]:
        """
        Checks if the story is due for generation based on the reference dt_record(self, table_name: str, timestate.
        The story is due if the reference date is older than 2 days.

        Returns:
            bool: True if the story is due, False otherwise.
        """
        day = self.published_date - timedelta(days=1)
        if self.template["reference_period_id"] == 35:  # daily
            season = month_to_season[day.month]
        elif self.template["reference_period_id"] == 36:  # monthly
            month = day.month -1 if day.month > 1 else 12
            season = month_to_season[month]
        elif self.template["reference_period_id"] == 37:  # seasonal
            # first get the last season, then get the start_end dates for this season
            season = month_to_season[self.published_date.month] -1 if month_to_season[self.published_date.month] > 1 else 4
        else:
            season = None
            season_year = None

        season_year = self.published_date.year
        return season, season_year

    def get_reference_period(self) -> Tuple[datetime, datetime]:
        """
        Checks if the story is due for generation based on the reference dt_record(self, table_name: str, timestate.
        The story is due if the reference date is older than 2 days.

        Returns:
            bool: True if the story is due, False otherwise.
        """
        if self.template["reference_period_id"] in (35, 56):  # daily, irregular
            period_start = self.most_recent_day
            period_end = self.most_recent_day
        elif self.template["reference_period_id"] == 36:  # monthly
            if self.published_date.month > 1:
                month = self.published_date.month - 1
                year = self.published_date.year
            else:
                month = 12
                year = self.published_date.year - 1
            period_start = datetime(year, month, 1)
            period_end = datetime(year, month, calendar.monthrange(year, month)[1])
        elif self.template["reference_period_id"] == 37:  # seasonal
            start_month, start_day = season_dates[self.season][0]
            end_month, end_day = season_dates[self.season][1]
            start_year = self.published_date.year -1 if self.season == 4 else self.published_date.year
            period_start = datetime(start_year, start_month, start_day)
            # For winter, end month is in the next year
            end_year = self.published_date.year 
            period_end = datetime(end_year, end_month, end_day)
            # Add one day to make the end exclusive (if needed)
            period_end += pd.DateOffset(days=1)

        elif self.template["reference_period_id"] == 38:  # yearly
            year = self.published_date.year - 1
            period_start = datetime(year, 1, 1)
            period_end = period_start + pd.DateOffset(years=1)
        else:
            period_end = None
            period_start = None
            logger.warning(
                f"Unknown reference period: {self.template['reference_period_id']}"
            )
        return period_start, period_end

    def story_is_due(self) -> bool:
        """
        Determines whether a story is due for generation based on data availability and reference period.
        Returns:
            bool: True if the story is due for generation, False otherwise.
        Logic:
            - Checks if there is relevant data for the given reference period.
            - If `force_generation` is True, returns whether data is available.
            - Otherwise, checks if the current run year, month, and day (if specified) match the reference period.
            - Returns True if all conditions are met and the story is due; otherwise, returns False.
        """

        if self.has_data_sql: 
            params = self.get_sql_command_params(self.has_data_sql)
            df = self.dbclient.run_query(self.has_data_sql, params)
            has_data = df.iloc[0]["cnt"] > 0
        else:
            # if no has_data_sql is defined, we assume there is data 
            has_data = True

        if self.force_generation:
            is_due = has_data
        else:
            params = self.get_sql_command_params(self.publish_conditions)
            df = self.dbclient.run_query(self.publish_conditions, params)
            is_due = has_data and df.iloc[0, 0] == 1 and not(self.data_is_published)
            is_due &= not self.data_is_published
        return is_due

    def get_context_data(self) -> dict:
        """File "/home/lcalm/Work/Dev/data_news_agent/src/data_news.py", line 329, in get_context_data
        Retrieves the comparisons for the story from the database.
        This method queries the database for the comparisons defined in the story configuration.

        Returns:
            dict: A dictionary containing the comparisons for the story.
        """
        result = {}
        cmd = """SELECT key, description, sql_command
            FROM report_generator.v_context
            WHERE story_template_id = :template_id
            ORDER BY key
        """
        params = {"template_id": self.template["id"]}
        df = self.dbclient.run_query(cmd, params)
        for index, row in df.iterrows():
            if row["key"] not in result:
                result[row["key"]] = {}
            node = result[row["key"]]

            cmd = row["sql_command"]
            params = self.get_sql_command_params(cmd)
            df = self.dbclient.run_query(cmd, params)
            if df.empty:
                logger.warning(f"No data found for context key: {row['key']}")
            elif len(df) > 1:
                node[row["description"]] = df.to_dict(orient="records")
            else:
                df = df.iloc[0].to_frame().T
                node[row["description"]] = df.to_dict(orient="records")

        return result

    def generate_story(self):
        """
        Generates the story text based on the parameters and the prompt.
        This method uses the OpenAI API to generate the story text.

        Returns:
            str: The generated story text.
        """

        def save_story_record():
            cmd = "Update report_generator.reports_story set json_payload = :json_payload, prompt_text = :prompt, content = :content where id = :id"
            params = {
                "json_payload": json.dumps(self.context_values, ensure_ascii=False),
                "prompt": self.template["prompt_text"],
                "content": self.content,
                "id": int(self.id),
            }
            self.dbclient.run_action_query(cmd, params)
            logger.info(f"AI response was successfully saved to the database.")

        def save_log_record():
            """
            Writes a log record for the story generation.
            This method inserts a new record into the reports_storylog table with the
            reference period start date and the story template ID.
            """
            cmd = """insert into report_generator.reports_storylog (
                reference_period_start, reference_period_end, story_template_id, story_id, publish_date) 
                values (:reference_period_start, :reference_period_end, :template_id, :story_id, :publish_date)
            """
            params = {
                "reference_period_start": self.reference_period_start,
                "reference_period_end": self.reference_period_end,
                "template_id": int(self.template["id"]),
                "story_id": int(self.id),
                "publish_date": self.published_date,
            }
            self.dbclient.run_action_query(cmd, params)
            logger.info(f"Log record for story generation was successfully saved.")

        def insert_story_record():
            """
            Inserts a new story record into the database.
            This method cleans up existing stories for the same day and inserts a new record
            with the provided title, published date, reference period start and end,
            reference values, and AI model.
            """

            # cleanup existing stories for the same day
            cmd = "delete from report_generator.reports_story where template_id = :template and published_date = :date"
            params = {
                "template": self.template["id"],
                "date": self.published_date.strftime("%Y-%m-%d"),
            }
            self.dbclient.run_action_query(cmd, params)
            cmd = "insert into report_generator.reports_story (template_id, title, published_date, reference_period_start, reference_period_end, reference_values, ai_model) values (:template_id, :title, :published_date, :reference_period_start, :reference_period_end, :reference_values, :ai_model)"
            params = {
                "template_id": int(self.template["id"]),
                "published_date": self.published_date,
                "title": self.title,
                "reference_period_start": self.reference_period_start,
                "reference_period_end": self.reference_period_end,
                "reference_values": json.dumps(
                    self.measured_values, ensure_ascii=False
                ),
                "ai_model": DEFAULT_AI_MODEL,
            }
            self.dbclient.run_action_query(cmd, params)
            # find id of record created
            cmd = "select max(id) from report_generator.reports_story"
            new_id = self.dbclient.run_query(cmd).iloc[0, 0]
            return new_id

        logger.info(
            f"initializing story db record {self.template['title']} for {self.published_date.strftime('%Y-%m-%d')}"
        )
        self.id = insert_story_record()
        logger.info(f"initializing comparisons")

        logger.info(f"sending prompt to OpenAI API")
        self.content = self.generate_report_text()
        logger.info(f"response received from OpenAI API")
        save_story_record()
        save_log_record()

    def generate_report_text(self):
        """
        Sends a weather data prompt to the OpenAI API and returns the generated report.

        Parameters:
            json_data (str): The JSON string representing the weather data.
            api_key (str): Your OpenAI API key.
            model (str): Model to use, e.g., "gpt-4" or "gpt-4o".

        Returns:
            str: The generated weather report.
        """

        api_key = os.getenv("OPENAI_API_KEY")
        client = OpenAI(api_key=api_key)
        disclaimer = """\nIf no reference data is available just return the text: no data was available for the period of interest.
        Format the output in markdown. Add a disclaimer that this content has been generated by an AI algorithm."""
        response = client.chat.completions.create(
            model=DEFAULT_AI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": self.template["prompt_text"] + disclaimer,
                },
                {
                    "role": "user",
                    "content": f"Measured data in reference period: \n\n {self.measured_values}. Historic comparison data:\n{self.context_values}",
                },
            ],
            temperature=self.template["temperature"],
        )
        return response.choices[0].message.content


class Dataset:
    def __init__(self, cfg):
        self.name = cfg["name"]
        self.id = cfg.get("id", True)
        self.active = cfg.get("active", True)
        self.source = cfg["source"]
        self.source_identifier = cfg["source_identifier"]
        self.description = cfg.get("description", "")
        self.base_url = cfg["base_url"]
        self.source_timestamp_field = cfg["source_timestamp_field"]
        self.db_timestamp_field = cfg["db_timestamp_field"]
        self.has_timestamp = (
            cfg["source_timestamp_field"] is not None
            and cfg["source_timestamp_field"] != ""
        )
        self.record_identifier_field = cfg["record_identifier_field"]
        self.has_record_identifier_field = (
            self.record_identifier_field is not None
            and self.record_identifier_field != ""
        )
        self.target_table_name = cfg["target_table_name"]
        self.delete_records_with_missing_values = cfg.get(
            "delete_records_with_missing_values", False
        )
        self.last_import_date = cfg.get("last_import_date", None)
        self.aggregations = cfg.get("aggregations", [])
        self.add_time_aggregation_fields = cfg.get("add_time_aggregation_fields", [])
        self.fields_selection = cfg.get("fields_selection", [])
        self.import_filter = cfg.get("import_filter", None)
        self.db_timestamp_field = cfg.get("db_timestamp_field", None)
        self.constants = cfg.get("constants", [])
        self.calculated_fields = cfg.get("calculated_fields", [])
        try:
            self.ods_records, self.ods_last_record = self.get_ods_last_record()
            self.ods_last_record_date = datetime.fromisoformat(
                self.ods_last_record[self.source_timestamp_field]
            )
        except:
            pass
        self.dbclient = PostgresClient()
        self.target_table_exists = self.dbclient.table_exists(
            self.target_table_name, schema="opendata"
        )
        self.ods_metadata = self.get_ods_metadata()

    def __repr__(self):
        return f"Job(job_id={self.id}, name={self.name})"

    def get_ods_metadata(self):
        url = url_ods_metadata.format(self.base_url, self.source_identifier)
        response = requests.get(url)
        if response.status_code == 200:
            metadata = response.json()
            return metadata
        else:
            raise ValueError(
                f"Failed to fetch metadata: {response.status_code} - {response.text}"
            )

    def get_ods_last_record(self):
        url = url_last_record.format(
            self.base_url, self.source_identifier, self.source_timestamp_field
        )
        response = requests.get(url)
        if response.status_code == 200:
            data = json.loads(response.text)
            records = data["total_count"]
            record = data["results"][0]
            return records, record

    def download_ods_data(
        self, filename, where_clause: str = None, fields: list = None
    ):
        url = "https://{}/api/explore/v2.1/catalog/datasets/{}/exports/csv"
        base_url = url.format(self.base_url, self.source_identifier)
        params = {
            "lang": "de",
            "timezone": "Europe/Zurich",
            "use_labels": "false",
            "delimiter": ";",
        }
        local_csv_file = str(filename).replace(".parquet", ".csv")
        Path(local_csv_file).parent.mkdir(parents=True, exist_ok=True)
        
        if where_clause:
            params["where"] = where_clause
        if fields:
            params["fields"] = ",".join(fields)
        try:
            query_string = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
            full_url = f"{base_url}?{query_string}"
            # Lokaler CSV-Dateiname
            
            # Streamed Download mit Fortschrittsanzeige
            with requests.get(full_url, stream=True, timeout=(10, 60)) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                with open(local_csv_file, "wb") as f, tqdm(
                    desc="Downloading CSV",
                    total=total,
                    unit="B",
                    unit_scale=True,
                    unit_divisor=1024,
                ) as bar:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
                        bar.update(len(chunk))
            # Jetzt die lokal gespeicherte Datei laden
            
            df = pd.read_csv(local_csv_file, sep=";", low_memory=False)
            logger.info(f"Downloaded {len(df)} records from ODS.")

            if self.has_timestamp:
                df[self.db_timestamp_field] = pd.to_datetime(
                    df[self.source_timestamp_field], errors="coerce"
                )
            return df

        except Exception as e:
            logger.warning(f"Error downloading ODS data: {e}")
            return False

    def transform_ods_data(self, df):
        month_to_season = {
            12: 4,
            1: 4,
            2: 4,  # Winter
            3: 1,
            4: 1,
            5: 1,  # Frühling
            6: 2,
            7: 2,
            8: 2,  # Sommer
            9: 3,
            10: 3,
            11: 3,  # Herbst
        }
        if self.has_timestamp:
            df[self.source_timestamp_field] = pd.to_datetime(
                df[self.source_timestamp_field], errors="coerce", utc=True
            )
            df[self.source_timestamp_field] = df[self.source_timestamp_field].dt.tz_convert("Europe/Zurich")
        if self.fields_selection != []:
            df = df[self.fields_selection]
        if self.constants != []:
            for item in self.constants:
                pass  # !todo
        if self.aggregations != {}:
            logger.info(f"Numbr of records before time stamp coercion: {len(df)}")
            df[self.source_timestamp_field] = pd.to_datetime(
                df[self.source_timestamp_field], errors="coerce"
            )
            logger.info(f"Number of records after time stamp coercion: {len(df)}")
            df[self.db_timestamp_field] = df[self.source_timestamp_field].dt.date
            agg_config = self.aggregations
            # Create a dictionary like {'avg_value': ('value', 'mean'), ...}
            agg_dict = {
                f"{func}_{col}": (col, func)
                for col in agg_config["value_fields"]
                for func in agg_config["agg_functions"]
            }
            df = (
                df.groupby(agg_config["group_fields"], as_index=False)
                .agg(**agg_dict)
                .sort_values(self.db_timestamp_field, ascending=False)
            )
            logger.info(f"number of records: {len(df)} after aggregation.")
        if self.delete_records_with_missing_values != []:
            logger.info(
                f"Deleting records with missing values in fields: {self.delete_records_with_missing_values}"
            )
            for field in self.delete_records_with_missing_values:
                df = df[df[field].notna()]
        if self.db_timestamp_field:
            col = df[self.db_timestamp_field]
            if not pd.api.types.is_numeric_dtype(col):
                df[self.db_timestamp_field] = pd.to_datetime(col, errors="coerce")
        if self.add_time_aggregation_fields:
            logger.info(f"Adding time aggregation fields (season, year, month etc.)")
            df["year"] = df[self.db_timestamp_field].dt.year
            df["month"] = df[self.db_timestamp_field].dt.month
            df["day_in_year"] = df[self.db_timestamp_field].dt.dayofyear
            df["season"] = df[self.db_timestamp_field].dt.month.map(month_to_season)
            df["season_year"] = np.where(
                df["month"].isin([1,2]),
                df[self.db_timestamp_field].dt.year - 1,
                df[self.db_timestamp_field].dt.year,
            )

        return df

    def post_process_data(self):
        for item in self.calculated_fields:
            if item["command"] != "":
                cmd = item["command"]
                # parameters = item.get('parameters', {})
                self.dbclient.run_action_query(cmd, None)
                logger.info(f"Post-import command executed: {cmd}")

    def get_time_limit_where_clause(self):
        """
        Constructs a ODS WHERE clause based on the configuration settings.
        This method generates a WHERE clause to filter records based on a time limit.
        The clause is constructed if the 'aggregation' key exists in the configuration
        and specific conditions are met. Currently, it supports filtering records
        where the timestamp is less than the current date when the aggregation
        function is 'max' and the grouping period is 'day'. This is useful for
        the current incomplete date is not included in the aggregation so that every
        date included all records for this day.

        Returns:
            str or None: A SQL WHERE clause string if the conditions are met,
            otherwise None.
        """

        # Initialize where_clause for conditional assignment based on configuration
        where_clause = None
        if self.aggregations:
            if self.aggregations.get("grouping_period") == "day":
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                where_clause = f"{self.source_timestamp_field} < :today"

        return where_clause

    def synchronize(self):
        identifier = self.source_identifier
        remote_table = self.target_table_name
        filename = files_path / f"{identifier}.parquet"
        agg_filename = files_path / f"{identifier}_agg.parquet"
        logger.info(f"Starting import for {identifier}")
        start = time.time()
        if self.target_table_exists:
            start = time.time()
            if self.has_timestamp:
                ods_date = make_utc(self.ods_last_record_date)
                last_db_record = self.dbclient.get_target_last_record(
                    self.target_table_name, self.db_timestamp_field
                )
                target_db_date = make_utc(last_db_record[self.db_timestamp_field])
                # Make dates timezone-aware (UTC)

                # target_db_date = target_db_date.astimezone(timezone.utc) if target_db_date.tzinfo else target_db_date.replace(tzinfo=timezone.utc)
                # if time differnece between ods_date and  target_db_ is greater 1 day
                if ods_date - target_db_date >= timedelta(days=1):
                    logger.info(
                        f"New data available in ODS. Last record date: {ods_date}"
                    )

                    where_clause = f"{self.source_timestamp_field} > '{target_db_date.strftime('%Y-%m-%d')}' and {self.source_timestamp_field} < '{datetime.now(timezone.utc).strftime("%Y-%m-%d")}'"
                    df = self.download_ods_data(
                        filename,
                        where_clause=where_clause,
                        fields=self.fields_selection,
                    )
                    df = self.transform_ods_data(df)
                    df.to_parquet(agg_filename)
                    self.dbclient.upload_to_db(
                        str(agg_filename), self.target_table_name
                    )

                    count = get_parquet_row_count(str(agg_filename))
                    logger.info(
                        f"{count} records added to target database table {remote_table}."
                    )
                    self.post_process_data()  # calculate fields on the database
                else:
                    logger.info(f"No new data for dataset {remote_table} was found.")
            else:
                # handle synch if there is only a jahr record
                pass
        else:
            logger.warning(
                f"Target table {remote_table} does not exist. Uploading full dataset."
            )
            local_csv_file = str(filename).replace(".parquet", ".csv")
            if not os.path.exists(local_csv_file):
                logger.info(f"Downloading full dataset for {identifier}.")
                where_clause = self.get_time_limit_where_clause()
                df = self.download_ods_data(
                    filename, where_clause=where_clause, fields=self.fields_selection
                )
            else:
                df = pd.read_csv(local_csv_file, sep=";", low_memory=False)

            if not df.empty:
                df = self.transform_ods_data(df)
                df.to_parquet(agg_filename)
                self.dbclient.upload_to_db(
                    file_path=str(agg_filename), table_name=remote_table
                )
                self.post_process_data()  # calculated fields

        elapsed = time.time() - start
        logger.info(
            f"Synchronisation for {identifier} completed in {elapsed:.2f} seconds."
        )
