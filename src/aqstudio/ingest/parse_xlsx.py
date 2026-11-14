"""Read the first non-empty sheet of an .xlsx file as CSV text (values only, never formulas)."""

import csv
import io
from datetime import date, datetime, time
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from aqstudio.config import MAX_UPLOAD_CELLS
from aqstudio.ingest.errors import IngestError


def _cell(value: object) -> str:
    """Render a cell as text; dates become ISO strings, empty cells become empty strings."""
    if value is None:
        return ""
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    return str(value)


def xlsx_to_csv(data: bytes) -> str:
    """Convert the first sheet with data to CSV text. Macros and formulas are never evaluated."""
    try:
        # read_only streams rows; data_only returns cached values, never formulas.
        book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except (BadZipFile, InvalidFileException, KeyError, ValueError) as exc:
        raise IngestError("This file is not a readable .xlsx workbook.") from exc
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    try:
        for sheet in book.worksheets:
            cells = 0
            for row in sheet.iter_rows(values_only=True):
                values = [_cell(v) for v in row]
                if not any(values):
                    continue
                cells += len(values)
                if cells > MAX_UPLOAD_CELLS:
                    raise IngestError("Upload has too many cells.", "file_too_large")
                writer.writerow(values)
            if out.tell():
                return out.getvalue()
    finally:
        book.close()
    raise IngestError("The workbook has no data.")
