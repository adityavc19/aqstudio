"""Brief routes: create (background), poll, evidence, diff, list."""

import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request

from aqstudio.compare.diff import diff_briefs
from aqstudio.ingest.errors import IngestError
from aqstudio.ingest.parse_long import parse_long_csv
from aqstudio.ingest.propose import propose_mapping, validate_mapping
from aqstudio.llm.client import LLMClient, LLMError
from aqstudio.pipeline import build_brief
from aqstudio.schemas import (
    Assumption,
    AssumptionStatus,
    Brief,
    BriefAccepted,
    BriefListItem,
    BriefRequest,
    BriefState,
    BriefStatus,
    ColumnMapping,
    Diff,
    ErrorBody,
    EvidenceResponse,
    RawTable,
)
from aqstudio.web.deps import Deps, get_deps, session_id
from aqstudio.web.errors import ApiError
from aqstudio.web.security import client_ip

router = APIRouter()
_log = logging.getLogger("aqstudio")
_FLAG_PREFIX = "Q"


def _run_brief(
    deps: Deps,
    llm: LLMClient,
    brief_id: str,
    table: RawTable,
    mapping: list[ColumnMapping],
    assumptions: list[Assumption],
    naive_is_ist: bool,
    request: BriefRequest,
) -> None:
    """Background job: build the brief and store it, or store an honest failure."""
    try:
        brief, evidence = build_brief(
            table,
            mapping,
            assumptions,
            naive_is_ist,
            request.persona,
            request.context,
            request.previous_brief_id,
            llm,
            brief_id=brief_id,
            on_stage=lambda stage: deps.briefs.set_stage(brief_id, stage),
        )
        deps.briefs.save_ready(brief, evidence)
    except LLMError as exc:
        deps.briefs.save_failed(brief_id, ErrorBody(code="llm_unavailable", message=str(exc)))
    except IngestError as exc:
        deps.briefs.save_failed(brief_id, ErrorBody(code=exc.code, message=str(exc)))
    except Exception:
        _log.exception("Brief %s failed", brief_id)
        deps.briefs.save_failed(
            brief_id,
            ErrorBody(code="internal_error", message="Brief generation failed unexpectedly."),
        )


def _apply_choices(assumptions: list[Assumption], req: BriefRequest) -> list[Assumption]:
    """Apply the user's confirm/override decisions to the proposed assumptions."""
    choices = {c.id: c.status for c in req.assumptions}
    return [a.model_copy(update={"status": choices.get(a.id, a.status)}) for a in assumptions]


@router.post("/briefs", status_code=202)
def create_brief(
    body: BriefRequest,
    request: Request,
    tasks: BackgroundTasks,
    deps: Annotated[Deps, Depends(get_deps)],
) -> BriefAccepted:
    """Start building a brief from a confirmed mapping; poll GET /briefs/{id} for the result."""
    upload = deps.uploads.get(body.upload_id)
    if upload is None:
        raise ApiError(404, "not_found", "Upload not found.")
    if body.previous_brief_id and deps.briefs.get(body.previous_brief_id) is None:
        raise ApiError(404, "not_found", "Previous brief not found.")
    if deps.llm is None:
        raise ApiError(503, "llm_unavailable", "The AI service is not configured on this server.")
    try:
        table = parse_long_csv(upload.text)
        proposed_mapping, proposed_assumptions = propose_mapping(table)
        mapping = body.mapping or proposed_mapping
        validate_mapping(table, mapping)
    except IngestError as exc:
        raise ApiError(422, exc.code, str(exc)) from exc
    decision = deps.limiter.check_and_record(client_ip(request))
    if not decision.allowed:
        raise ApiError(429, "rate_limited", decision.reason)
    assumptions = _apply_choices(proposed_assumptions, body)
    naive_is_ist = any(
        a.id == "timezone" and a.status == AssumptionStatus.OVERRIDDEN for a in assumptions
    )
    sid = session_id(request, create=True) or ""
    brief_id = deps.briefs.create_processing(sid, body.persona, body.previous_brief_id)
    tasks.add_task(
        _run_brief, deps, deps.llm, brief_id, table, mapping, assumptions, naive_is_ist, body
    )
    return BriefAccepted(brief_id=brief_id, status=BriefStatus.PROCESSING)


@router.get("/briefs")
def list_briefs(request: Request, deps: Annotated[Deps, Depends(get_deps)]) -> list[BriefListItem]:
    """List the briefs created in this browser session, newest first."""
    sid = session_id(request)
    if sid is None:
        return []
    return [
        BriefListItem(
            id=b.id,
            created_at=datetime.fromtimestamp(b.created_at, UTC).isoformat(),
            persona=b.persona,
            label=f"{b.persona.value.replace('_', ' ')} - "
            f"{datetime.fromtimestamp(b.created_at, UTC):%Y-%m-%d %H:%M} UTC",
        )
        for b in deps.briefs.list_for_session(sid)
    ]


def _ready_brief(deps: Deps, brief_id: str) -> tuple[Brief, dict[str, dict[str, str]]]:
    """Load a finished brief or raise the matching API error."""
    stored = deps.briefs.get(brief_id)
    if stored is None:
        raise ApiError(404, "not_found", "Brief not found.")
    if stored.brief is None:
        raise ApiError(409, "not_ready", "The brief is not ready yet.")
    return stored.brief, stored.evidence_rows


@router.get("/briefs/{brief_id}")
def get_brief(brief_id: str, deps: Annotated[Deps, Depends(get_deps)]) -> BriefState:
    """Return processing state, the finished brief, or an honest error."""
    stored = deps.briefs.get(brief_id)
    if stored is None:
        raise ApiError(404, "not_found", "Brief not found.")
    return BriefState(
        id=stored.id,
        status=stored.status,
        stage=stored.stage,
        brief=stored.brief,
        error=stored.error,
    )


@router.get("/briefs/{brief_id}/evidence/{fact_id}")
def get_evidence(
    brief_id: str, fact_id: str, deps: Annotated[Deps, Depends(get_deps)]
) -> EvidenceResponse:
    """Return a fact with the source rows, quality flags and reliability behind it."""
    brief, evidence_rows = _ready_brief(deps, brief_id)
    fact = next((f for f in brief.facts if f.id == fact_id), None)
    if fact is None:
        raise ApiError(404, "not_found", "Fact not found in this brief.")
    refs = [r for r in fact.evidence if not _is_flag_id(r)]
    return EvidenceResponse(
        fact=fact,
        rows=[{"row_ref": r, "values": evidence_rows.get(r, {})} for r in refs],
        flags=[f for f in brief.flags if f.id in fact.evidence],
        reliability=next((r for r in brief.reliability if r.station_id == fact.station_id), None),
    )


def _is_flag_id(ref: str) -> bool:
    """True for quality-flag ids (Q1, Q2, ...) mixed into evidence lists."""
    return ref.startswith(_FLAG_PREFIX) and ref[1:].isdigit()


@router.get("/briefs/{brief_id}/diff")
def get_diff(
    brief_id: str,
    against: Annotated[str, Query(description="Baseline brief id; changes are measured from it.")],
    deps: Annotated[Deps, Depends(get_deps)],
) -> Diff:
    """Compare this brief with a baseline, labelling coverage-driven changes."""
    after, _ = _ready_brief(deps, brief_id)
    before, _ = _ready_brief(deps, against)
    return diff_briefs(before, after)
