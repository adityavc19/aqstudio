"""Read report-style PDFs (e.g. KSPCB monthly reports): one station table per page.

Each table page has a title "<Station> - <Month> <Year>", a header row starting with "Date",
a row of subscripts ("10 2.5 2 2 3 3" for PM10, PM2.5, SO2 ...), a units row, then one row per
DD-MM-YYYY date, and Minimum/Maximum/Average summary rows, which are not data and are skipped.
"""

import csv
import io
import re

import pdfplumber
from pdfminer.pdfparser import PDFSyntaxError
from pdfplumber.utils.exceptions import PdfminerException

from aqstudio.ingest.errors import IngestError

MAX_PDF_PAGES = 60
_TITLE = re.compile(r"^(?P<station>.+?)\s+[–-]\s+[A-Za-z]+\s+\d{4}\s*$")
_DATE_ROW = re.compile(r"^(\d{2})-(\d{2})-(\d{4})\s+(.*)$")
_SUBSCRIPT = re.compile(r"^[\d.\s]+$")
_TAKES_SUBSCRIPT = {"PM", "SO", "NO", "O", "NH"}
_NAME_SYNONYMS = {"HR": "RH"}  # the same measure is spelled differently on some pages
_UNIT_SYNONYMS = {"oC": "°C", "Degree": "degree", "µg/m3": "µg/m³", "mg/m3": "mg/m³"}
_IST_MIDNIGHT = "T00:00:00+05:30"  # report dates are local calendar days


def _columns(header: str, subscripts: str) -> list[str]:
    """Rebuild pollutant names whose subscripts were printed on the next line."""
    words = header.split()[1:]  # drop "Date"
    merged: list[str] = []
    for word in words:
        if word == "H" and merged and merged[-1] == "R":
            merged[-1] = "RH"  # "R H" is relative humidity split by the layout
        else:
            merged.append(word)
    subs = iter(subscripts.split())
    named = [t + next(subs, "") if t in _TAKES_SUBSCRIPT else t for t in merged]
    return [_NAME_SYNONYMS.get(n, n) for n in named]


def _station_rows(lines: list[str]) -> tuple[str, list[str], list[dict[str, str]], int]:
    """Parse one table page: station, column labels with units, date rows, skipped rows."""
    title = next((m for line in lines if (m := _TITLE.match(line))), None)
    start = next((i for i, line in enumerate(lines) if line.startswith("Date ")), None)
    if title is None or start is None or start + 2 >= len(lines):
        return "", [], [], 0
    has_subs = bool(_SUBSCRIPT.match(lines[start + 1]))
    columns = _columns(lines[start], lines[start + 1] if has_subs else "")
    units = [_UNIT_SYNONYMS.get(u, u) for u in lines[start + 2 if has_subs else start + 1].split()]
    measured = [c for c in columns if c != "AQI"]
    labels = {
        col: f"{col} ({units[i]})" if len(units) == len(measured) else col
        for i, col in enumerate(measured)
    }
    labels["AQI"] = "AQI"
    rows: list[dict[str, str]] = []
    skipped = 0
    for line in lines[start + 1 :]:
        match = _DATE_ROW.match(line)
        if not match:
            continue
        day, month, year, rest = match.groups()
        values = rest.split()
        if len(values) != len(columns):
            skipped += 1
            continue
        row = {"Timestamp": f"{year}-{month}-{day}{_IST_MIDNIGHT}"}
        row.update({labels[c]: v for c, v in zip(columns, values, strict=True)})
        rows.append(row)
    return title.group("station").strip(), list(labels.values()), rows, skipped


def report_text_to_csv(pages: list[str]) -> tuple[str, int]:
    """Turn the text of report pages into one long CSV; returns it and the skipped-row count."""
    header: list[str] = []
    records: list[dict[str, str]] = []
    skipped = 0
    for text in pages:
        station, labels, rows, bad = _station_rows(text.splitlines())
        skipped += bad
        if not station:
            continue
        header.extend(label for label in labels if label not in header)
        records.extend({"Station ID": station, **row} for row in rows)
    if not records:
        raise IngestError("No station data tables were found in this PDF.")
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=["Station ID", "Timestamp", *header], restval="")
    writer.writeheader()
    writer.writerows(records)
    return out.getvalue(), skipped


def pdf_to_csv(data: bytes) -> str:
    """Extract text from a report PDF (text layer only, no OCR) and convert it."""
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if len(pdf.pages) > MAX_PDF_PAGES:
                raise IngestError(f"PDFs are limited to {MAX_PDF_PAGES} pages.", "file_too_large")
            pages = [page.extract_text() or "" for page in pdf.pages]
    except (PdfminerException, PDFSyntaxError, ValueError, KeyError) as exc:
        raise IngestError("This file is not a readable PDF.") from exc
    text, _ = report_text_to_csv(pages)
    return text
