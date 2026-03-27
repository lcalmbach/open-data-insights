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
import sys
import tempfile
import time
import urllib.parse
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
# from django.db import transaction
from django.utils import timezone as django_timezone
from django.conf import settings
from tqdm import tqdm

from reports.services.base import ETLBaseService
from reports.services.database_client import DjangoPostgresClient
from reports.services.eia_api import (
    AVAILABLE_SERIES,
    DEFAULT_DATASET_LABEL,
    fetch_eia_prices_df,
)
from reports.services.utils import (
    get_parquet_row_count,
    make_utc,
)
from reports.models.dataset import Dataset, ImportTypeEnum, PeriodEnum


class DatasetSyncService(ETLBaseService):
    """Service for synchronizing datasets from external sources"""

    def __init__(self):
        super().__init__("DatasetSync")
        self.files_path = Path(settings.BASE_DIR) / "files"
        self.files_path.mkdir(exist_ok=True)

    def synchronize_dataset(self, dataset: Dataset) -> bool:
        """Synchronize a single dataset"""
        try:
            if self._is_skipped_dataset(dataset):
                self.logger.info(
                    "Skipping dataset ID %s: %s because import type is SKIP.",
                    dataset.id,
                    dataset.name,
                )
                return True

            self.logger.info(
                f"Starting synchronization for dataset ID {dataset.id}: {dataset.name}"
            )
            processor = create_dataset_processor(dataset)
            if hasattr(processor, "persist_data"):
                result = self._persist_connector_data(dataset, processor)
            elif hasattr(processor, "fetch_dataframe"):
                df = processor.fetch_dataframe()
                result = self._persist_connector_dataframe(dataset, processor, df)
            else:
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

    def _persist_connector_data(self, dataset: Dataset, processor) -> bool:
        try:
            dbclient = DjangoPostgresClient()
            written = processor.persist_data(
                dbclient=dbclient,
                table_name=dataset.target_table_name,
                schema="opendata",
            )
            self._run_sql_batch(dataset.post_create_sql_commands)
            self._run_sql_batch(dataset.post_import_sql_commands)
            self.logger.info(
                "Persisted %s row(s) into opendata.%s for dataset ID %s",
                written,
                dataset.target_table_name,
                dataset.id,
            )
            return True
        except Exception as e:
            self.logger.error(
                f"Error persisting fetched data for dataset ID {dataset.id} ({dataset.name}): {str(e)}"
            )
            return False

    def _persist_connector_dataframe(self, dataset: Dataset, processor, df: pd.DataFrame) -> bool:
        try:
            if df is None or df.empty:
                self.logger.info(
                    "No new rows fetched for dataset ID %s: %s",
                    dataset.id,
                    dataset.name,
                )
                return True

            dbclient = DjangoPostgresClient()
            write_mode = (
                processor.get_write_mode()
                if hasattr(processor, "get_write_mode")
                else "upsert"
            )

            if write_mode == "replace":
                written = dbclient.replace_table_from_dataframe(
                    df=df,
                    table_name=dataset.target_table_name,
                    schema="opendata",
                )
                self._run_sql_batch(dataset.post_create_sql_commands)
            else:
                unique_fields = processor.get_unique_fields()
                update_fields = processor.get_update_fields(df.columns.tolist())
                table_exists = dbclient.table_exists(dataset.target_table_name, schema="opendata")

                if table_exists:
                    written = dbclient.upsert_dataframe(
                        df=df,
                        table_name=dataset.target_table_name,
                        unique_fields=unique_fields,
                        update_fields=update_fields,
                        schema="opendata",
                    )
                else:
                    written = dbclient.create_table_from_dataframe(
                        df=df,
                        table_name=dataset.target_table_name,
                        schema="opendata",
                    )
                    dbclient.ensure_unique_index(
                        table_name=dataset.target_table_name,
                        unique_fields=unique_fields,
                        schema="opendata",
                    )
                    self._run_sql_batch(dataset.post_create_sql_commands)

            self._run_sql_batch(dataset.post_import_sql_commands)
            self.logger.info(
                "Persisted %s row(s) into opendata.%s for dataset ID %s",
                written,
                dataset.target_table_name,
                dataset.id,
            )
            return True
        except Exception as e:
            self.logger.error(
                f"Error persisting fetched DataFrame for dataset ID {dataset.id} ({dataset.name}): {str(e)}"
            )
            return False


    def _run_sql_batch(self, sql_commands: str | None) -> None:
        if not sql_commands:
            return

        dbclient = DjangoPostgresClient()
        for command in sql_commands.split(";"):
            command = command.strip()
            if command:
                dbclient.run_action_query(command)

    @staticmethod
    def _is_skipped_dataset(dataset: Dataset) -> bool:
        import_type_id = getattr(dataset, "import_type_id", None)
        if import_type_id is None:
            import_type = getattr(dataset, "import_type", None)
            import_type_id = getattr(import_type, "id", None)
        return import_type_id == ImportTypeEnum.SKIP.value

    def synchronize_datasets(
        self,
        dataset_id: Optional[int] = None,
        keep_files: bool = False,
    ) -> Dict[str, Any]:
        """Synchronize multiple datasets"""

        if dataset_id:
            matching_datasets = Dataset.objects.filter(active=True, id=dataset_id)
        else:
            matching_datasets = Dataset.objects.filter(active=True)

        datasets = matching_datasets.exclude(
            import_type_id=ImportTypeEnum.SKIP.value
        ).order_by("id")

        results = {
            "success": True,
            "total_datasets": datasets.count(),
            "successful": 0,
            "failed": 0,
            "details": [],
        }

        if not datasets.exists():
            if dataset_id and matching_datasets.exists():
                skipped_dataset = matching_datasets.first()
                self.logger.info(
                    "Dataset ID %s: %s is configured with import type SKIP and was omitted from synchronization.",
                    skipped_dataset.id,
                    skipped_dataset.name,
                )
                results["details"].append(
                    {
                        "dataset_id": skipped_dataset.id,
                        "dataset_name": skipped_dataset.name,
                        "success": True,
                        "skipped": True,
                    }
                )
                return results

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
            self.logger.info(f"Synchronizing dataset ID {dataset.id}: {dataset.name}")

            try:
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

        # Cleanup temporary files unless explicitly preserved for retry/debugging.
        if keep_files:
            self.logger.info("Keeping temporary files in %s", self.files_path)
        else:
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


