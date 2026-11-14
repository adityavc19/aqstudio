"""Opt-in live test against the real AI provider.

Run with: RUN_LIVE_LLM=1 uv run pytest tests/test_live_llm.py
"""

import os
import re
from pathlib import Path

import pytest

from aqstudio.ingest.parse_long import parse_long_csv
from aqstudio.ingest.propose import propose_mapping
from aqstudio.llm.sarvam_client import SarvamClient
from aqstudio.pipeline import build_brief
from aqstudio.schemas import ClaimStatus, Persona

pytestmark = pytest.mark.skipif(os.environ.get("RUN_LIVE_LLM") != "1", reason="set RUN_LIVE_LLM=1")


def _key() -> str:
    key = os.environ.get("SARVAM_API_KEY")
    if not key and Path(".env").exists():
        match = re.search(r"^SARVAM_API_KEY=(.*)$", Path(".env").read_text(), re.M)
        key = match.group(1).strip() if match else None
    if not key:
        pytest.skip("SARVAM_API_KEY not configured")
    return key


def test_real_model_produces_mostly_verified_claims_and_actions() -> None:
    rows = ["Station ID,Timestamp,PM2.5 (ug/m3),PM10 (ug/m3),NO2 (ug/m3)"]
    rows += [f"S1,2026-11-13T{h:02d}:00:00Z,{60 + h},{120 + h},{25 + h}" for h in range(24)]
    table = parse_long_csv("\n".join(rows))
    mapping, assumptions = propose_mapping(table)
    llm = SarvamClient(_key(), os.environ.get("SARVAM_MODEL", "deepseekv4.1-flash-1017"))
    brief, _ = build_brief(
        table, mapping, assumptions, False, None, frozenset(), {}, Persona.SCHOOL, None, None, llm
    )
    verified = sum(c.status == ClaimStatus.VERIFIED for c in brief.claims)
    assert brief.claims and verified / len(brief.claims) >= 0.8
    assert brief.actions and all(a.fact_ids for a in brief.actions)
