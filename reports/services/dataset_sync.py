"""
Dataset Synchronization Service
Handles importing and synchronizing datasets from external sources
"""

import json
import logging
import pandas as pd
import numpy as np
import requests
import os
import time
import urllib.parse
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List
from django.db import transaction
from django.utils import timezone as django_timezone
from django.conf import settings
from tqdm import tqdm

from reports.models import Dataset
from reports.services.base import ETLBaseService
from reports.services.database_client import DjangoPostgresClient
from reports.services.utils import (
    get_parquet_row_count,
    make_utc,
)
from reports.models import Dataset


class DatasetSyncService(ETLBaseService):
    """Service for synchronizing datasets from external sources"""

    def __init__(self):
        super().__init__("DatasetSync")
        self.files_path = Path(settings.BASE_DIR) / "files"
        self.files_path.mkdir(exist_ok=True)

    def synchronize_dataset(self, dataset: Dataset) -> bool:
        """Synchronize a single dataset"""
        try:
            self.logger.info(
                f"Starting synchronization for dataset ID {dataset.id}: {dataset.name}"
            )

            # Create dataset processor
            processor = DatasetProcessor(dataset)
            result = processor.synchronize()

            if result:
                # Update last import date
                dataset.last_import_date = django_timezone.now()
                dataset.save(update_fields=["last_import_date"])
                self.logger.info(
                    f"Successfully synchronized dataset ID {dataset.id}: {dataset.name}"
                )
                return True
            else:
                self.logger.error(
                    f"Failed to synchronize dataset ID {dataset.id}: {dataset.name}"
                )
                return False

        except Exception as e:
            self.logger.error(
                f"Error synchronizing dataset ID {dataset.id} ({dataset.name}): {str(e)}"
            )
            return False

    def synchronize_datasets(self, dataset_id: Optional[int] = None) -> Dict[str, Any]:
        """Synchronize multiple datasets"""
        
        if dataset_id:
            datasets = Dataset.objects.filter(id=dataset_id)
        else:
            datasets = Dataset.objects.filter(active=True)

        results = {
            "success": True,
            "total_datasets": datasets.count(),
            "successful": 0,
            "failed": 0,
            "details": [],
        }
        
        if not datasets.exists():
            self.logger.error(f"No active dataset found with ID: {dataset_id}")
            results["failed"] += 1
            results["success"] = False
            results["details"].append(
                {
                    "dataset_id": dataset_id,
                    "dataset_name": "None",
                    "success": False,
                    "error": "No dataset found with this ID",
                }
            )

        for dataset in datasets:
            try:
                with transaction.atomic():
                    success = self.synchronize_dataset(dataset)
                    if success:
                        results["successful"] += 1
                    else:
                        results["failed"] += 1
                        results["success"] = False

                    results["details"].append(
                        {
                            "dataset_id": dataset.id,
                            "dataset_name": dataset.name,
                            "success": success,
                        }
                    )

            except Exception as e:
                self.logger.error(
                    f"Transaction failed for dataset ID {dataset.id} ({dataset.name}): {str(e)}"
                )
                results["failed"] += 1
                results["success"] = False
                results["details"].append(
                    {
                        "dataset_id": dataset.id,
                        "dataset_name": dataset.name,
                        "success": False,
                        "error": str(e),
                    }
                )

        # Cleanup temporary files
        self.cleanup_temp_files()

        # Enhanced logging with failed dataset IDs
        if results["failed"] > 0:
            failed_datasets = [
                detail["dataset_id"]
                for detail in results["details"]
                if not detail["success"]
            ]
            self.logger.error(
                f"Synchronization completed with errors. Processed: {results['total_datasets']}, Failed: {results['failed']}, Failed dataset IDs: {failed_datasets}"
            )
        else:
            self.logger.info(
                f"Synchronization completed successfully. Processed: {results['total_datasets']}, All successful"
            )

        return results


