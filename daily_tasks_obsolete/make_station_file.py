import pandas as pd

from sqlalchemy import create_engine, text, MetaData, Table, select, desc
from sqlalchemy.engine import Engine
from utils import get_parquet_row_count, setup_logger, make_utc
import time
from tqdm import tqdm
import tomllib
import os

file_name = "./files/100164.parquet"
secrets_file = "./secrets.toml"
table_name = "ds_100164_stations"
csv_file = file_name.replace(".parquet", "_stations.csv")


# filen needs to be saved, then mnaually cleaned for duplicates, since
def transform_file():
    df = pd.read_parquet(file_name, engine="pyarrow")
    stations_df = (
        df[["stationnr", "stationname", "stationid", "lat", "lon", "bohrkataster_link"]]
        .drop_duplicates()
        .sort_values("stationnr")
    )
    stations_df.to_csv(csv_file, index=False, sep=";", encoding="utf-8")


def get_engine():
    secrets = {}
    config = {}
    try:
        with open(secrets_file, "rb") as f:
            secrets = tomllib.load(f)
    except FileNotFoundError:
        print(
            f"Warning: Config file '{secrets_file}' not found. Falling back to environment variables."
        )

    config.setdefault("postgres", {})
    user = secrets["postgres"].get("user", os.getenv("PGUSER"))
    password = secrets["postgres"].get("password", os.getenv("PGPASSWORD"))
    host = secrets["postgres"].get("host", os.getenv("PGHOST", "localhost"))
    port = secrets["postgres"].get("port", os.getenv("PGPORT", "5432"))
    database = secrets["postgres"].get("database", os.getenv("PGDATABASE", "postgres"))
    schema = secrets["postgres"].get("schema", os.getenv("PGSCHEMA", "opendata"))

    connection_string = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}?options=-csearch_path%3D{schema}"
    return create_engine(connection_string)


def save_to_db():
    csv_file = file_name.replace(".parquet", "_stations.csv")
    df = pd.read_csv(csv_file, sep=";")
    engine = get_engine()
    schema = "opendata"
    df.to_sql(
        table_name,
        con=engine,
        schema=schema,
        if_exists="append",
        index=False,
        method="multi",
    )


save_to_db()
