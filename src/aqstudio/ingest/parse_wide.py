"""Parser for wide hourly grids: Year rows, Month-YYYY headers with 24 hour columns, day rows.

The grid carries no station or pollutant labels, so the user supplies them; nothing is guessed.
Grid hours are local clock hours and are written with an explicit IST offset.
"""

import calendar
import csv
import io
import re
from dataclasses import dataclass
from datetime import date

from aqstudio.config import MAX_UPLOAD_CELLS
from aqstudio.ingest.errors import IngestError
from aqstudio.schemas import RawTable

_MONTH_HEADER = re.compile(r"^\s*([A-Za-z]+)-(\d{4})\s*$")
_HOUR = re.compile(r"^\s*(\d{1,2}):\d{2}(?::\d{2})?\s*$")
_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_IST = "+05:30"


@dataclass(frozen=True)
class WideLabels:
    """What the grid measures, supplied by the user."""

    station: str
    pollutant: str
    unit: str


def wide_to_long(text: str, labels: WideLabels) -> tuple[RawTable, int]:
    """Convert a wide grid into a long table; returns it with the count of impossible dates."""
    rows: list[list[str]] = []
    hours: list[int] = []
    month: tuple[int, int] | None = None
    skipped = 0
    for line in text.splitlines():
        if not line.strip().strip('"').strip(","):
            continue  # blank and stray-quote spacer lines, which would break CSV quoting
        cells = [c.strip() for c in next(csv.reader([line]))]
        header = _MONTH_HEADER.match(cells[0])
        if header and header.group(1).lower() in _MONTHS:
            month = (int(header.group(2)), _MONTHS[header.group(1).lower()])
            hours = [int(m.group(1)) for c in cells[1:] if (m := _HOUR.match(c))]
            continue
        if month is None or not cells[0].isdigit():
            continue  # Year markers, notes and anything outside a month block
        year, mon = month
        day = int(cells[0])
        if not 1 <= day <= calendar.monthrange(year, mon)[1]:
            skipped += 1
            continue
        stamp = date(year, mon, day).isoformat()
        values = cells[1 : len(hours) + 1]
        rows.extend(
            [labels.station, f"{stamp}T{hour:02d}:00:00{_IST}", value]
            for hour, value in zip(hours, values, strict=False)
        )
        if len(rows) * 3 > MAX_UPLOAD_CELLS:
            raise IngestError("Upload has too many cells.", "file_too_large")
    if not rows:
        raise IngestError("No day rows were found under a Month-YYYY header in this grid.")
    columns = ["Station ID", "Timestamp", f"{labels.pollutant} ({labels.unit})"]
    return RawTable(columns=columns, rows=rows), skipped


def table_to_csv(table: RawTable) -> str:
    """Serialise a table back to CSV text so the rest of the pipeline treats it as a long file."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(table.columns)
    writer.writerows(table.rows)
    return out.getvalue()
