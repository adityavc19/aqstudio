"""Application settings and domain constants.

Every constant with domain meaning lives here with its source or an explicit ASSUMPTION tag.
"""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LOCAL_TZ = "Asia/Kolkata"  # IST, +05:30; all readings are converted to this zone.
IST_OFFSET_MINUTES = 330
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_UPLOAD_ROWS = 200_000
MAX_UPLOAD_CELLS = 250_000  # rows x columns; keeps parsing time and memory bounded (about 40 s).
MAX_STATIONS = 100
MAX_ID_CHARS = 64
MAX_NAME_CHARS = 100
MAX_POLLUTANT_CHARS = 32
MAX_UNPARSEABLE_TS_FRACTION = 0.2  # more bad timestamps than this fails the upload loudly.
PREVIEW_ROWS = 10
LEDGER_SAMPLE_SIZE = 200  # ledger entries embedded in a Brief; full counts are in ledger_summary.

# Rate limits are generous so automated evaluators are not blocked; the provider spend cap
# is the hard backstop.
UPLOAD_RATE_LIMIT_PER_HOUR = 60  # uploads per client IP per hour.
UPLOAD_DAILY_CAP = 2000
UPLOAD_TTL_HOURS = 24.0  # stored upload text is deleted after this.
BRIEF_TTL_DAYS = 30.0
BRIEF_TIMEOUT_S = 600.0  # a brief still processing after this is reported as failed.
RATE_LIMIT_PER_HOUR = 20  # LLM-backed requests per client IP per hour.
DAILY_CAP = 300  # LLM-backed requests per rolling 24h across all clients.

# Reliability grading by coverage/score. ASSUMPTION: thresholds chosen for readability, not a
# published standard.
RELIABILITY_GRADES = ((90.0, "good"), (75.0, "fair"), (50.0, "poor"))
FLAG_PENALTY = {"critical": 15.0, "warn": 5.0, "info": 0.0}  # ASSUMPTION: score points per flag.

MISSING_TOKENS = frozenset({"", "-", "*", "na", "nan", "none", "null"})
CEILING_SENTINEL = 500.0  # sensor-fault ceiling seen in KSPCB exports (see CLAUDE.md section 6).
# ASSUMPTION: run lengths need both a reading count and a duration in hours, so the rules
# hold for 15-min, hourly and daily data alike.
CEILING_MIN_RUN = 4
CEILING_MIN_HOURS = 3.0
STUCK_MIN_RUN = 4
STUCK_MIN_HOURS = 8.0
ZERO_RUN_OK = frozenset({"RF", "TOT-RF", "RAINFALL"})  # constant zero is normal for rain gauges.
DAILY_CADENCE_MIN_HOURS = 20.0  # median spacing at or above this means daily readings.
AQI_COLUMNS = frozenset({"AQI"})  # a reported AQI column, checked against its inputs
ZERO_FILL_MIN_READINGS = 6  # ASSUMPTION: zeros while everything else is missing, this many times.
SCALE_HINTS = ("US AQI", "USAQI", "EPA")  # column names suggesting a non-CPCB AQI scale

# Patterns. ASSUMPTION: minimum data before a pattern is reported, so hints are not noise.
DIURNAL_MIN_DAYS = 2
TREND_MIN_DAYS_PER_HALF = 3
TREND_MIN_CHANGE_PCT = 10.0
CITYWIDE_SHARE = 2 / 3  # share of stations moving together that suggests a regional driver
PATTERN_POLLUTANTS = ("PM2.5", "PM10")
HOURLY_GRID_HOURS = 24
HOURLY_GRID_POLLUTANT = "PM2.5"
GAP_MIN_HOURS = 24.0  # ASSUMPTION: silence between valid readings that counts as a gap.
LAT_COLUMNS = frozenset({"latitude", "lat"})
LON_COLUMNS = frozenset({"longitude", "lon", "lng"})
NON_POLLUTANT_COLUMNS = frozenset(
    {"station id", "state", "city", "station name", "timestamp"} | LAT_COLUMNS | LON_COLUMNS
)
# ASSUMPTION: rough bounding box of India (lat_min, lon_min, lat_max, lon_max), used only to
# notice swapped latitude/longitude; coordinates are never invented or geocoded.
INDIA_BBOX = (6.0, 68.0, 37.5, 97.5)
MAX_LOCATION_ROWS = 2000

# ASSUMPTION: coarse physical plausibility ranges (inclusive) for Indian ambient monitoring;
# values outside are flagged, never deleted. Keys are canonical pollutant names.
PLAUSIBLE_RANGES: dict[str, tuple[float, float]] = {
    "PM2.5": (0.0, 1000.0),
    "PM10": (0.0, 2000.0),
    "AT": (-5.0, 50.0),
    "RH": (5.0, 100.0),
}

# Expected units after normalisation. SOURCE: CPCB AQI (ug/m3, CO in mg/m3). Other units are
# flagged and excluded, never silently converted.
EXPECTED_UNITS = {
    "PM2.5": "ug/m3",
    "PM10": "ug/m3",
    "NO2": "ug/m3",
    "SO2": "ug/m3",
    "O3": "ug/m3",
    "NH3": "ug/m3",
    "CO": "mg/m3",
}

# Gas ppb/ppm -> mass concentration uses molecular weight and the molar volume at 25 C, 1 atm
# (24.45 L/mol). This is approximate (real temperature and pressure differ) and is only ever
# applied after the user approves it.
MOLAR_VOLUME_L = 24.45
GAS_MOLECULAR_WEIGHT = {"NO2": 46.0055, "SO2": 64.066, "O3": 47.9982, "NH3": 17.031, "CO": 28.010}

