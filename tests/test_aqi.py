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
