"""Pydantic models: the contract between pipeline stages and the JSON API (BACKEND_PLAN.md)."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import AwareDatetime, BaseModel, Field


class Persona(StrEnum):
    """Who the brief is written for."""

    WARD_OFFICER = "ward_officer"
    HOUSING_SOCIETY = "housing_society"
    SCHOOL = "school"
    CITIZEN = "citizen"
    OTHER = "other"


class FlagKind(StrEnum):
    """Data-quality problem categories."""

    GAP = "gap"
    STUCK = "stuck"
    CEILING = "ceiling"
    IMPLAUSIBLE = "implausible"
    EMPTY_COLUMN = "empty_column"
    UNIT_MISMATCH = "unit_mismatch"
    ORPHAN_AQI = "orphan_aqi"
    STALE = "stale"
    NO_COORDS = "no_coords"


class Severity(StrEnum):
    """Flag severity."""

    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"


class ReliabilityGrade(StrEnum):
    """Reliability grade for a station or fact."""

    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    UNRELIABLE = "unreliable"


class ClaimStatus(StrEnum):
    """Verifier outcome for a claim."""

    VERIFIED = "verified"
    UNVERIFIED = "unverified"


class AssumptionStatus(StrEnum):
    """Whether the user accepted a proposed assumption."""

    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    OVERRIDDEN = "overridden"


class CoordinatesSource(StrEnum):
    """Where station coordinates came from; never geocoded."""

    UPLOADED = "uploaded"
    STATIONS_FILE = "stations_file"
    NONE = "none"


class BriefStatus(StrEnum):
    """Lifecycle of a brief."""

    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class Reading(BaseModel):
    """One pollutant measurement. A missing value is None, never zero."""

    station_id: str
    ts: AwareDatetime
    pollutant: str
    value: float | None
    unit: str
    row_ref: str


class Assumption(BaseModel):
    """Something the pipeline assumed about the data; the user may override it."""

    id: str
    kind: str
    description: str
    proposed: Any
    confidence: float = Field(ge=0, le=1)
    status: AssumptionStatus = AssumptionStatus.PROPOSED


class LedgerEntry(BaseModel):
    """One cleaning action, so every change is auditable."""

    row_ref: str
    rule: str
    before: str | None
    after: str | None
    reason: str


class QualityFlag(BaseModel):
    """A detected data-quality problem. `id` is assigned by detect_all."""

    id: str = ""
    kind: FlagKind
    station_id: str
    pollutant: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    severity: Severity
    detail: str
    row_refs: list[str] = Field(default_factory=list)


class StationReliability(BaseModel):
    """Per-station reliability summary."""

    station_id: str
    coverage_pct: float = Field(ge=0, le=100)
    score: float = Field(ge=0, le=100)
    grade: ReliabilityGrade
    reasons: list[str]


class Fact(BaseModel):
    """A deterministically computed statement the LLM may cite by id. `id` is assigned later."""

    id: str = ""
    kind: str
    station_id: str | None = None
    period: str | None = None
    values: dict[str, float | str | None]
    coverage_pct: float = Field(ge=0, le=100)
    reliability_grade: ReliabilityGrade
    evidence: list[str] = Field(default_factory=list)
    spatial_note: str | None = None


class QuotedValue(BaseModel):
    """A number a claim quotes, tied to the fact field it must match."""

    fact_id: str
    field: str
    value: float


class ClaimDraft(BaseModel):
    """A claim as returned by the LLM, before verification."""

    text: str
    fact_ids: list[str]
    confidence: float = Field(ge=0, le=1)
    quoted_values: list[QuotedValue] = Field(default_factory=list)


class InterpretationOutput(BaseModel):
    """Schema the LLM must return."""

    claims: list[ClaimDraft]


class Claim(ClaimDraft):
    """A claim after verification, with the reasons it failed if it did."""

    id: str
    status: ClaimStatus = ClaimStatus.UNVERIFIED
    notes: list[str] = Field(default_factory=list)


class ActionTier(StrEnum):
    """Urgency tier of an action."""

    NOW = "now"
    ESCALATE = "escalate"
    CONTEXT = "context"


class EffectType(StrEnum):
    """What an action changes."""

    EXPOSURE = "exposure"
    SOURCE = "source"
    EVIDENCE = "evidence"


class Horizon(StrEnum):
    """When an action pays off."""

    TODAY = "today"
    WEEK = "week"
    STRUCTURAL = "structural"


class Action(BaseModel):
    """A prioritized recommendation for a persona (generated in a later milestone)."""

    id: str
    persona: Persona
    tier: ActionTier
    effect_type: EffectType
    text: str
    steps: list[str]
    owner: str
    escalate_to: str | None = None
    horizon: Horizon
    success_signal: str
    fact_ids: list[str]
    confidence: float = Field(ge=0, le=1)
    gated_reason: str | None = None


class StationLocation(BaseModel):
    """A station's name and coordinates as found in the upload, with any problem noted."""

    station_id: str
    name: str
    lat: float | None = None
    lon: float | None = None
    problem: str | None = None
    detail: str = ""


