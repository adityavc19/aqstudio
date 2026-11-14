"""Brief pipeline: normalize -> quality -> facts -> interpret -> verify. No storage here."""

import re
import uuid
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime

from aqstudio.clean.normalize import clean_long
from aqstudio.clean.stations import extract_stations
from aqstudio.config import LEDGER_SAMPLE_SIZE, MAX_FACTS_TO_LLM
from aqstudio.facts.build_facts import assign_fact_ids, build_facts
from aqstudio.facts.derived import flag_facts, reliability_facts
from aqstudio.ingest.errors import IngestError
from aqstudio.llm.client import LLMClient
from aqstudio.quality.coords import coordinate_flags
from aqstudio.quality.detectors import assign_flag_ids, detect_all
from aqstudio.quality.reliability import station_reliability
from aqstudio.schemas import (
    Assumption,
    Brief,
    BriefStatus,
    ColumnMapping,
    CoordinatesSource,
    Fact,
    Persona,
    RawTable,
)
from aqstudio.summary import station_infos
from aqstudio.verify.claims import verify_claims

_CADENCE_ASSUMPTION = Assumption(
    id="cadence",
    kind="cadence",
    description="Readings are one per day: treated as 24-hour averages, AQI computed per day.",
    proposed="daily",
    confidence=0.8,
)
_PRIORITY = [
    "hotspot",
    "station_reliability",
    "aqi_latest",
    "aqi_worst",
    "aqi_insufficient",
    "quality_flag",
    "pm_ratio",
    "pollutant_mean",
]
_ROW_REF = re.compile(r"^row(\d+):")
_FLAG_REF = re.compile(r"^Q\d+$")


def source_rows(table: RawTable, facts: list[Fact]) -> dict[str, dict[str, str]]:
    """Map each evidence row_ref cited by facts to its full source row (column -> cell)."""
    rows: dict[str, dict[str, str]] = {}
    for fact in facts:
        for ref in fact.evidence:
            match = _ROW_REF.match(ref)
            if _FLAG_REF.match(ref) or match is None or ref in rows:
                continue
            index = int(match[1]) - 2  # row 1 is the header
            if 0 <= index < len(table.rows):
                cells = table.rows[index]
                rows[ref] = dict(zip(table.columns, cells, strict=False))
    return rows


def _priority_facts(facts: list[Fact]) -> list[Fact]:
    """The facts sent to the model: all of them, or the most important MAX_FACTS_TO_LLM."""
    if len(facts) <= MAX_FACTS_TO_LLM:
        return facts
    ranked = sorted(facts, key=lambda f: _PRIORITY.index(f.kind) if f.kind in _PRIORITY else 99)
    return ranked[:MAX_FACTS_TO_LLM]


def build_brief(
    table: RawTable,
    mapping: list[ColumnMapping],
    assumptions: list[Assumption],
    naive_is_ist: bool,
    day_first: bool | None,
    swap_station_ids: frozenset[str],
    persona: Persona,
    context: str | None,
    previous_id: str | None,
    llm: LLMClient,
    brief_id: str | None = None,
    on_stage: Callable[[str], None] = lambda _stage: None,
) -> tuple[Brief, dict[str, dict[str, str]]]:
    """Run the full pipeline and return the brief with the source rows its facts cite."""
    on_stage("cleaning")
    cleaned = clean_long(table, mapping, naive_is_ist, day_first)
    on_stage("quality")
    locations = extract_stations(table, mapping, swap_station_ids)
    flags = assign_flag_ids([*detect_all(cleaned.readings), *coordinate_flags(locations)])
    on_stage("facts")
    base_facts, daily_cadence = build_facts(cleaned.readings, flags)
    if not base_facts:
        raise IngestError(
            "No usable readings remain after cleaning, so there is nothing to brief.", "no_data"
        )
    reliability = station_reliability(base_facts, flags)
    facts = assign_fact_ids(
        [*base_facts, *reliability_facts(reliability, flags), *flag_facts(flags)]
    )
    notes: list[str] = []
    if daily_cadence:
        assumptions = [*assumptions, _CADENCE_ASSUMPTION]
    sent = _priority_facts(facts)
    if len(sent) < len(facts):
        notes.append(f"The AI narrated {len(sent)} of {len(facts)} facts (highest priority first).")
    on_stage("interpreting")
    drafts = llm.interpret_facts(sent, persona, context)
    on_stage("verifying")
    claims = verify_claims(drafts, facts)
    brief = Brief(
        id=brief_id or uuid.uuid4().hex,
        created_at=datetime.now(UTC),
        persona=persona,
        context=context,
        facts=facts,
        claims=claims,
        actions=[],
        flags=flags,
        reliability=reliability,
        ledger_summary=dict(Counter(e.rule for e in cleaned.ledger)),
        ledger=cleaned.ledger[:LEDGER_SAMPLE_SIZE],
        assumptions=assumptions,
        stations=station_infos(locations, facts, reliability),
        notes=notes,
        coordinates_source=(
            CoordinatesSource.UPLOADED
            if any(loc.lat is not None for loc in locations)
            else CoordinatesSource.NONE
        ),
        status=BriefStatus.READY,
        previous_id=previous_id,
    )
    return brief, source_rows(table, facts)
