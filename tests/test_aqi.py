import pytest

from aqstudio.facts.aqi import category_for, overall_aqi, sub_index


def test_sub_index_matches_cpcb_worked_examples() -> None:
    assert sub_index("PM2.5", 45) == pytest.approx(75)
    assert sub_index("PM2.5", 150) == pytest.approx(323.08, abs=0.01)


def test_worst_sub_index_sets_aqi() -> None:
    result = overall_aqi({"PM2.5": 45, "SO2": 20, "NO2": 20})
    assert result is not None
    assert (result.aqi, result.dominant, result.category) == (75, "PM2.5", "Satisfactory")


def test_insufficient_data_returns_none() -> None:
    assert overall_aqi({"PM2.5": 45, "NO2": 38}) is None  # only two pollutants
    assert overall_aqi({"NO2": 38, "SO2": 10, "CO": 1}) is None  # no particulate


def test_extreme_value_capped_and_categories() -> None:
    assert sub_index("PM10", 5000) == 500
    assert category_for(50) == "Good" and category_for(401) == "Severe"


def test_breakpoints_match_the_official_cpcb_table() -> None:
    # Lower edges of each category, from the PIB release of 17 Oct 2014 (relid 110654).
    from aqstudio.config import AQI_BREAKPOINTS

    official = {
        "PM10": (0, 50, 100, 250, 350, 430),
        "PM2.5": (0, 30, 60, 90, 120, 250),
        "NO2": (0, 40, 80, 180, 280, 400),
        "O3": (0, 50, 100, 168, 208, 748),
        "CO": (0, 1, 2, 10, 17, 34),
        "SO2": (0, 40, 80, 380, 800, 1600),
        "NH3": (0, 200, 400, 800, 1200, 1800),
    }
    assert official == AQI_BREAKPOINTS
