"""
ETL Base Service
Provides common functionality for all ETL operations
"""

import logging
from django.conf import settings
from pathlib import Path
from typing import Optional, Any, Dict, List
import pandas as pd
from pathlib import Path
from reports.services.utils import delete_all_files_in_folder


class ETLBaseService:
    """Base class for all ETL services"""

    def __init__(self, logger_name: str = None):
        self.logger = logging.getLogger(logger_name or self.__class__.__name__)
        self.setup_logger()

    def setup_logger(self):
        """Setup logging configuration"""
        if not self.logger.handlers:
            # Ensure logs directory exists

            log_dir = Path(settings.BASE_DIR) / "logs"
            log_dir.mkdir(exist_ok=True)

            handler = logging.FileHandler(log_dir / "etl.log")
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )

            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

    def execute_sql_query(
        self, query: str, params: Optional[Dict] = None
    ) -> pd.DataFrame:
        """Execute SQL query and return DataFrame"""
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(query, params or {})
            columns = [col[0] for col in cursor.description]
            data = cursor.fetchall()
            return pd.DataFrame(data, columns=columns)

    def cleanup_temp_files(self, folder_path: str = "./files"):
        """Clean up temporary files"""
        folder = Path(folder_path)
        if folder.exists():
            delete_all_files_in_folder(folder)
            self.logger.info(f"Cleaned up temporary files in: {folder}")