def create_dataset_processor(dataset: Dataset):
    source = (dataset.source or "").strip().lower()
    connector_map = {
        "ods": OdsDatasetConnector,
        "eia": EiaDatasetConnector,
        "url": UrlDatasetConnector,
    }
    connector_cls = connector_map.get(source)
    if connector_cls is None:
        raise ValueError(f"Unsupported dataset source: {dataset.source!r}")
    return connector_cls(dataset)


class EiaDatasetConnector:
    """Connector that fetches EIA API data as a normalized DataFrame."""

    def __init__(self, dataset: Dataset):
        self.dataset = dataset
        self.logger = logging.getLogger(f"EiaDatasetConnector.{dataset.name}")

    def fetch_dataframe(self) -> pd.DataFrame:
        source_label = (self.dataset.source_identifier or "").strip() or DEFAULT_DATASET_LABEL
        series_selection = getattr(self.dataset, "series_selection", None)
        if not series_selection:
            series_selection = getattr(self.dataset, "fields_selection", None)
        normalized_selection = self._normalize_series_selection(series_selection)
        if normalized_selection is None:
            normalized_selection = [item.series for item in AVAILABLE_SERIES]
        return fetch_eia_prices_df(
            api_url="https://api.eia.gov/v2/petroleum/pri/spt/data/",
            source_label=source_label,
            series_selection=normalized_selection,
            recent_days=7,
            logger=self.logger,
        )

    def get_unique_fields(self) -> list[str]:
        return ["commodity_code", "price_timestamp", "quote_type"]

    def get_update_fields(self, columns: list[str]) -> list[str]:
        return [col for col in columns if col not in self.get_unique_fields()]

    def _normalize_series_selection(self, value: Any) -> list[Any] | None:
        if value is None:
            return None

        if isinstance(value, list):
            if not value:
                return None
            return value

        if isinstance(value, tuple | set):
            items = list(value)
            return items or None

        if isinstance(value, dict):
            return [value]

        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            if stripped[0] in "[{":
                try:
                    parsed = json.loads(stripped)
                except json.JSONDecodeError:
                    pass
                else:
                    if isinstance(parsed, list):
                        return parsed
                    if isinstance(parsed, dict):
                        return [parsed]
                    if isinstance(parsed, str):
                        return [parsed]
            if "," in stripped:
                return [item.strip() for item in stripped.split(",") if item.strip()]
            return [stripped]

        raise ValueError(
            f"Unsupported EIA fields_selection type for dataset {self.dataset.id}: {type(value).__name__}"
        )


