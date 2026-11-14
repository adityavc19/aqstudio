"""Unit normalisation: spelling variants collapse to one canonical form, nothing is converted."""

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
