"""Unit normalisation and documented conversions (applied only when the user approves)."""

from dataclasses import dataclass

from aqstudio.config import EXPECTED_UNITS, GAS_MOLECULAR_WEIGHT, MOLAR_VOLUME_L

_REPLACEMENTS = (
    ("µ", "u"),  # micro sign
    ("μ", "u"),  # Greek mu
    ("³", "3"),  # superscript three
    ("mcg", "ug"),
    ("^", ""),
    (" ", ""),
)


def normalize_unit(raw: str) -> str:
    """Normalise e.g. 'µg/m³', 'μg/m^3' and 'ug/m3' to 'ug/m3'."""
    unit = raw.strip().lower()
    for old, new in _REPLACEMENTS:
        unit = unit.replace(old, new)
    return unit


_MASS_TO_UG = {"ug/m3": 1.0, "mg/m3": 1000.0, "ng/m3": 0.001}  # micrograms per unit
_GAS_FRACTION_TO_UG = {"ppb": 1.0, "ppm": 1000.0}  # ppb of gas -> ug/m3 = ppb * MW / molar volume


@dataclass(frozen=True)
class Conversion:
    """A multiplication that turns a series' unit into the unit CPCB expects."""

    from_unit: str
    to_unit: str
    factor: float
    exact: bool


def conversion_for(pollutant: str, unit: str) -> Conversion | None:
    """The documented conversion into CPCB's unit, or None if there is no safe one."""
    target = EXPECTED_UNITS.get(pollutant)
    if target is None or unit in ("unknown", target):
        return None
    ug_per_target = 1000.0 if target == "mg/m3" else 1.0
    if unit in _MASS_TO_UG:
        return Conversion(unit, target, _MASS_TO_UG[unit] / ug_per_target, True)
    weight = GAS_MOLECULAR_WEIGHT.get(pollutant)
    if unit in _GAS_FRACTION_TO_UG and weight is not None:
        ug = _GAS_FRACTION_TO_UG[unit] * weight / MOLAR_VOLUME_L
        return Conversion(unit, target, ug / ug_per_target, False)
    return None
