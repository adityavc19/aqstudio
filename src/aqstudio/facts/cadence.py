"""Detect whether readings are daily or hourly-or-finer."""

import pandas as pd

from aqstudio.config import DAILY_CADENCE_MIN_HOURS


def is_daily(frame: pd.DataFrame) -> bool:
    """True when the median spacing between valid readings of a series is about a day or more."""
    steps = (
        frame.sort_values("ts")
        .groupby(["station", "pollutant"])["ts"]
        .diff()
        .dt.total_seconds()
        .dropna()
        / 3600
    )
    return bool(len(steps)) and float(steps.median()) >= DAILY_CADENCE_MIN_HOURS
