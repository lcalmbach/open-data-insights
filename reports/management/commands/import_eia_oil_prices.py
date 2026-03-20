from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction


DEFAULT_SOURCE = "eia_pet_pri_spt_s1_d"
WORKBOOK_DEFAULT = Path("work/oil/PET_PRI_SPT_S1_D.xls")
XML_NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


@dataclass(frozen=True)
class SeriesConfig:
    column: str
    commodity: str
    commodity_code: str
    market: str
    unit: str
    source_key: str
    description: str


SERIES = [
    SeriesConfig(
        column="B",
        commodity="WTI",
        commodity_code="RWTC",
        market="Cushing, OK",
        unit="barrel",
        source_key="RWTC",
        description="Cushing, OK WTI Spot Price FOB (Dollars per Barrel)",
    ),
    SeriesConfig(
        column="C",
        commodity="Brent Crude",
        commodity_code="RBRTE",
        market="Europe",
        unit="barrel",
        source_key="RBRTE",
        description="Europe Brent Spot Price FOB (Dollars per Barrel)",
    ),
]


def _excel_serial_to_date(serial_value: str) -> date:
    serial = int(float(serial_value))
    return date(1899, 12, 30) + timedelta(days=serial)


def _convert_xls_to_xlsx(source_path: Path) -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(
            [
                "libreoffice",
                "--headless",
                "--convert-to",
                "xlsx",
                "--outdir",
                tmpdir,
                str(source_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        converted_path = Path(tmpdir) / f"{source_path.stem}.xlsx"
        if not converted_path.exists():
            raise CommandError(f"LibreOffice did not produce {converted_path.name}")
        target_dir = Path(tempfile.mkdtemp(prefix="eia_oil_"))
        persisted_path = target_dir / converted_path.name
        persisted_path.write_bytes(converted_path.read_bytes())
        return persisted_path


def _resolve_xlsx_path(source_path: Path) -> Path:
    if source_path.suffix.lower() == ".xlsx":
        return source_path
    if source_path.suffix.lower() != ".xls":
        raise CommandError(f"Unsupported workbook format: {source_path.suffix}")
    return _convert_xls_to_xlsx(source_path)


def _load_shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(text_node.text or "" for text_node in item.iterfind(".//a:t", XML_NS))
        for item in shared_root.findall("a:si", XML_NS)
    ]


def _sheet_path_by_name(archive: ZipFile, sheet_name: str) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_map = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in relationships
    }
    for sheet in workbook.find("a:sheets", XML_NS):
        if sheet.attrib["name"] == sheet_name:
            rel_id = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
            return f"xl/{rel_map[rel_id]}"
    raise CommandError(f"Unable to find sheet '{sheet_name}' in workbook.")


def _iter_sheet_rows(archive: ZipFile, sheet_path: str, shared_strings: list[str]):
    root = ET.fromstring(archive.read(sheet_path))
    sheet_data = root.find("a:sheetData", XML_NS)
    if sheet_data is None:
        return
    for row in sheet_data.findall("a:row", XML_NS):
        values: dict[str, str] = {}
        for cell in row.findall("a:c", XML_NS):
            reference = cell.attrib.get("r", "")
            column = "".join(ch for ch in reference if ch.isalpha())
            value_node = cell.find("a:v", XML_NS)
            if not column or value_node is None:
                continue
            value = value_node.text or ""
            if cell.attrib.get("t") == "s":
                value = shared_strings[int(value)]
            values[column] = value
        if values:
            yield int(row.attrib["r"]), values


def _load_daily_rows(workbook_path: Path) -> dict[str, list[tuple[date, Decimal]]]:
    result = {series.commodity_code: [] for series in SERIES}
    with ZipFile(workbook_path) as archive:
        shared_strings = _load_shared_strings(archive)
        sheet_path = _sheet_path_by_name(archive, "Data 1")
        for row_number, values in _iter_sheet_rows(archive, sheet_path, shared_strings):
            if row_number < 4:
                continue
            serial_value = values.get("A")
            if not serial_value:
                continue
            price_date = _excel_serial_to_date(serial_value)
            for series in SERIES:
                raw_price = values.get(series.column)
                if not raw_price:
                    continue
                result[series.commodity_code].append((price_date, Decimal(raw_price)))
    return result


def _aggregate_monthly_rows(series: SeriesConfig, daily_rows: list[tuple[date, Decimal]]) -> list[dict]:
    monthly_prices: dict[tuple[int, int], list[Decimal]] = {}
    for price_date, price in daily_rows:
        monthly_prices.setdefault((price_date.year, price_date.month), []).append(price)

    rows: list[dict] = []
    for year, month in sorted(monthly_prices):
        values = monthly_prices[(year, month)]
        average_price = (sum(values) / Decimal(len(values))).quantize(Decimal("0.000001"))
        rows.append(
            {
                "commodity": series.commodity,
                "commodity_code": series.commodity_code,
                "year": year,
                "month": month,
                "market": series.market,
                "price": average_price,
                "currency": "USD",
                "unit": series.unit,
                "quote_type": "monthly_average",
                "source": DEFAULT_SOURCE,
                "price_timestamp": datetime(year, month, 1, tzinfo=UTC),
                "metadata": {
                    "source_key": series.source_key,
                    "series_description": series.description,
                    "aggregation": "monthly_average",
                    "daily_points": len(values),
                    "period_month": f"{year:04d}-{month:02d}",
                },
            }
        )
    return rows


def _upsert_rows(rows: list[dict]) -> int:
    count = 0
    with transaction.atomic():
        with connection.cursor() as cursor:
            for row in rows:
                cursor.execute(
                    """
                    INSERT INTO opendata.commodity_price (
                        commodity,
                        commodity_code,
                        year,
                        month,
                        market,
                        price,
                        currency,
                        unit,
                        quote_type,
                        source,
                        price_timestamp,
                        metadata
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (commodity_code, source, price_timestamp)
                    WHERE commodity_code IS NOT NULL
                    DO UPDATE SET
                        commodity = EXCLUDED.commodity,
                        year = EXCLUDED.year,
                        month = EXCLUDED.month,
                        market = EXCLUDED.market,
                        price = EXCLUDED.price,
                        currency = EXCLUDED.currency,
                        unit = EXCLUDED.unit,
                        quote_type = EXCLUDED.quote_type,
                        metadata = EXCLUDED.metadata,
                        retrieved_at = NOW()
                    """,
                    [
                        row["commodity"],
                        row["commodity_code"],
                        row["year"],
                        row["month"],
                        row["market"],
                        row["price"],
                        row["currency"],
                        row["unit"],
                        row["quote_type"],
                        row["source"],
                        row["price_timestamp"],
                        json.dumps(row["metadata"]),
                    ],
                )
                count += 1
    return count


class Command(BaseCommand):
    help = "Import monthly WTI and Brent price history from the EIA workbook into opendata.commodity_price."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            type=str,
            default=str(WORKBOOK_DEFAULT),
            help="Path to the EIA workbook (.xls or .xlsx).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and aggregate without writing to the database.",
        )

    def handle(self, *args, **options):
        source_path = Path(options["source"]).expanduser()
        if not source_path.exists():
            raise CommandError(f"Workbook not found: {source_path}")

        workbook_path = _resolve_xlsx_path(source_path)
        daily_rows = _load_daily_rows(workbook_path)

        total_rows = 0
        for series in SERIES:
            monthly_rows = _aggregate_monthly_rows(series, daily_rows[series.commodity_code])
            total_rows += len(monthly_rows)
            if options["dry_run"]:
                self.stdout.write(
                    self.style.WARNING(
                        f"Dry run: prepared {len(monthly_rows)} monthly rows for {series.commodity_code}."
                    )
                )
                continue
            written = _upsert_rows(monthly_rows)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Imported {written} monthly rows for {series.commodity_code}."
                )
            )

        if options["dry_run"]:
            self.stdout.write(self.style.SUCCESS(f"Dry run complete. Prepared {total_rows} rows."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Import complete. Wrote {total_rows} rows."))
