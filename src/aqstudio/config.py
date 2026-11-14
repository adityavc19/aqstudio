"""Application settings and domain constants.

Domain constants (AQI breakpoints, plausibility ranges) are added with a cited
source in the phase that first uses them; none are guessed here.
"""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LOCAL_TZ = "Asia/Kolkata"  # IST, +05:30; all readings are converted to this zone.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_UPLOAD_ROWS = 200_000
MIN_COVERAGE_PCT = 75.0  # below this an aggregate is labelled unreliable.


class Settings(BaseSettings):
    """Environment-backed settings; secrets are never logged or sent to clients."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_model: str = "claude-sonnet-5-5"
    session_secret: SecretStr = SecretStr("")