class DatasetProcessor:
    """
    Processor for individual dataset operations
    Contains the migrated business logic from the original Dataset class
    """

    def __init__(self, dataset: Dataset):
        self.dataset = dataset
        self.logger = logging.getLogger(f"DatasetProcessor.{dataset.name}")
        self.dbclient = DjangoPostgresClient()
        self.files_path = Path(settings.BASE_DIR) / "files"
        self.files_path.mkdir(exist_ok=True)

        # URLs for ODS API
        self.url_ods_data = "https://{}/api/explore/v2.1/catalog/datasets/{}/exports/csv?lang=de&timezone=Europe%2FBerlin&use_labels=false&delimiter=%3B"
        self.url_ods_metadata = "https://{}/api/explore/v2.1/catalog/datasets/{}"
        self.url_last_record = "https://{}/api/explore/v2.1/catalog/datasets/{}/records?limit=1&order_by={}%20desc"

        # Initialize dataset properties
        self.has_timestamp = (
            self.dataset.source_timestamp_field is not None
            and self.dataset.source_timestamp_field != ""
        )
        self.has_record_identifier_field = (
            self.dataset.record_identifier_field is not None
            and self.dataset.record_identifier_field != ""
        )

        # Get ODS metadata and last record
        try:
            self.ods_records, self.ods_last_record = self.get_ods_last_record()
            self.ods_last_record_date, self.ods_last_record_identifier = None, None
            if self.ods_last_record and self.dataset.source_timestamp_field:
                self.ods_last_record_date = datetime.fromisoformat(
                    self.ods_last_record[self.dataset.source_timestamp_field]
                )
            elif self.ods_last_record and self.dataset.record_identifier_field:
                self.ods_last_record_identifier = self.ods_last_record[self.dataset.record_identifier_field]
            
        except Exception as e:
            self.logger.warning(f"Could not get ODS last record: {e}")
            self.ods_records = 0
            self.ods_last_record = None
            self.ods_last_record_date = None

        # Check if target table exists
        self.target_table_exists = self.dbclient.table_exists(
            self.dataset.target_table_name, schema="opendata"
        )

        # Get ODS metadata
        try:
            self.ods_metadata = self.get_ods_metadata()
        except Exception as e:
            self.logger.warning(f"Could not get ODS metadata: {e}")
            self.ods_metadata = None

    def get_ods_metadata(self) -> Optional[Dict]:
        """Get metadata from ODS API"""
        url = self.url_ods_metadata.format(
            self.dataset.base_url, self.dataset.source_identifier
        )
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger.error(f"Failed to fetch ODS metadata: {e}")
            return None

    def get_ods_last_record(self) -> tuple:
        """Get the last record from ODS API"""
        if self.has_record_identifier_field:
            url = self.url_last_record.format(
                self.dataset.base_url,
                self.dataset.source_identifier,
                self.dataset.record_identifier_field,
            )
            try:
                response = requests.get(url, timeout=30)
                response.raise_for_status()
                data = response.json()
                records = data.get("total_count", 0)
                record = data.get("results", [])
                return records, record[0] if record else None
            except Exception as e:
                self.logger.error(f"Failed to fetch ODS last record: {e}")
                return 0, None
        elif self.dataset.source_timestamp_field:
            url = self.url_last_record.format(
                self.dataset.base_url,
                self.dataset.source_identifier,
                self.dataset.source_timestamp_field,
            )
            try:
                response = requests.get(url, timeout=30)
                response.raise_for_status()
                data = response.json()
                records = data.get("total_count", 0)
                record = data.get("results", [])
                return records, record[0] if record else None
            except Exception as e:
                self.logger.error(f"Failed to fetch ODS last record: {e}")
                return 0, None
        else:
            return 0, None
    
    def get_ods_identifiers(self) -> List[Any]:
        """Get all record identifiers from ODS"""
        if self.has_record_identifier_field:
            # url = f"https://{self.dataset.base_url}/api/explore/v2.1/catalog/datasets/{self.dataset.source_identifier}/exports/json?lang=de&timezone=Europe%2FBerlin&use_labels=false"
            url = f"https://{self.dataset.base_url}/api/explore/v2.1/catalog/datasets/{self.dataset.source_identifier}/exports/csv?lang=de&timezone=Europe%2FBerlin&use_labels=false&delimiter=%3B&select={self.dataset.record_identifier_field}"
            try:
                response = requests.get(url, timeout=60)
                response.raise_for_status()
                ids = sorted({int(s) for s in response.content.decode("utf-8-sig").splitlines()[1:] if s.strip()})
                return ids
            except Exception as e:
                self.logger.error(f"Failed to fetch ODS identifiers: {e}")
                return []
        else:
            return []
    
    def get_db_identifiers(self, table_name: str) -> List[Any]:
        """Get all record identifiers from the target database table"""
        try:
            query = f"SELECT {self.dataset.record_identifier_field} FROM opendata.{table_name}"
            results = self.dbclient.run_query(query)
            identifiers = list(results[self.dataset.record_identifier_field])
            return identifiers
        except Exception as e:
            self.logger.error(f"Failed to fetch DB identifiers: {e}")
            return []

    def synchronize(self) -> bool:
        """
        Main synchronization method - migrated from original Dataset.synchronize()
        """
        try:
            identifier = self.dataset.source_identifier
            remote_table = self.dataset.target_table_name
            filename = self.files_path / f"{identifier}.parquet"
            agg_filename = self.files_path / f"{identifier}_agg.parquet"

            self.logger.info(f"Starting import for {identifier}")
            start_time = time.time()

            if self.target_table_exists:
                success = self._sync_existing_table(
                    filename, agg_filename, remote_table
                )
            else:
                success = self._sync_new_table(filename, agg_filename, remote_table)
            
            if success:
                if self.dataset.post_import_sql_commands:
                    self.logger.info(
                        f"Executing post-import SQL commands for dataset {identifier}"
                    )
                    for command in self.dataset.post_import_sql_commands.split(";"):
                        command = command.strip()
                        if command:
                            self.dbclient.run_action_query(command)
                            
                elapsed = time.time() - start_time
                self.logger.info(
                    f"Synchronization for {identifier} completed in {elapsed:.2f} seconds."
                )
            return success

        except Exception as e:
            self.logger.error(f"Error in dataset synchronization: {str(e)}")
            return False

    def _sync_existing_table(
        self, filename: Path, agg_filename: Path, remote_table: str
    ) -> bool:
        """Synchronize when target table already exists"""
        try:
            if self.has_timestamp and self.ods_last_record_date:
                ods_date = make_utc(self.ods_last_record_date).date()
                last_db_record = self.dbclient.get_target_last_record(
                    self.dataset.target_table_name, self.dataset.db_timestamp_field
                )

                if last_db_record:
                    raw_ts = (
                        last_db_record.get(self.dataset.db_timestamp_field)
                        if isinstance(last_db_record, dict)
                        else last_db_record[self.dataset.db_timestamp_field]
                    )

                    parsed_ts = None
                    # Already a datetime
                    if isinstance(raw_ts, datetime):
                        parsed_ts = raw_ts
                    # pandas Timestamp
                    elif isinstance(raw_ts, pd.Timestamp):
                        parsed_ts = raw_ts.to_pydatetime()
                    # date only -> convert to datetime at midnight
                    elif isinstance(raw_ts, date):
                        parsed_ts = datetime(raw_ts.year, raw_ts.month, raw_ts.day)
                    # string -> try ISO parse then pandas fallback
                    elif isinstance(raw_ts, str):
                        try:
                            parsed_ts = datetime.fromisoformat(raw_ts)
                        except Exception:
                            parsed = pd.to_datetime(raw_ts, errors="coerce")
                            if not pd.isna(parsed):
                                parsed_ts = parsed.to_pydatetime()

                    if parsed_ts is None:
                        self.logger.warning(
                            f"Could not parse last DB record timestamp for {remote_table}: {raw_ts!r}"
                        )
                        return False

                    target_db_date = make_utc(parsed_ts).date()

                    # Check if new data is available
                    if ods_date - target_db_date >= timedelta(days=1):
                        self.logger.info(
                            f"New data available in ODS. Last record date: {ods_date}"
                        )

                        # Download incremental data
                        where_clause = (
                            f"{self.dataset.source_timestamp_field} > '{target_db_date.strftime('%Y-%m-%d')}' "
                            f"and {self.dataset.source_timestamp_field} < '{datetime.now(timezone.utc).strftime('%Y-%m-%d')}'"
                        )

                        df = self.download_ods_data(
                            filename,
                            where_clause=where_clause,
                            fields=(
                                self.dataset.fields_selection
                                if self.dataset.fields_selection
                                else None
                            ),
                        )

                        if df is not False and not df.empty:
                            df = self.transform_ods_data(df)
                            df.to_parquet(agg_filename)
                            self.dbclient.upload_to_db(
                                str(agg_filename), self.dataset.target_table_name
                            )

                            count = get_parquet_row_count(str(agg_filename))
                            self.logger.info(
                                f"{count} records added to target database table {remote_table}."
                            )

                            self.post_process_data()
                            return True
                        if df.empty:
                            self.logger.info(
                                f"No new data found for dataset {remote_table}."
                            )
                            return True
                        else:
                            self.logger.warning(
                                "Failed to download data new data available"
                            )
                            return False
                    else:
                        self.logger.info(
                            f"No new data for dataset {remote_table} was found."
                        )
                        return True
                else:
                    self.logger.warning(
                        f"No new recorords detected in table {remote_table}"
                    )
                    return False
            elif self.has_record_identifier_field and self.ods_last_record_identifier:
                ods_identifers = self.get_ods_identifiers()
                db_identifiers = self.get_db_identifiers(remote_table)
                # unique indentifiers only
                ods_identifers = sorted(set(ods_identifers))
                db_identifiers = sorted(set(db_identifiers))
                new_identifiers = list(set(ods_identifers) - set(db_identifiers))
                if new_identifiers:
                    self.logger.info(
                        f"New data available in ODS. New record IDs: {new_identifiers}"
                    )

                    # Download incremental data
                    where_clause = (
                        f"{self.dataset.record_identifier_field} IN ({', '.join([f'\'{id}\'' for id in new_identifiers])})"
                    )

                    df = self.download_ods_data(
                        filename,
                        where_clause=where_clause,
                        fields=(
                            self.dataset.fields_selection
                            if self.dataset.fields_selection
                            else None
                        ),
                    )

                    if df is not False and not df.empty:
                        df = self.transform_ods_data(df)
                        df.to_parquet(agg_filename)
                        self.dbclient.upload_to_db(
                            str(agg_filename), self.dataset.target_table_name
                        )

                        count = get_parquet_row_count(str(agg_filename))
                        self.logger.info(
                            f"{count} records added to target database table {remote_table}."
                        )

                        self.post_process_data()
                        return True
                    if df.empty:
                        self.logger.info(
                            f"No new data found for dataset {remote_table}."
                        )
                        return True
                    else:
                        self.logger.warning("Failed to download data new data available")
                        return False
                else:
                    self.logger.warning(
                        f"no new records detected in table {remote_table}"
                    )
                    return True
            else:
                self.logger.info(
                    f"No timestamp field configured or no last record available"
                )
                return True

        except Exception as e:
            self.logger.error(f"Error in existing table sync: {e}")
            return False

    def _sync_new_table(
        self, filename: Path, agg_filename: Path, remote_table: str
    ) -> bool:
        """Synchronize when target table doesn't exist (full download)"""
        try:
            self.logger.warning(
                f"Target table {remote_table} does not exist. Uploading full dataset."
            )

            # Download full dataset
            where_clause = self.get_time_limit_where_clause()
            df = self.download_ods_data(
                filename,
                where_clause=where_clause,
                fields=(
                    self.dataset.fields_selection
                    if self.dataset.fields_selection
                    else None
                ),
            )
    
            if df is not False and not df.empty:
                df = self.transform_ods_data(df)
                df.to_parquet(agg_filename)
                self.dbclient.upload_to_db(str(agg_filename), remote_table)
                # check if data-time column is of type date, if not force it
                if not pd.api.types.is_datetime64_any_dtype(df[self.dataset.db_timestamp_field]):
                    df[self.dataset.db_timestamp_field] = pd.to_datetime(df[self.dataset.db_timestamp_field], errors="coerce")
                self.post_process_data()
                return True
            else:
                self.logger.error("Failed to download full dataset")
                return False

        except Exception as e:
            self.logger.error(f"Error in new table sync: {e}")
            return False

    def download_ods_data(
        self, filename: Path, where_clause: str = None, fields: list = None
    ) -> pd.DataFrame:
        """Download data from ODS API"""
        url = "https://{}/api/explore/v2.1/catalog/datasets/{}/exports/csv"
        base_url = url.format(self.dataset.base_url, self.dataset.source_identifier)

        params = {
            "lang": "de",
            "timezone": "Europe/Zurich",
            "use_labels": "false",
            "delimiter": ";",
        }

        if where_clause:
            params["where"] = where_clause
        if fields:
            params["fields"] = ",".join(fields)

        try:
            query_string = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
            full_url = f"{base_url}?{query_string}"
            local_csv_file = str(filename).replace(".parquet", ".csv")
            if os.path.exists(local_csv_file):
                self.logger.info(
                    f"File {local_csv_file} already exists. Using existing csv file."
                )
            else:
                # Download with progress bar
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

            # Read the downloaded file
            df = pd.read_csv(local_csv_file, sep=";", low_memory=False)
            self.logger.info(f"Downloaded {len(df)} records from ODS.")

            # Convert timestamp if needed
            if self.has_timestamp and self.dataset.source_timestamp_field:
                df[self.dataset.db_timestamp_field] = pd.to_datetime(
                    df[self.dataset.source_timestamp_field], errors="coerce"
                )

            return df

        except Exception as e:
            self.logger.error(f"Error downloading ODS data: {e}")
            return False

    def transform_ods_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Transform and process the downloaded data"""
        month_to_season = {
            12: 4,
            1: 4,
            2: 4,  # Winter
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

        # Convert timestamp fields
        if self.has_timestamp and self.dataset.source_timestamp_field:
            df[self.dataset.source_timestamp_field] = pd.to_datetime(
                df[self.dataset.source_timestamp_field], errors="coerce", utc=True
            )
            df[self.dataset.source_timestamp_field] = df[
                self.dataset.source_timestamp_field
            ].dt.tz_convert("Europe/Zurich")

        # Select specific fields if configured
        if self.dataset.fields_selection:
            df = df[self.dataset.fields_selection]

        # Add constants if configured
        if self.dataset.constants:
            for item in self.dataset.constants:
                if isinstance(item, dict) and "field_name" in item:
                    df[item["field_name"]] = item.get("value", "")

        # Apply aggregations if configured
        if self.dataset.aggregations:
            df = self._apply_aggregations(df)

        # Delete records with missing values
        if self.dataset.delete_records_with_missing_values:
            self.logger.info(
                f"Deleting records with missing values in fields: {self.dataset.delete_records_with_missing_values}"
            )
            for field in self.dataset.delete_records_with_missing_values:
                df = df[df[field].notna()]

        # Ensure proper timestamp conversion
        if (
            self.dataset.db_timestamp_field
            and self.dataset.db_timestamp_field in df.columns
        ):
            col = df[self.dataset.db_timestamp_field]
            if not pd.api.types.is_numeric_dtype(col):
                df[self.dataset.db_timestamp_field] = pd.to_datetime(
                    col, errors="coerce"
                )

        # Add time aggregation fields if configured
        if self.dataset.add_time_aggregation_fields and self.dataset.db_timestamp_field:
            self.logger.info(
                "Adding time aggregation fields (season, year, month etc.)"
            )
            df["year"] = df[self.dataset.db_timestamp_field].dt.year
            df["month"] = df[self.dataset.db_timestamp_field].dt.month
            df["day_in_year"] = df[self.dataset.db_timestamp_field].dt.dayofyear
            df["season"] = df[self.dataset.db_timestamp_field].dt.month.map(
                month_to_season
            )
            df["season_year"] = np.where(
                df["month"].isin([1, 2]),
                df[self.dataset.db_timestamp_field].dt.year - 1,
                df[self.dataset.db_timestamp_field].dt.year,
            )

        # ensure df is a real copy before mutating to avoid SettingWithCopyWarning
        df = df.copy()

        if self.dataset.source_timestamp_field in df.columns:
            df.loc[:, self.dataset.source_timestamp_field] = pd.to_datetime(
                df[self.dataset.source_timestamp_field], errors="coerce"
            )

        return df

    def _apply_aggregations(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply aggregations to the data"""
        if not self.dataset.aggregations:
            return df

        try:
            agg_config = self.dataset.aggregations

            self.logger.info(f"Number of records before aggregation: {len(df)}")

            # Ensure timestamp is properly converted
            if self.dataset.source_timestamp_field:
                df[self.dataset.source_timestamp_field] = pd.to_datetime(
                    df[self.dataset.source_timestamp_field], errors="coerce"
                )
                df[self.dataset.db_timestamp_field] = df[
                    self.dataset.source_timestamp_field
                ].dt.date

            # Create aggregation dictionary
            agg_dict = {}
            if "agg_functions" in agg_config:
                for field in agg_config["value_fields"]:
                    for func in agg_config["agg_functions"]:
                        agg_dict[f"{func}_{field}"] = (field, func)

            # Apply aggregation
            if "group_fields" in agg_config:
                df = (
                    df.groupby(agg_config["group_fields"], as_index=False)
                    .agg(**agg_dict)
                    .sort_values(self.dataset.db_timestamp_field, ascending=False)
                )

            self.logger.info(f"Number of records after aggregation: {len(df)}")

        except Exception as e:
            self.logger.error(f"Error applying aggregations: {e}")

        return df

    def post_process_data(self):
        """Execute post-processing commands"""
        if self.dataset.calculated_fields:
            for item in self.dataset.calculated_fields:
                if isinstance(item, dict) and item.get("command"):
                    cmd = item["command"]
                    try:
                        self.dbclient.run_action_query(cmd)
                        self.logger.info(f"Post-import command executed: {cmd}")
                    except Exception as e:
                        self.logger.error(f"Error executing post-import command: {e}")

    def get_time_limit_where_clause(self) -> Optional[str]:
        """Construct WHERE clause for time limits"""
        
        if self.dataset.source_timestamp_field:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            return f"{self.dataset.source_timestamp_field} < '{today}'"
        else:
            return None