"""Parser for long-format exports: one row per timestamp, one column per pollutant."""

import csv
import io

from aqstudio.config import MAX_UPLOAD_BYTES, MAX_UPLOAD_ROWS
from aqstudio.ingest.errors import IngestError
from aqstudio.schemas import RawTable


def parse_long_csv(text: str) -> RawTable:
    """Parse CSV text into a RawTable, enforcing size and row caps."""
    if len(text.encode("utf-8")) > MAX_UPLOAD_BYTES:
        raise IngestError("Upload exceeds the maximum file size.", "file_too_large")
    reader = csv.reader(io.StringIO(text))
    try:
        columns = [c.strip() for c in next(reader)]
    except StopIteration:
        raise IngestError("The file is empty.") from None
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if len(rows) > MAX_UPLOAD_ROWS:
        raise IngestError("Upload exceeds the maximum row count.", "file_too_large")
    if not rows:
        raise IngestError("The file has a header but no data rows.")
    return RawTable(columns=columns, rows=rows)
