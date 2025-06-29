import json
import logging
from .utils import setup_logger
from .data_news import Dataset, Story
from datetime import date, timedelta
import sys
import psycopg2
import pandas as pd
from decouple import config
import argparse

logger = setup_logger(name=__name__, log_file="logs/sync.log")
conn = psycopg2.connect(
    dbname=config("DB_NAME"),
    user=config("DB_USER"),
    password=config("DB_PASSWORD"),
    host=config("DB_HOST"),
    port=config("DB_PORT"),
)


def load_config(table_name) -> pd.DataFrame:
    query = f"SELECT * FROM report_generator.reports_{table_name} WHERE active = TRUE"
    df = pd.read_sql(query, conn)
    return df


def run(dataset_id=None):
    datasets_df = load_config("dataset")
    logger.info("Starting data synchronisation...")
    if dataset_id:
        datasets_df = datasets_df[datasets_df["id"] == dataset_id]
        if len(datasets_df) == 0:
            logger.error(f"'{dataset_id}' is not a valid dataset.")
            logger.info(f"Available datasets: {', '.join(datasets_df['name'])}")

    for index, row in datasets_df.iterrows():
        if row["active"]:
            logger.info(f"Synchronizing: {row['name']}")
            dataset = Dataset(row)
            dataset.synchronize()
    logger.info("Synchronisation was completed successfully.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process records by dataset ID.")

    parser.add_argument("--id", type=int, help="ID of the record to process")
    args = parser.parse_args()
    run(dataset_id=args.id)
