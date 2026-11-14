"""Repositories for uploads and briefs. Parameterised SQL only."""

import json
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Any

from aqstudio.schemas import Brief, BriefStatus, BriefSummary, ErrorBody, Persona
from aqstudio.store.db import Database


@dataclass(frozen=True)
class StoredUpload:
    """A saved upload."""

    id: str
    detected_format: str
    text: str


@dataclass(frozen=True)
class BriefListRow:
    """Metadata-only row for listing; never carries the brief JSON."""

    id: str
    persona: Persona
    created_at: float
    status_line: str | None
    worst_category: str | None
    unreliable_count: int | None


@dataclass(frozen=True)
class StoredBrief:
    """A brief row: status plus the finished brief, evidence rows or error when present."""

    id: str
    session_id: str
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

    def save_ready(
        self, brief: Brief, evidence_rows: dict[str, dict[str, str]], summary: BriefSummary
    ) -> None:
        """Store a finished brief, its evidence rows and its precomputed list summary."""
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE briefs SET status = 'ready', stage = NULL, brief_json = ?,"
                " evidence_json = ?, status_line = ?, worst_category = ?, unreliable_count = ?"
                " WHERE id = ?",
                (
                    brief.model_dump_json(),
                    json.dumps(evidence_rows),
                    summary.status_line,
                    summary.worst_category,
                    summary.unreliable_count,
                    brief.id,
                ),
            )

    def save_brief(self, brief: Brief) -> None:
        """Rewrite the stored brief JSON (used when only map data changes)."""
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE briefs SET brief_json = ? WHERE id = ?", (brief.model_dump_json(), brief.id)
            )

    def save_failed(self, brief_id: str, error: ErrorBody) -> None:
        """Store a failure so the client can show an honest error."""
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE briefs SET status = 'failed', stage = NULL, error_json = ?"
                " WHERE id = ? AND status = 'processing'",
                (error.model_dump_json(), brief_id),
            )

    def fail_orphaned(self) -> None:
        """At startup, mark briefs left processing by a previous run as failed."""
        error = ErrorBody(
            code="interrupted", message="The server restarted while building this brief. Try again."
        )
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE briefs SET status = 'failed', stage = NULL, error_json = ?"
                " WHERE status = 'processing'",
                (error.model_dump_json(),),
            )

    def get(self, brief_id: str) -> StoredBrief | None:
        """Fetch one brief by id."""
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT id, session_id, persona, created_at, status, stage, previous_id,"
                " brief_json, evidence_json, error_json FROM briefs WHERE id = ?",
                (brief_id,),
            ).fetchone()
        return _hydrate(row) if row else None

    def list_for_session(self, session_id: str, limit: int = 50) -> list[BriefListRow]:
        """List this browser session's briefs, newest first, from metadata columns only."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT id, persona, created_at, status_line, worst_category, unreliable_count"
                " FROM briefs WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [BriefListRow(r[0], Persona(r[1]), r[2], r[3], r[4], r[5]) for r in rows]


def _hydrate(row: tuple[Any, ...]) -> StoredBrief:
    """Convert a full database row into a StoredBrief."""
    (brief_id, session, persona, created, status, stage, previous, brief_json, evidence, error) = (
        row
    )
    return StoredBrief(
        id=brief_id,
        session_id=session,
        persona=Persona(persona),
        created_at=created,
        status=BriefStatus(status),
        stage=stage,
        previous_id=previous,
        brief=Brief.model_validate_json(brief_json) if brief_json else None,
        evidence_rows=json.loads(evidence) if evidence else {},
        error=ErrorBody.model_validate_json(error) if error else None,
    )


class ShareRepo:
    """Unguessable public links to a brief's citizen view."""

    def __init__(self, db: Database) -> None:
        """Keep the database handle."""
        self._db = db

    def share(self, brief_id: str) -> str:
        """Return the brief's share id, creating one if needed."""
        with self._db.connect() as conn:
            row = conn.execute("SELECT id FROM shares WHERE brief_id = ?", (brief_id,)).fetchone()
            if row:
                return str(row[0])
            share_id = secrets.token_urlsafe(16)
            conn.execute(
                "INSERT INTO shares (id, brief_id, created_at) VALUES (?, ?, ?)",
                (share_id, brief_id, time.time()),
            )
        return share_id

    def brief_id(self, share_id: str) -> str | None:
        """The brief behind a share id."""
        with self._db.connect() as conn:
            row = conn.execute("SELECT brief_id FROM shares WHERE id = ?", (share_id,)).fetchone()
        return str(row[0]) if row else None