class UrlDatasetConnector:
    """Connector that downloads a CSV file from a URL and replaces the target table."""

    def __init__(self, dataset: Dataset):
        self.dataset = dataset
        self.logger = logging.getLogger(f"UrlDatasetConnector.{dataset.name}")

    def fetch_dataframe(self) -> pd.DataFrame:
        if not self.dataset.source_url:
            raise ValueError("URL datasets require source_url.")

        csv_path = self._download_csv_to_temp_file()
        try:
            df = pd.read_csv(
                csv_path,
                sep=None,
                engine="python",
            )
            self.logger.info(
                "Downloaded %s row(s) from URL source %s",
                len(df),
                self.dataset.source_url,
            )
            return df
        finally:
            Path(csv_path).unlink(missing_ok=True)

    def get_write_mode(self) -> str:
        return "replace"

    def persist_data(self, dbclient: DjangoPostgresClient, table_name: str, schema: str = "opendata") -> int:
        csv_path = self._download_csv_to_temp_file()
        try:
            written = dbclient.replace_table_from_csv(
                csv_path,
                table_name=table_name,
                schema=schema,
                sep=None,
                engine="python",
            )
            self.logger.info(
                "Downloaded %s row(s) from URL source %s",
                written,
                self.dataset.source_url,
            )
            return written
        finally:
            Path(csv_path).unlink(missing_ok=True)

    def _download_csv_to_temp_file(self) -> str:
        response = requests.get(
            self.dataset.source_url,
            stream=True,
            timeout=(10, 60),
        )
        try:
            response.raise_for_status()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp_file:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        tmp_file.write(chunk)
                return tmp_file.name
        finally:
            response.close()


