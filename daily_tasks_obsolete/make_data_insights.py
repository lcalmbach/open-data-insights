import json
import logging
from daily_tasks.utils import setup_logger
from daily_tasks.data_news import Dataset, Story
from datetime import date, timedelta
import sys
import psycopg2
import pandas as pd
from decouple import config
from sqlalchemy import create_engine
import argparse


logger = setup_logger(name=__name__, log_file="logs/sync.log")
db_url = (
    f"postgresql+psycopg2://{config('DB_USER')}:{config('DB_PASSWORD')}"
    f"@{config('DB_HOST')}:{config('DB_PORT')}/{config('DB_NAME')}"
)
# Create SQLAlchemy engine
conn = create_engine(db_url)


def load_config(table_name) -> pd.DataFrame:
    query = f"SELECT * FROM report_generator.reports_{table_name} WHERE active = TRUE"
    df = pd.read_sql(query, conn)
    return df


def run(story_id=None, run_date=None, force=False):
    stories_df = load_config("storytemplate")
    run_date = run_date or date.today()
    logger.info("Generating data insights...")
    if story_id:
        stories_df = stories_df[stories_df["id"] == story_id]
        if len(stories_df) == 0:
            logger.error(f"'{story_id}' is not a valid story id.")
            logger.info(f"Available stories: {', '.join(stories_df['title'])}")

    for key, row in stories_df.iterrows():
        if row["active"]:
            logger.info(f"Generating data insight: {row['title']}")
            data = dict(row)
            story = Story(data, run_date, force)
            if story.story_is_due():
                story.generate_story()
            else:
                logger.info(
                    f"No data available or story '{row['title']}' is not due for generation on {run_date}."
                )
        else:
            logger.info(f"Skipping report generation for: {row['title']}")
        logger.info("All data insights have been created.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process records by ID and date.")

    parser.add_argument("--id", type=int, help="ID of the record to process")
    parser.add_argument(
        "--date",
        type=lambda d: date.fromisoformat(d),
        help="Date to run the process (format: YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force creation even if the date does not match run_year/month/day",
    )

    args = parser.parse_args()
    run(story_id=args.id, run_date=args.date, force=args.force)
