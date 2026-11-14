"""Application settings and domain constants.

Domain constants (AQI breakpoints, plausibility ranges) are added with a cited
source in the phase that first uses them; none are guessed here.
"""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LOCAL_TZ = "Asia/Kolkata"  # IST, +05:30; all readings are converted to this zone.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_UPLOAD_ROWS = 200_000
RATE_LIMIT_PER_HOUR = 5  # LLM-backed requests per client IP per hour.
DAILY_CAP = 100  # LLM-backed requests per rolling 24h across all clients (protects API credits).
MIN_COVERAGE_PCT = 75.0  # below this an aggregate is labelled unreliable.


class Settings(BaseSettings):
    """Environment-backed settings; secrets are never logged or sent to clients."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_model: str = "claude-sonnet-5-5"
    session_secret: SecretStr = SecretStr("")
    database_path: str = "aqstudio.sqlite3"


MISSING_TOKENS = frozenset({"", "-", "*", "na", "nan", "none", "null"})
CEILING_SENTINEL = 500.0  # sensor-fault ceiling seen in KSPCB exports (see CLAUDE.md section 6).
CEILING_MIN_RUN = 4  # consecutive sentinel readings before it is treated as a fault.
STUCK_MIN_RUN = 8  # identical consecutive readings before a sensor is treated as stuck.
GAP_MIN_HOURS = 24.0  # silence between valid readings that counts as a gap.
NON_POLLUTANT_COLUMNS = frozenset({"station id", "state", "city", "station name", "timestamp"})

# CPCB National AQI (India). Concentration edges map to index edges INDEX_EDGES; the Severe
# band tops out at edge5 + (edge5 - edge4), the CPCB convention that reproduces the published
# PM2.5 worked example (150 ug/m3 -> 323). Units: ug/m3, except CO in mg/m3.
# SOURCE: CPCB AQI health breakpoints as reproduced at
# https://ies.gov.in/arthapedia/concept/national-air-quality-index .
# NOT YET VERIFIED against the CPCB PDF itself; verify before relying on these in production.
INDEX_EDGES = (0, 50, 100, 200, 300, 400, 500)
AQI_BREAKPOINTS: dict[str, tuple[float, float, float, float, float, float]] = {
    "PM10": (0, 50, 100, 250, 350, 430),
    "PM2.5": (0, 30, 60, 90, 120, 250),
    "NO2": (0, 40, 80, 180, 280, 400),
    "O3": (0, 50, 100, 168, 208, 748),
    "CO": (0, 1, 2, 10, 17, 34),
    "SO2": (0, 40, 80, 380, 800, 1600),
    "NH3": (0, 200, 400, 800, 1200, 1800),
}
AQI_CATEGORIES = (
    (50, "Good"),
    (100, "Satisfactory"),
    (200, "Moderate"),
    (300, "Poor"),
    (400, "Very Poor"),
    (500, "Severe"),
)
PARTICULATES = frozenset({"PM10", "PM2.5"})
POLLUTANT_ALIASES = {"OZONE": "O3", "PM25": "PM2.5", "PM2_5": "PM2.5"}
MIN_AQI_POLLUTANTS = 3  # SOURCE: same page; one of them must be PM2.5 or PM10.
MIN_DAY_HOURS = 16  # SOURCE: same page; minimum hours of data for a sub-index.
MIN_8H_HOURS = 6  # ASSUMPTION: valid hours needed inside an 8-hour window for CO and O3.
EIGHT_HOUR_POLLUTANTS = frozenset({"CO", "O3"})