class OdsDatasetConnector:
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
            self.ods_records, self.ods_last_record = self.get_ods_last_record() if self.dataset.source == 'ods' else (0, None)  
            # self.ods_last_record_date, self.ods_last_record_identifier = None, None

            if self.ods_last_record and self.dataset.source_timestamp_field:
                raw_timestamp = self.ods_last_record[
                    self.dataset.source_timestamp_field
                ]
                # Add default day if only year-month is provided so fromisoformat succeeds
                if (
                    isinstance(raw_timestamp, str)
                    and len(raw_timestamp) == 7
                    and raw_timestamp.count("-") == 1
                ):
                    raw_timestamp = f"{raw_timestamp}-01"
                self.ods_last_record_date = datetime.fromisoformat(raw_timestamp)
            # elif self.ods_last_record and self.dataset.record_identifier_field:
            #    self.ods_last_record_identifier = self.ods_last_record[self.dataset.record_identifier_field]

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
            self.ods_metadata = self.get_ods_metadata() if self.dataset.source == 'ods' else None
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
        if not self.has_record_identifier_field:
            return []

        url = f"https://{self.dataset.base_url}/api/explore/v2.1/catalog/datasets/{self.dataset.source_identifier}/exports/csv?lang=de&timezone=Europe%2FBerlin&use_labels=false&delimiter=%3B&select={self.dataset.record_identifier_field}&group_by={self.dataset.record_identifier_field}"
        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            raw_lines = response.content.decode("utf-8-sig").splitlines()
            if len(raw_lines) <= 1:  # Only header or empty
                self.logger.warning(
                    "ODS returned no identifier records (header only or empty)."
                )
                return []
            ids = sorted({s.strip() for s in raw_lines[1:] if s.strip()})
            self.logger.info(f"Retrieved {len(ids)} unique identifiers from ODS.")
            return ids
        except Exception as e:
            self.logger.error(f"Failed to fetch ODS identifiers: {e}")
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

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        """Convert a value to float if possible, otherwise return None."""
        if value is None or pd.isna(value):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def dataset_covers_period(self) -> bool:
        freq_id = getattr(self.dataset.data_update_frequency, "id", None)
        if freq_id not in {PeriodEnum.YEARLY.value, PeriodEnum.MONTHLY.value}:
            return False

        url = self._build_period_url(freq_id)
        if not url:
            return False

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            record = self._extract_first_record(response.json())
            if not record:
                return False

            return self._record_matches_period(record, freq_id)
        except Exception as e:
            self.logger.error(f"Failed to fetch ODS last record: {e}")
            return False

    def _build_period_url(self, freq_id: int) -> Optional[str]:
        if not self.dataset.year_field:
            return None

        if freq_id == PeriodEnum.YEARLY.value:
            field_selection = self.dataset.year_field
        elif freq_id == PeriodEnum.MONTHLY.value:
            if not self.dataset.month_field:
                return None
            field_selection = f"{self.dataset.year_field}, {self.dataset.month_field}"
        else:
            return None

        return self.url_last_record.format(
            self.dataset.base_url,
            self.dataset.source_identifier,
            field_selection,
        )

    def _extract_first_record(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        results = data.get("results", [])
        if not results:
            return None
        return results[0]

    def _record_matches_period(self, record: Dict[str, Any], freq_id: int) -> bool:
        year_field = self.dataset.year_field
        record_year = record.get(year_field)
        try:
            record_year = int(record_year)
        except (TypeError, ValueError):
            return False

        now = datetime.now(timezone.utc)
        if freq_id == PeriodEnum.YEARLY.value:
            return record_year >= now.year

        record_month = record.get(self.dataset.month_field)
        if record_month is None:
            return False

        try:
            record_month = int(record_month)
        except (TypeError, ValueError):
            return False

        last_month = now.month - 1 if now.month > 1 else 12
        return record_year == now.year and record_month >= last_month


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
            import_is_due = True

            if self.dataset.source == 'ods' and self.dataset.data_update_frequency.id == PeriodEnum.YEARLY.value and self.dataset.year_field:
                if self.dataset_covers_period():
                    self.logger.info(
                        f"Dataset {identifier} is already up to date."
                    )
                return True
            
            elif self.dataset.import_month or self.dataset.import_day:
                month, day = self.dataset.import_month, self.dataset.import_day
                today = datetime.now(timezone.utc)
                import_is_due = (month == today.month and day == today.day) or (
                    month == None and day == today.day
                )
                if not import_is_due:
                    self.logger.info(
                        f"Reload for {identifier} is not due today ({today.date()}). Skipping synchronization."
                    )
                    return True
            
            if import_is_due and self.dataset.import_type.id == ImportTypeEnum.FULL_RELOAD.value:
                self.logger.info(f"Performing full reload for {identifier}")
                self.dbclient.delete_table(
                    self.dataset.target_table_name, schema="opendata"
                )

            if self.target_table_exists:
                success = self._sync(filename, agg_filename, remote_table)
            else:
                success = self._sync_new_table(filename, agg_filename, remote_table)

            if success and self.dataset.post_import_sql_commands:
                self.logger.info(f"Executing post-import SQL commands")
                for command in self.dataset.post_import_sql_commands.split(";"):
                    command = command.strip()
                    if command:
                        self.dbclient.run_action_query(command)

            elapsed = time.time() - start_time

            if success:
                self.dataset.last_import_date = django_timezone.now()
                self.dataset.save()
                self.logger.info(
                    f"Synchronization for {identifier} completed in {elapsed:.2f} seconds."
                )

            return success

        except Exception as e:
            self.logger.error(f"Error in dataset synchronization: {str(e)}")
            return False

    def _sync(self, filename: Path, agg_filename: Path, remote_table: str) -> bool:
        """Synchronize when target table already exists."""
        try:
            handler = self._get_existing_table_handler()
            if handler:
                return handler(filename, agg_filename, remote_table)

            return self._sync_default(remote_table)

        except Exception as e:
            self.logger.error(f"Error in existing table sync: {e}")
            return False

    def _get_existing_table_handler(self):
        """Return the handler for the configured import type."""
        handlers = {
            ImportTypeEnum.NEW_TIMESTAMP.value: self._sync_new_timestamp,
            ImportTypeEnum.NEW_PK.value: self._sync_new_identifier,
            ImportTypeEnum.NEW_YEAR.value: self._sync_new_year,
            ImportTypeEnum.NEW_YEAR_MONTH.value: self._sync_new_year_month,
        }
        return handlers.get(self.dataset.import_type.id)

    def _sync_new_timestamp(
        self, filename: Path, agg_filename: Path, remote_table: str
    ) -> bool:
        """Handle incremental sync when import type is based on timestamps."""
        ods_date = make_utc(self.ods_last_record_date).date()
        last_db_record = self.dbclient.get_target_last_record(
            self.dataset.target_table_name, self.dataset.db_timestamp_field
        )

        if not last_db_record:
            self.logger.warning(f"No new recorords detected in table {remote_table}")
            return False

        raw_ts = (
            last_db_record.get(self.dataset.db_timestamp_field)
            if isinstance(last_db_record, dict)
            else last_db_record[self.dataset.db_timestamp_field]
        )

        parsed_ts = None
        if isinstance(raw_ts, datetime):
            parsed_ts = raw_ts
        elif isinstance(raw_ts, pd.Timestamp):
            parsed_ts = raw_ts.to_pydatetime()
        elif isinstance(raw_ts, date):
            parsed_ts = datetime(raw_ts.year, raw_ts.month, raw_ts.day)
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
        if ods_date - target_db_date < timedelta(days=1):
            self.logger.info(f"No new data for dataset {remote_table} was found.")
            return True

        self.logger.info(f"New data available in ODS. Last record date: {ods_date}")
        
        # today and future data should not be accepted in most cases as those are often empty records or partial data. however for events or predictions, future data is important and must be imported.
        where_clause = (
            f"{self.dataset.source_timestamp_field} > '{target_db_date.strftime('%Y-%m-%d')}' "
        ) if self.dataset.allow_future_data else (
            f"{self.dataset.source_timestamp_field} > '{target_db_date.strftime('%Y-%m-%d')}' "
            f"and {self.dataset.source_timestamp_field} < '{(datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%d')}'"
        )
        df = self.download_ods_data(
            filename,
            where_clause=where_clause,
            fields=(
                self.dataset.fields_selection if self.dataset.fields_selection else None
            ),
        )

        if df is False:
            self.logger.warning("Failed to download data new data available")
            return False

        if df.empty:
            self.logger.info(f"No new data found for dataset {remote_table}.")
            return True

        df = self.transform_ods_data(df)
        df.to_parquet(agg_filename)
        self.dbclient.upload_to_db(str(agg_filename), self.dataset.target_table_name)

        count = get_parquet_row_count(str(agg_filename))
        self.logger.info(
            f"{count} records added to target database table {remote_table}."
        )
        return True

    def _sync_new_identifier(
        self, filename: Path, agg_filename: Path, remote_table: str
    ) -> bool:
        """Handle incremental sync when import type is based on new identifiers."""
        ods_identifiers = self.get_ods_identifiers()
        db_identifiers = self.get_db_identifiers(remote_table)
        db_identifiers = list(set(db_identifiers))

        # Check for type mismatch
        if ods_identifiers and db_identifiers:
            ods_type = type(ods_identifiers[0]).__name__
            db_type = type(db_identifiers[0]).__name__
            if ods_type != db_type:
                self.logger.warning(
                    f"Type mismatch detected: ODS returns {ods_type}, DB returns {db_type}. "
                    "Normalizing both to strings for comparison."
                )

                ods_identifiers = sorted(
                    {str(x).strip() for x in ods_identifiers if x is not None}
                )
                db_identifiers = sorted(
                    {str(x).strip() for x in db_identifiers if x is not None}
                )

        new_identifiers = list(set(ods_identifiers) - set(db_identifiers))

        if not new_identifiers:
            self.logger.info(
                f"No new records detected in table {remote_table}. "
                f"ODS: {len(ods_identifiers)} records, DB: {len(db_identifiers)} records."
            )
            return True

        self.logger.info(
            f"New data available in ODS. Found {len(new_identifiers)} new record(s)."
        )
        self.logger.debug(
            f"New record IDs: {new_identifiers[:10]}..."
        )  # Log first 10 for brevity

        identifiers_clause = self._format_identifier_clause(new_identifiers)
        where_clause = (
            f"{self.dataset.record_identifier_field} IN ({identifiers_clause})"
        )

        df = self.download_ods_data(
            filename,
            where_clause=where_clause,
            fields=(
                self.dataset.fields_selection if self.dataset.fields_selection else None
            ),
        )

        if df is False:
            self.logger.warning("Failed to download data new data available")
            return False

        if df.empty:
            self.logger.info(f"No new data found for dataset {remote_table}.")
            return True

        df = self.transform_ods_data(df)
        df.to_parquet(agg_filename)
        self.dbclient.upload_to_db(str(agg_filename), self.dataset.target_table_name)

        count = get_parquet_row_count(str(agg_filename))
        self.logger.info(
            f"{count} records added to target database table {remote_table}."
        )
        return True

    def _sync_new_year(
        self, filename: Path, agg_filename: Path, remote_table: str
    ) -> bool:
        """Handle incremental sync when import type is based on new years."""
        self.logger.warning(
            "NEW_YEAR import type handler has not been implemented yet."
        )
        return False

    def _sync_new_year_month(
        self, filename: Path, agg_filename: Path, remote_table: str
    ) -> bool:
        """Handle incremental sync when import type is based on new year/month combinations."""
        self.logger.warning(
            "NEW_YEAR_MONTH import type handler has not been implemented yet."
        )
        return False

    def _sync_default(self, remote_table: str) -> bool:
        """Fallback when no import type handler is configured."""
        self.logger.info(f"No timestamp field configured or no last record available")
        return True

    def _sync_new_table(
        self, filename: Path, agg_filename: Path, remote_table: str
    ) -> bool:
        """Synchronize when target table doesn't exist (full download)"""
        success = False
        try:
            self.logger.warning(
                f"Target table {remote_table} does not exist. Uploading full dataset."
            )

            # Download full dataset
            if self.dataset.source.lower() == "ods":
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
                success = True
            else:
                self.logger.error("Failed to download full dataset")
                success = False

            if success and self.dataset.post_create_sql_commands:
                self.logger.info(f"Executing post-import SQL commands")
                for command in self.dataset.post_create_sql_commands.split(";"):
                    command = command.strip()
                    if command:
                        self.dbclient.run_action_query(command)

        except Exception as e:
            self.logger.error(f"Error in new table sync: {e}")

        return success

    def _normalize_ods_timestamps(self, values: pd.Series) -> pd.Series:
        """Normalize ODS timestamps to a single timezone across DST boundaries."""
        timestamps = pd.to_datetime(values, errors="coerce", utc=True)
        return timestamps.dt.tz_convert("Europe/Zurich")

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
                        disable=not sys.stderr.isatty(),
                    ) as bar:
                        for chunk in r.iter_content(chunk_size=8192):
                            f.write(chunk)
                            bar.update(len(chunk))

            # Read the downloaded file
            df = pd.read_csv(local_csv_file, sep=";", low_memory=False)
            self.logger.info(f"Downloaded {len(df)} records from ODS.")

            # Convert timestamp if needed
            if self.has_timestamp and self.dataset.source_timestamp_field:
                normalized_timestamps = self._normalize_ods_timestamps(
                    df[self.dataset.source_timestamp_field]
                )
                df[self.dataset.source_timestamp_field] = normalized_timestamps
                if self.dataset.db_timestamp_field:
                    df[self.dataset.db_timestamp_field] = normalized_timestamps

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
        source_timestamp_field = self.dataset.source_timestamp_field
        db_timestamp_field = self.dataset.db_timestamp_field
        if self.has_timestamp and source_timestamp_field and source_timestamp_field in df.columns:
            df[source_timestamp_field] = self._normalize_ods_timestamps(
                df[source_timestamp_field]
            )

        # Select specific fields if configured
        if self.dataset.fields_selection:
            df = df[self.dataset.fields_selection]

        if (
            source_timestamp_field
            and db_timestamp_field
            and source_timestamp_field in df.columns
            and db_timestamp_field not in df.columns
        ):
            df[db_timestamp_field] = df[source_timestamp_field]

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
                df[self.dataset.source_timestamp_field] = self._normalize_ods_timestamps(
                    df[self.dataset.source_timestamp_field]
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

    def _format_identifier_clause(self, identifiers: list) -> str:
        """Return a SQL IN-clause string for identifier values with safe escaping."""
        safe_identifiers = [
            str(identifier).replace("'", "''") for identifier in identifiers
        ]
        return ", ".join(f"'{identifier}'" for identifier in safe_identifiers)

    def get_time_limit_where_clause(self) -> Optional[str]:
        """Construct WHERE clause for time limits"""
        if self.dataset.source_timestamp_field and not self.dataset.allow_future_data:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            return f"{self.dataset.source_timestamp_field} < '{today}'"
        else:
            return None
