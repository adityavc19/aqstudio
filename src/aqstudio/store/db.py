"""SQLite access: one short-lived connection per operation, schema created on startup."""

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager

from aqstudio.config import BRIEF_TTL_DAYS, UPLOAD_TTL_HOURS

_SCHEMA = """
CREATE TABLE IF NOT EXISTS uploads (
    id TEXT PRIMARY KEY, created_at REAL NOT NULL, detected_format TEXT NOT NULL, text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS briefs (
    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, created_at REAL NOT NULL, persona TEXT NOT NULL,
    status TEXT NOT NULL, stage TEXT, previous_id TEXT,
    brief_json TEXT, evidence_json TEXT, error_json TEXT,
    status_line TEXT, worst_category TEXT, unreliable_count INTEGER
);
CREATE INDEX IF NOT EXISTS idx_briefs_session ON briefs (session_id, created_at);
CREATE TABLE IF NOT EXISTS llm_cache (
    key TEXT PRIMARY KEY, value TEXT NOT NULL, created_at REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_uploads_created ON uploads (created_at);
CREATE INDEX IF NOT EXISTS idx_briefs_created ON briefs (created_at);
"""


_CACHE_MIGRATION = "ALTER TABLE llm_cache ADD COLUMN created_at REAL NOT NULL DEFAULT 0"
_MIGRATIONS = {
    "status_line": "ALTER TABLE briefs ADD COLUMN status_line TEXT",
    "worst_category": "ALTER TABLE briefs ADD COLUMN worst_category TEXT",
    "unreliable_count": "ALTER TABLE briefs ADD COLUMN unreliable_count INTEGER",
}


class Database:
    """Opens connections to one SQLite file and ensures the schema exists."""

    def __init__(self, path: str) -> None:
        """Create tables if they do not exist."""
        self._path = path
        with self.connect() as conn:
            conn.executescript(_SCHEMA)
            existing = {row[1] for row in conn.execute("PRAGMA table_info(briefs)")}
            for column, statement in _MIGRATIONS.items():
                if column not in existing:
                    conn.execute(statement)
            if "created_at" not in {r[1] for r in conn.execute("PRAGMA table_info(llm_cache)")}:
                conn.execute(_CACHE_MIGRATION)

    def purge_expired(self, now: float) -> None:
        """Delete old uploads, briefs and cached LLM results so storage stays bounded."""
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM uploads WHERE created_at < ?", (now - UPLOAD_TTL_HOURS * 3600,)
            )
            conn.execute("DELETE FROM briefs WHERE created_at < ?", (now - BRIEF_TTL_DAYS * 86400,))
            conn.execute(
                "DELETE FROM llm_cache WHERE created_at < ?", (now - BRIEF_TTL_DAYS * 86400,)
            )

    def cache_get(self, key: str) -> str | None:
        """Return a cached JSON value, if present."""
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM llm_cache WHERE key = ?", (key,)).fetchone()
        return str(row[0]) if row else None

    def cache_put(self, key: str, value: str) -> None:
        """Store a JSON value under a key."""
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO llm_cache (key, value, created_at) VALUES (?, ?, ?)",
                (key, value, time.time()),
            )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection that commits on success and always closes."""
        conn = sqlite3.connect(self._path, timeout=5)
        try:
            with conn:
                yield conn
        finally:
            conn.close()