# CPCB National AQI (India). Concentration edges map to index edges INDEX_EDGES; the Severe
# band tops out at edge5 + (edge5 - edge4), the CPCB convention that reproduces the published
# PM2.5 worked example (150 ug/m3 -> 323). Units: ug/m3, except CO in mg/m3.
# SOURCE: "AQI Category, Pollutants and Health Breakpoints", Government of India press release
# (PIB) launching the National AQI, 17 Oct 2014: https://www.pib.gov.in/newsite/printrelease.aspx?relid=110654
# (CPCB final report: https://app.cpcbccr.com/ccr_docs/FINAL-REPORT_AQI_.pdf). Values verified
# against that table on 14 Nov 2026. The official table gives Severe only as "430+" etc., so the
# Severe upper edge here is a convention. Known limitation: the official table marks O3's Very
# Poor and Severe bands as one-hourly; this code uses 8-hour values for every O3 band.
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

# PM2.5/PM10 ratio hints. ASSUMPTION: coarse rules of thumb, presented as hints only.
PM_RATIO_COMBUSTION = 0.6
PM_RATIO_DUST = 0.4
HOTSPOT_MIN_STATIONS = 2

SARVAM_BASE_URL = "https://api.sarvam.ai"  # OpenAI-compatible chat API lives under /v2.
SARVAM_MAX_TOKENS = 6000  # reasoning tokens share this budget, so keep it generous.
SARVAM_TIMEOUT_S = 120.0

# Advisory languages (Sarvam Translate codes) and reading levels.
ADVISORY_LANGUAGES = {
    "en": "en-IN",
    "hi": "hi-IN",
    "kn": "kn-IN",
    "mr": "mr-IN",
    "bn": "bn-IN",
    "ml": "ml-IN",
}
READING_LEVELS = ("simple", "standard")
SARVAM_TRANSLATE_MODEL = "mayura:v1"
SARVAM_TTS_MODEL = "bulbul:v3"
TTS_MAX_CHARS = 1500  # ASSUMPTION: kept under Bulbul's per-request text limit.
ADVISORY_DISCLAIMER = (
    "General guidance only, based on the uploaded data. For any health concern contact your "
    "doctor or local health authority. AI-written; translations are machine-made, please review."
)

# Live public data (OpenAQ v3). Only regulatory monitors that reported recently are used.
OPENAQ_BASE_URL = "https://api.openaq.org/v3"
LIVE_RADIUS_M = 25000  # OpenAQ's maximum search radius
LIVE_MAX_AGE_HOURS = 3.0  # ASSUMPTION: older than this, a station is not "now"
LIVE_STATIONS = 3  # nearest live stations shown
LIVE_WINDOW_HOURS = 24  # CPCB real-time AQI uses a rolling 24-hour window
LIVE_CACHE_SECONDS = 1800
LIVE_RATE_LIMIT_PER_HOUR = 30
LIVE_DAILY_CAP = 1000
OPENAQ_PARAMETERS = {
    "pm25": "PM2.5",
    "pm10": "PM10",
    "no2": "NO2",
    "so2": "SO2",
    "o3": "O3",
    "co": "CO",
    "nh3": "NH3",
}
# SOURCE: "Associated Health Impacts" in the same PIB release (17 Oct 2014) as AQI_BREAKPOINTS.
HEALTH_IMPACTS = {
    "Good": "Minimal impact.",
    "Satisfactory": "May cause minor breathing discomfort to sensitive people.",
    "Moderate": "May cause breathing discomfort to people with lung disease such as asthma, and "
    "discomfort to people with heart disease, children and older adults.",
    "Poor": "May cause breathing discomfort to people on prolonged exposure, and discomfort to "
    "people with heart disease.",
    "Very Poor": "May cause respiratory illness to people on prolonged exposure. Effect may be "
    "more pronounced in people with lung and heart diseases.",
    "Severe": "May cause respiratory impact even on healthy people, and serious health impacts on "
    "people with lung or heart disease. Impacts may be felt even during light physical activity.",
}

# Verification and comparison.
VERIFIER_DROP_UNVERIFIED = False  # False: show unverified claims, visibly marked.
# A claim citing a poor/unreliable fact must contain one of these hedges.
HEDGE_WORDS = (
    "unreliab",
    "insufficient",
    "low coverage",
    "limited",
    "caution",
    "poor",
    "incomplete",
    "partial",
    "not reliable",
    "gap",
    "fault",
    "cannot",
    "uncertain",
    "doubt",
)
MAX_FACTS_TO_LLM = 150  # facts sent to the model; the rest stay in the brief but unnarrated.
MAX_FLAG_FACTS = 20
COMPARE_MIN_CHANGE_PCT = 5.0  # ASSUMPTION: relative change below this is not reported.
COVERAGE_SHIFT_PTS = 10.0  # ASSUMPTION: coverage change that explains a value change.


class Settings(BaseSettings):
    """Environment-backed settings; secrets are never logged or sent to clients."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_model: str = "claude-sonnet-5-5"
    session_secret: SecretStr = SecretStr("")
    refresh_token: SecretStr = SecretStr("")
    sarvam_api_key: SecretStr = SecretStr("")
    sarvam_model: str = "deepseekv4.1-flash-1017"
    llm_provider: str = "auto"  # auto | anthropic | sarvam
    database_path: str = "aqstudio.sqlite3"
    frontend_dir: str = "frontend"
    cookie_secure: bool = False
    trusted_ip_header: str = ""
    openaq_api_key: SecretStr = SecretStr(
        ""
    )  # e.g. CF-Connecting-IP on Render; empty trusts no header
