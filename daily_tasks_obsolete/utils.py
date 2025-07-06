import pyarrow.parquet as pq
import logging
from pathlib import Path
from datetime import timezone, date, datetime


def setup_logger(
    name: str = __name__, log_file: str = "my_sync_log.log", level=logging.INFO
) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid adding multiple handlers if logger is already configured
    if not logger.handlers:

        # Create formatter
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

        # Console handler
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        logger.addHandler(ch)

        # Ensure log directory exists
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)

        # File handler
        fh = logging.FileHandler(log_file)
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    return logger


def get_parquet_row_count(file_path):
    parquet_file = pq.ParquetFile(file_path)
    return parquet_file.metadata.num_rows


def make_utc(dt):
    if not dt:
        return None
    if isinstance(dt, date) and not isinstance(dt, datetime):
        # Convert date → datetime
        dt = datetime(dt.year, dt.month, dt.day)
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def delete_all_files_in_folder(folder: Path):
    """
    Deletes all files (not directories) in the given Path object folder.

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
