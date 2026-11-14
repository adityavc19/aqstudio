"""Pydantic models: the contract between pipeline stages."""

from datetime import datetime
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, Field


class Persona(StrEnum):
    """Who the brief is written for."""

    WARD_OFFICER = "ward_officer"
    HOUSING_SOCIETY = "housing_society"
    SCHOOL = "school"


class FlagKind(StrEnum):
    """Data-quality problem categories."""

    GAP = "gap"
    STUCK = "stuck"
    CEILING = "ceiling"
    IMPLAUSIBLE = "implausible"
    EMPTY_COLUMN = "empty_column"
    UNIT_MISMATCH = "unit_mismatch"
    ORPHAN_AQI = "orphan_aqi"


class Severity(StrEnum):
    """Flag severity."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class ClaimStatus(StrEnum):
    """Verifier outcome for a claim."""

    VERIFIED = "verified"
    UNVERIFIED = "unverified"


class Reading(BaseModel):
    """One pollutant measurement. A missing value is None, never zero."""

    station_id: str
    timestamp: AwareDatetime
    pollutant: str
    value: float | None
    unit: str
    source_row_ref: str


class LedgerEntry(BaseModel):
    """One cleaning action, so every change is auditable."""

    row_ref: str
    rule: str
    before: str | None
    after: str | None
    reason: str


class QualityFlag(BaseModel):
    """A detected data-quality problem."""

    kind: FlagKind
    station_id: str
    pollutant: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    severity: Severity
    evidence_refs: list[str] = Field(default_factory=list)


class Fact(BaseModel):
    """A deterministically computed statement the LLM may cite by id."""

    id: str
    statement_data: dict[str, float | str | None]
    station_id: str | None = None
    period: str | None = None
    coverage_pct: float = Field(ge=0, le=100)
    reliable: bool
    evidence_refs: list[str] = Field(default_factory=list)


class QuotedValue(BaseModel):
    """A number a claim quotes, tied to the fact field it must match."""

    fact_id: str
    field: str
    value: float


class ClaimDraft(BaseModel):
    """A claim as returned by the LLM, before verification."""

    text: str
    cited_fact_ids: list[str]
    confidence: float = Field(ge=0, le=1)
    quoted_values: list[QuotedValue] = Field(default_factory=list)


class InterpretationOutput(BaseModel):
    """Schema the LLM must return."""

    claims: list[ClaimDraft]


class Claim(ClaimDraft):
    """A claim after verification, with the reasons it failed if it did."""

    status: ClaimStatus = ClaimStatus.UNVERIFIED
    notes: list[str] = Field(default_factory=list)


class Action(BaseModel):
    """A prioritized recommendation for a persona."""

    priority: int = Field(ge=1)
    persona: Persona
    text: str
    rationale: str
    cited_fact_ids: list[str]
    confidence: float = Field(ge=0, le=1)


class Brief(BaseModel):
    """A complete stored briefing."""

    id: str
    created_at: AwareDatetime
    persona: Persona
    facts: list[Fact]
    claims: list[Claim]
    actions: list[Action]
    flags: list[QualityFlag]
    ledger_summary: dict[str, int]


class Diff(BaseModel):
    """Difference between two briefs, coverage-aware."""

    changed_fact_ids: list[str]
    new_flags: list[QualityFlag]
    resolved_flags: list[QualityFlag]
    coverage_changes: dict[str, float]
    coverage_driven_fact_ids: list[str]


class RawTable(BaseModel):
    """Unparsed tabular text: header plus string cells."""

    columns: list[str]
    rows: list[list[str]]


class CleanResult(BaseModel):
    """Tidy readings plus the ledger of every change made to get them."""

    readings: list[Reading]
    ledger: list[LedgerEntry]
