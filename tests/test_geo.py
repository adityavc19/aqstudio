import pytest

from aqstudio.geo import check_coordinates


@pytest.mark.parametrize(
    ("lat", "lon", "problem"),
    [
        ("12.97", "77.59", None),
        ("", "", "missing"),
        ("12.97", "", "invalid"),
        ("abc", "77.5", "invalid"),
        ("0", "0", "invalid"),
        ("nan", "77", "invalid"),
        ("95", "200", "invalid"),
        ("77.59", "12.97", "swapped"),
        ("-200", "10", "invalid"),
    ],
)
def test_check_coordinates(lat: str, lon: str, problem: str | None) -> None:
    assert check_coordinates(lat, lon).problem == problem


def test_valid_pair_returns_floats_and_swapped_is_not_silently_fixed() -> None:
    ok = check_coordinates("12.97", "77.59")
    assert (ok.lat, ok.lon) == (12.97, 77.59)
    swapped = check_coordinates("77.59", "12.97")
    assert swapped.problem == "swapped" and (swapped.lat, swapped.lon) == (77.59, 12.97)
