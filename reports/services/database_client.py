"""
Django-integrated Database Client
Replaces the standalone PostgresClient with Django ORM integration
"""

import logging
import pandas as pd
from typing import Optional, Dict, Any, List
from django.db import connection, transaction
from django.conf import settings
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from .utils import normalize_sql_query


class DjangoPostgresClient:
    """
    Database client that integrates with Django's connection handling
    while maintaining compatibility with the existing SQLAlchemy-based code
    """

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.schema = getattr(settings, "DB_DATA_SCHEMA", "opendata")

        # Create SQLAlchemy engine for bulk operations (where Django ORM might be slower)
        db_config = settings.DATABASES["default"]
        connection_string = (
            f"postgresql+psycopg2://{db_config['USER']}:{db_config['PASSWORD']}"
            f"@{db_config['HOST']}:{db_config['PORT']}/{db_config['NAME']}"
            f"?options=-csearch_path%3D{self.schema}"
        )
        self.engine = create_engine(connection_string)

    def run_query(self, query: str, params: dict | None = None):
        """Execute a query and return DataFrame - uses Django connection"""
        # Normalize the query using our utility function
        clean_query = normalize_sql_query(query)
        params = params or {}

        try:
            with connection.cursor() as cursor:
                # Log rendered SQL for debugging (psycopg2-style)
                try:
                    rendered = cursor.mogrify(clean_query, params)
                    self.logger.debug(
                        "Executing SQL: %s",
                        rendered.decode()
                        if isinstance(rendered, (bytes, bytearray))
                        else rendered,
                    )
                except Exception:
                    self.logger.debug(
                        "Could not mogrify SQL; query: %s params: %s",
                        clean_query,
                        params,
                    )
                cursor.execute(clean_query, params)
                cols = [c[0] for c in cursor.description] if cursor.description else []
                rows = cursor.fetchall()
                return pd.DataFrame(rows, columns=cols)
        except Exception:
            self.logger.exception("Error executing SQL")
            raise

    def run_action_query(self, query: str, params: Optional[Dict] = None) -> None:
        """Execute an action query (INSERT, UPDATE, DELETE) - uses Django connection"""
        # Normalize the query using our utility function
        clean_query = normalize_sql_query(query)

        with connection.cursor() as cursor:
            # Only pass params when provided; passing an empty mapping causes
            # psycopg2 to attempt formatting and breaks on literal '%' in SQL.
            if params is None:
                cursor.execute(clean_query)
            else:
                # If a dict is provided, drop None values to avoid accidental NULL param bindings
                if isinstance(params, dict):
                    params = {k: v for k, v in params.items() if v is not None}
                cursor.execute(clean_query, params)

    def table_exists(self, table_name: str, schema: str = None) -> bool:
        """Check if a table exists in the database"""
        if schema is None:
            schema = self.schema

        query = """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables 
                WHERE table_schema = %s AND table_name = %s
            )
        """
        with connection.cursor() as cursor:
            cursor.execute(query, [schema, table_name])
            return cursor.fetchone()[0]

    def list_tables(self, schema: str = None) -> pd.DataFrame:
        """List all tables in a schema"""
        if schema is None:
            schema = self.schema

        query = """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s
            AND table_type = 'BASE TABLE'
        """
        with connection.cursor() as cursor:
            cursor.execute(query, [schema])
            tables = cursor.fetchall()
            return pd.DataFrame(tables, columns=["table_name"])

    def get_target_last_record(
        self, table_name: str, timestamp_field: str
    ) -> Optional[Dict]:
        """Get the last record from a table based on timestamp field"""
        try:
            query = f"""
                SELECT * FROM {self.schema}."{table_name}" 
                ORDER BY {timestamp_field} DESC 
                LIMIT 1
            """
            with connection.cursor() as cursor:
                cursor.execute(query)
                if cursor.rowcount > 0:
                    columns = [col[0] for col in cursor.description]
                    row = cursor.fetchone()
                    return dict(zip(columns, row))
                return None
        except Exception as e:
            self.logger.warning(
                f"Database error while accessing table '{table_name}': {e}"
            )
            return None

    def upload_to_db(self, file_path: str, table_name: str, chunksize: int = 10000):
        """Upload a parquet file to the database using SQLAlchemy for performance"""
        try:
            df = pd.read_parquet(file_path, engine="pyarrow")
            self.logger.info(f"{len(df)} records were read from {file_path}.")

            # Use SQLAlchemy for bulk operations (more efficient than Django ORM)
            from tqdm import tqdm

            for start in tqdm(range(0, len(df), chunksize), desc="Uploading"):
                chunk = df.iloc[start : start + chunksize]
                chunk.to_sql(
                    table_name,
                    con=self.engine,
                    schema=self.schema,
                    if_exists="append",
                    index=False,
                    method="multi",
                )

            self.logger.info(f"Data was uploaded to table {table_name} successfully.")

        except Exception as e:
            self.logger.error(f"Error uploading file to database: {e}")
            raise
