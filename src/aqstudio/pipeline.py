"""Brief pipeline: normalize -> quality -> facts -> interpret -> verify. No storage here."""

import re
import uuid
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime

from aqstudio.clean.normalize import clean_long
from aqstudio.config import LEDGER_SAMPLE_SIZE
from aqstudio.facts.build_facts import build_facts
from aqstudio.llm.client import LLMClient
from aqstudio.quality.detectors import detect_all
from aqstudio.quality.reliability import station_reliability
from aqstudio.schemas import (
    Assumption,
    Brief,
    BriefStatus,
    ColumnMapping,
    Fact,
    Persona,
    RawTable,
)
from aqstudio.verify.claims import verify_claims

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


def build_brief(
    table: RawTable,
    mapping: list[ColumnMapping],
    assumptions: list[Assumption],
    naive_is_ist: bool,
    persona: Persona,
    context: str | None,
    previous_id: str | None,
    llm: LLMClient,
    brief_id: str | None = None,
    on_stage: Callable[[str], None] = lambda _stage: None,
) -> tuple[Brief, dict[str, dict[str, str]]]:
    """Run the full pipeline and return the brief with the source rows its facts cite."""
    on_stage("cleaning")
    cleaned = clean_long(table, mapping, naive_is_ist)
    on_stage("quality")
    flags = detect_all(cleaned.readings)
    on_stage("facts")
    facts = build_facts(cleaned.readings, flags)
    reliability = station_reliability(facts, flags)
    on_stage("interpreting")
    drafts = llm.interpret_facts(facts, flags, reliability, persona, context)
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
        status=BriefStatus.READY,
        previous_id=previous_id,
    )
    return brief, source_rows(table, facts)
