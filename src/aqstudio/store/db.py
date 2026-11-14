"""SQLite access: one short-lived connection per operation, schema created on startup."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

_SCHEMA = """
CREATE TABLE IF NOT EXISTS uploads (
    id TEXT PRIMARY KEY, created_at REAL NOT NULL, detected_format TEXT NOT NULL, text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS briefs (
    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, created_at REAL NOT NULL, persona TEXT NOT NULL,
    status TEXT NOT NULL, stage TEXT, previous_id TEXT,
    brief_json TEXT, evidence_json TEXT, error_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_briefs_session ON briefs (session_id, created_at);
CREATE TABLE IF NOT EXISTS llm_cache (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class Database:
    """Opens connections to one SQLite file and ensures the schema exists."""

    def __init__(self, path: str) -> None:
        """Create tables if they do not exist."""
        self._path = path
        with self.connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection that commits on success and always closes."""
        conn = sqlite3.connect(self._path, timeout=5)
        try:
            with conn:
                yield conn
        finally:
            conn.close()
