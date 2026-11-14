from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from aqstudio.schemas import Reading


def test_reading_allows_missing_value_but_requires_tz() -> None:
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    reading = Reading(
        station_id="s1",
        ts=ts,
        pollutant="PM2.5",
        value=None,
        unit="ug/m3",
        row_ref="r1",
    )
    assert reading.value is None
    with pytest.raises(ValidationError):
        Reading(
            station_id="s1",
            ts=datetime(2024, 1, 1),
            pollutant="PM2.5",
            value=1.0,
            unit="ug/m3",
            row_ref="r1",
        )