class StationInfo(BaseModel):
    """Map-ready station summary. lat/lon come only from the upload or user-supplied files."""

    station_id: str
    name: str
    lat: float | None
    lon: float | None
    aqi: float | None
    category: str
    reliability_grade: ReliabilityGrade


class BriefSummary(BaseModel):
    """Code-built summary stored with the brief's metadata for fast listing."""

    status_line: str
    worst_category: str
    unreliable_count: int


class Brief(BaseModel):
    """A complete stored briefing."""

    id: str
    created_at: AwareDatetime
    persona: Persona
    context: str | None = None
    facts: list[Fact]
    claims: list[Claim]
    actions: list[Action]
    flags: list[QualityFlag]
    reliability: list[StationReliability]
    ledger_summary: dict[str, int]
    ledger: list[LedgerEntry] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    stations: list[StationInfo] = Field(default_factory=list)
    coordinates_source: CoordinatesSource = CoordinatesSource.NONE
    status: BriefStatus
    previous_id: str | None = None


class FactChange(BaseModel):
    """A comparable fact whose headline value moved between two briefs."""

    key: str
    before_fact_id: str
    after_fact_id: str
    field: str
    before: float
    after: float
    delta: float
    delta_pct: float | None


class CoverageChange(BaseModel):
    """Coverage movement for a comparable fact."""

    key: str
    before_pct: float
    after_pct: float


class Diff(BaseModel):
    """Difference between two briefs, coverage-aware."""

    changed: list[FactChange]
    new_flags: list[QualityFlag]
    resolved_flags: list[QualityFlag]
    coverage_changes: list[CoverageChange]
    explained_by_coverage: list[FactChange]
    summary_inputs: dict[str, int | str]


class RawTable(BaseModel):
    """Unparsed tabular text: header plus string cells."""

    columns: list[str]
    rows: list[list[str]]


class CleanResult(BaseModel):
    """Tidy readings plus the ledger of every change made to get them."""

    readings: list[Reading]
    ledger: list[LedgerEntry]


class ColumnMapping(BaseModel):
    """What a source column means. `pollutant` is set when meaning is 'pollutant'."""

    column: str
    meaning: str
    pollutant: str | None = None
    unit: str | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)


class Preview(BaseModel):
    """First rows of an upload."""

    columns: list[str]
    rows: list[list[str]]


class UploadResponse(BaseModel):
    """Result of POST /uploads."""

    upload_id: str
    detected_format: str
    preview: Preview
    mapping: list[ColumnMapping]
    assumptions: list[Assumption]
    warnings: list[str]


class AssumptionChoice(BaseModel):
    """The user's decision on one assumption."""

    id: str
    status: AssumptionStatus


class BriefRequest(BaseModel):
    """Body of POST /briefs."""

    upload_id: str
    persona: Persona
    context: str | None = Field(default=None, max_length=1000)
    mapping: list[ColumnMapping] | None = None
    assumptions: list[AssumptionChoice] = Field(default_factory=list)
    previous_brief_id: str | None = None


class BriefAccepted(BaseModel):
    """Response of POST /briefs."""

    brief_id: str
    status: BriefStatus


class ErrorBody(BaseModel):
    """Inner error object."""

    code: str
    message: str
    detail: dict[str, Any] | None = None


class BriefState(BaseModel):
    """Response of GET /briefs/{id}."""

    id: str
    status: BriefStatus
    stage: str | None = None
    brief: Brief | None = None
    error: ErrorBody | None = None


class BriefListItem(BaseModel):
    """Entry of GET /briefs."""

    id: str
    created_at: str
    persona: Persona
    label: str
    status_line: str | None = None
    worst_category: str | None = None
    unreliable_count: int | None = None


class EvidenceResponse(BaseModel):
    """Response of GET /briefs/{id}/evidence/{fact_id}."""

    fact: Fact
    rows: list[dict[str, Any]]
    flags: list[QualityFlag]
    reliability: StationReliability | None


class HealthResponse(BaseModel):
    """Response of GET /health."""

    status: str
    version: str


class LocationMatch(BaseModel):
    """A locations-file row that updated a station."""

    row: int
    file_station: str
    station_id: str


class LocationRejection(BaseModel):
    """A locations-file row that did not update any station, with the reason."""

    row: int
    file_station: str
    reason: str


class LocationsResponse(BaseModel):
    """Response of POST /briefs/{id}/locations."""

    stations: list[StationInfo]
    coordinates_source: CoordinatesSource
    matched: list[LocationMatch]
    unmatched: list[LocationRejection]
