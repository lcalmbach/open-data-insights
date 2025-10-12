"""
ETL Utilities
Common utility functions for ETL operations
"""

import pyarrow.parquet as pq
import logging
import re
from pathlib import Path
from datetime import timezone, date, datetime
from typing import Optional
from dateutil.relativedelta import relativedelta
import calendar
import json


def get_parquet_row_count(file_path: str) -> int:
    """Get the number of rows in a parquet file"""
    parquet_file = pq.ParquetFile(file_path)
    return parquet_file.metadata.num_rows


def make_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Convert datetime to UTC timezone"""
    if not dt:
        return None
    if isinstance(dt, date) and not isinstance(dt, datetime):
        # Convert date → datetime
        dt = datetime(dt.year, dt.month, dt.day)
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def delete_all_files_in_folder(folder: Path) -> None:
    """
    Delete all files (not directories) in the given Path object folder.

    Args:
        folder (Path): A pathlib.Path object pointing to a folder.
    """
    if not folder.exists() or not folder.is_dir():
        print(f"Folder '{folder}' does not exist or is not a directory.")
        return

    for file in folder.glob("*"):
        if file.is_file():
            file.unlink()
            print(f"Deleted: {file.name}")


def normalize_sql_query(query: str) -> str:
    """
    Normalize SQL query by cleaning up formatting and common issues.

    - Replace line endings with spaces
    - Normalize whitespace
    - Remove trailing semicolons
    - Fix malformed parameter placeholders
    - Escape literal % characters in LIKE clauses for Django parameter compatibility

    Args:
        query (str): Raw SQL query string

    Returns:
        str: Normalized SQL query string
    """
    # Clean the query: replace line endings with spaces
    clean_query = query.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")

    # Remove extra whitespace
    clean_query = " ".join(clean_query.split())

    # Remove trailing semicolon
    clean_query = clean_query.rstrip(";").strip()

    # Fix malformed parameters like %(param)% -> %(param)s
    clean_query = re.sub(r"%\(([^)]+)\)%", r"%(\1)s", clean_query)

    # Fix other common parameter formatting issues
    clean_query = re.sub(
        r"%\(([^)]+)\)d", r"%(\1)s", clean_query
    )  # %(param)d -> %(param)s
    clean_query = re.sub(
        r"%\(([^)]+)\)f", r"%(\1)s", clean_query
    )  # %(param)f -> %(param)s

    return clean_query


# SQL Templates for common operations
SQL_TEMPLATES = {
    "summary_no_group": """SELECT 
        MIN({0}) AS min_value,
        percentile_cont(0.01) WITHIN GROUP (ORDER BY {0}) AS p01,
        percentile_cont(0.05) WITHIN GROUP (ORDER BY {0}) AS p05,
        percentile_cont(0.25) WITHIN GROUP (ORDER BY {0}) AS p25,
        percentile_cont(0.75) WITHIN GROUP (ORDER BY {0}) AS p75,
        percentile_cont(0.95) WITHIN GROUP (ORDER BY {0}) AS p95,
        percentile_cont(0.99) WITHIN GROUP (ORDER BY {0}) AS p99,
        MAX({0}) AS max_value
    FROM opendata.{1}
    WHERE {0} IS NOT NULL {2};"""
}

def ensure_date(dt):
    return dt.date() if isinstance(dt, datetime) else dt

def get_month_labels(abbrev: bool = True) -> list:
    """Return month labels for 1..12.

    Args:
        abbrev: if True return 3-letter abbreviations (Jan, Feb, ...),
                otherwise full month names (January, February, ...).

    Returns:
        list of 12 strings for months January..December
    """
    if abbrev:
        # month_abbr[1]..month_abbr[12]
        return [calendar.month_abbr[i] for i in range(1, 13)]
    return [calendar.month_name[i] for i in range(1, 13)]

def get_month_labels_literal(abbrev: bool = True) -> str:
    """Return month labels as a JSON-style array string with double quotes.

    Useful when you want to copy a double-quoted list into other tools or the database.
    Example: "["Jan","Feb",... ]"
    """
    labels = get_month_labels(abbrev=abbrev)
    return json.dumps(labels)

