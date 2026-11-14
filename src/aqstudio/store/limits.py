"""SQLite-backed per-IP rate limit and global daily cap for LLM-backed requests."""

import sqlite3
import time
from collections.abc import Callable

from pydantic import BaseModel

_HOUR = 3600.0
_DAY = 86400.0


class LimitDecision(BaseModel):
    """Whether a request may proceed, and why not if it may not."""

    allowed: bool
    reason: str = ""


class UsageLimiter:
    """Counts LLM-backed requests; the clock is injectable for tests."""

    def __init__(
        self,
        db_path: str,
        per_ip_per_hour: int,
        daily_cap: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Open the database and create the hits table if needed."""
        self._db_path = db_path
        self._per_ip = per_ip_per_hour
        self._daily_cap = daily_cap
        self._clock = clock
        with self._connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS hits (ts REAL NOT NULL, ip TEXT NOT NULL)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_hits_ip_ts ON hits (ip, ts)")

    def _connect(self) -> sqlite3.Connection:
        """Open a short-lived connection (SQLite handles cross-thread safety per connection)."""
        return sqlite3.connect(self._db_path, timeout=5)

    def check_and_record(self, ip: str) -> LimitDecision:
        """Record the request and allow it, unless the IP or global limit is reached."""
        now = self._clock()
        with self._connect() as conn:
            conn.execute("DELETE FROM hits WHERE ts < ?", (now - _DAY,))
            total = conn.execute("SELECT COUNT(*) FROM hits").fetchone()[0]
            if total >= self._daily_cap:
                return LimitDecision(
                    allowed=False,
                    reason="The daily request limit for this service has been reached. "
                    "Please try again tomorrow.",
                )
            recent = conn.execute(
                "SELECT COUNT(*) FROM hits WHERE ip = ? AND ts >= ?", (ip, now - _HOUR)
            ).fetchone()[0]
            if recent >= self._per_ip:
                return LimitDecision(
                    allowed=False,
                    reason="Too many requests from your address. Please try again later.",
                )
            conn.execute("INSERT INTO hits (ts, ip) VALUES (?, ?)", (now, ip))
        return LimitDecision(allowed=True)
