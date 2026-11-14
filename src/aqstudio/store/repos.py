"""Repositories for uploads and briefs. Parameterised SQL only."""

import json
import time
import uuid
from dataclasses import dataclass

from aqstudio.schemas import Brief, BriefStatus, ErrorBody, Persona
from aqstudio.store.db import Database


@dataclass(frozen=True)
class StoredUpload:
    """A saved upload."""

    id: str
    detected_format: str
    text: str


@dataclass(frozen=True)
class StoredBrief:
    """A brief row: status plus the finished brief, evidence rows or error when present."""

    id: str
    persona: Persona
    created_at: float
    status: BriefStatus
    stage: str | None
    previous_id: str | None
    brief: Brief | None
    evidence_rows: dict[str, dict[str, str]]
    error: ErrorBody | None


class UploadRepo:
    """Persists raw upload text so briefs can be built from a confirmed mapping later."""

    def __init__(self, db: Database) -> None:
        """Keep the database handle."""
        self._db = db

    def create(self, detected_format: str, text: str) -> str:
        """Store an upload and return its unguessable id."""
        upload_id = uuid.uuid4().hex
        with self._db.connect() as conn:
            conn.execute(
                "INSERT INTO uploads (id, created_at, detected_format, text) VALUES (?, ?, ?, ?)",
                (upload_id, time.time(), detected_format, text),
            )
        return upload_id

    def get(self, upload_id: str) -> StoredUpload | None:
        """Fetch an upload by id."""
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT id, detected_format, text FROM uploads WHERE id = ?", (upload_id,)
            ).fetchone()
        return StoredUpload(*row) if row else None


class BriefRepo:
    """Persists brief state and results."""

    def __init__(self, db: Database) -> None:
        """Keep the database handle."""
        self._db = db

    def create_processing(self, session_id: str, persona: Persona, previous_id: str | None) -> str:
        """Insert a brief in the processing state and return its id."""
        brief_id = uuid.uuid4().hex
        with self._db.connect() as conn:
            conn.execute(
                "INSERT INTO briefs (id, session_id, created_at, persona, status, stage,"
                " previous_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    brief_id,
                    session_id,
                    time.time(),
                    persona.value,
                    "processing",
                    "queued",
                    previous_id,
                ),
            )
        return brief_id

    def set_stage(self, brief_id: str, stage: str) -> None:
        """Record the pipeline stage currently running."""
        with self._db.connect() as conn:
            conn.execute("UPDATE briefs SET stage = ? WHERE id = ?", (stage, brief_id))

    def save_ready(self, brief: Brief, evidence_rows: dict[str, dict[str, str]]) -> None:
        """Store a finished brief and its evidence rows."""
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE briefs SET status = 'ready', stage = NULL, brief_json = ?,"
                " evidence_json = ? WHERE id = ?",
                (brief.model_dump_json(), json.dumps(evidence_rows), brief.id),
            )

    def save_failed(self, brief_id: str, error: ErrorBody) -> None:
        """Store a failure so the client can show an honest error."""
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE briefs SET status = 'failed', stage = NULL, error_json = ? WHERE id = ?",
                (error.model_dump_json(), brief_id),
            )

    def get(self, brief_id: str) -> StoredBrief | None:
        """Fetch one brief by id."""
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT id, persona, created_at, status, stage, previous_id, brief_json,"
                " evidence_json, error_json FROM briefs WHERE id = ?",
                (brief_id,),
            ).fetchone()
        return _hydrate(row) if row else None

    def list_for_session(self, session_id: str, limit: int = 50) -> list[StoredBrief]:
        """List this browser session's briefs, newest first."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT id, persona, created_at, status, stage, previous_id, NULL, NULL, NULL"
                " FROM briefs WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [_hydrate(r) for r in rows]


def _hydrate(
    row: tuple[str, str, float, str, str | None, str | None, str | None, str | None, str | None],
) -> StoredBrief:
    """Convert a database row into a StoredBrief."""
    brief_id, persona, created, status, stage, previous, brief_json, evidence_json, error_json = row
    return StoredBrief(
        id=brief_id,
        persona=Persona(persona),
        created_at=created,
        status=BriefStatus(status),
        stage=stage,
        previous_id=previous,
        brief=Brief.model_validate_json(brief_json) if brief_json else None,
        evidence_rows=json.loads(evidence_json) if evidence_json else {},
        error=ErrorBody.model_validate_json(error_json) if error_json else None,
    )
