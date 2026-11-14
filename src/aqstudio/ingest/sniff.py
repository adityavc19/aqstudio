"""Format detection for uploaded text."""

import re
from enum import StrEnum


class DetectedFormat(StrEnum):
    """Supported and recognised-but-unsupported input shapes."""

    LONG_CSV = "long_csv"
    WIDE_GRID = "wide_grid"
    UNKNOWN = "unknown"


_WIDE_MARKER = re.compile(r"^\s*(Year\s*,\s*\d{4}|[A-Za-z]+-\d{4}\s*,\s*00:00:00)", re.MULTILINE)


def detect_format(text: str) -> DetectedFormat:
    """Classify text as a long CSV, a wide hourly grid, or unknown."""
    if _WIDE_MARKER.search(text):
        return DetectedFormat.WIDE_GRID
    header = next((line for line in text.splitlines() if line.strip()), "").lower()
    if "station id" in header and "timestamp" in header:
        return DetectedFormat.LONG_CSV
    return DetectedFormat.UNKNOWN
