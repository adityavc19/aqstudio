from pathlib import Path

import pytest

from aqstudio.config import Settings
from aqstudio.schemas import ActionDraft, AdvisoryDraft, ClaimDraft, Fact, Persona, QuotedValue


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=str(tmp_path / "test.sqlite3"),
        frontend_dir=str(tmp_path / "none"),
    )


class FakeLLM:
    """Cites the first fact correctly and one invented fact; counts calls."""

    def __init__(self) -> None:
        self.calls = 0
        self.fact_counts: list[int] = []

    def interpret_facts(
        self, facts: list[Fact], persona: Persona, context: str | None
    ) -> list[ClaimDraft]:
        self.calls += 1
        self.fact_counts.append(len(facts))
        first = next((f for f in facts if "mean" in f.values), facts[0])
        quotes = (
            [QuotedValue(fact_id=first.id, field="mean", value=float(first.values["mean"] or 0))]
            if "mean" in first.values
            else []
        )
        return [
            ClaimDraft(text="Grounded", fact_ids=[first.id], confidence=0.8, quoted_values=quotes),
            ClaimDraft(text="Invented", fact_ids=["F999"], confidence=0.9),
        ]

    def rank_actions(
        self, facts: list[Fact], persona: Persona, context: str | None
    ) -> list[ActionDraft]:
        good = next((f for f in facts if "mean" in f.values), facts[0])
        return [_action([good.id]), _action(["F999"])]

    def write_advisory(self, facts: list[Fact], level: str) -> AdvisoryDraft:
        self.calls += 1
        aqi = next((f for f in facts if f.kind == "aqi_latest"), facts[0])
        value = aqi.values.get("aqi")
        return AdvisoryDraft(
            headline=f"Air quality index is {value:g} today."
            if isinstance(value, float)
            else "Air today.",
            everyone="Limit long outdoor exercise.",
            children="Keep sports indoors.",
            older_adults="Avoid long walks outside.",
            sensitive_groups="Keep medicines handy and contact a doctor if unwell.",
            fact_ids=[aqi.id],
            confidence=0.7,
        )


def _action(fact_ids: list[str], tier: str = "now", effect: str = "exposure") -> ActionDraft:
    return ActionDraft.model_validate(
        {
            "tier": tier,
            "effect_type": effect,
            "text": "Do a thing",
            "steps": ["step"],
            "owner": "ward officer",
            "horizon": "today",
            "success_signal": "done",
            "fact_ids": fact_ids,
            "confidence": 0.7,
        }
    )


def hourly_csv(base: int = 30, hours: int = 24, day: int = 1) -> str:
    rows = ["Station ID,Timestamp,PM2.5 (ug/m3),PM10 (ug/m3),NO2 (ug/m3)"]
    for h in range(hours):
        rows.append(f"S1,2024-01-{day:02d}T{h:02d}:00:00Z,{base + h},{base * 2 + h},{20 + h}")
    return "\n".join(rows)


def station_csv(stations: list[tuple[str, str, str, str]], with_coords: bool = True) -> str:
    """Hourly data per station: (id, name, lat, lon); with_coords=False drops lat/lon columns."""
    coord_header = "Latitude,Longitude," if with_coords else ""
    header = (
        f"Station ID,Station Name,{coord_header}Timestamp,PM2.5 (ug/m3),PM10 (ug/m3),NO2 (ug/m3)"
    )
    rows = [header]
    for sid, name, lat, lon in stations:
        coords = f"{lat},{lon}," if with_coords else ""
        for h in range(24):
            rows.append(
                f"{sid},{name},{coords}2024-01-01T{h:02d}:00:00Z,{40 + h},{80 + h},{20 + h}"
            )
    return "\n".join(rows)
