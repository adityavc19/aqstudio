"""Verify persona actions: citations, numbers, and reliability gating."""

from aqstudio.schemas import (
    Action,
    ActionDraft,
    ActionTier,
    ClaimDraft,
    EffectType,
    Fact,
    Persona,
    ReliabilityGrade,
)
from aqstudio.verify.claims import verify_claims

_BAD = {ReliabilityGrade.POOR, ReliabilityGrade.UNRELIABLE}
GATED = "Based on unreliable data: verify the sensor or request better data before acting."


def verify_actions(drafts: list[ActionDraft], facts: list[Fact], persona: Persona) -> list[Action]:
    """Keep actions whose citations and numbers check out; gate those resting on weak data."""
    by_id = {f.id: f for f in facts}
    kept: list[Action] = []
    for draft in drafts:
        text = " ".join([draft.text, *draft.steps, draft.success_signal])
        [check] = verify_claims(
            [ClaimDraft(text=text, fact_ids=draft.fact_ids, confidence=draft.confidence)], facts
        )
        notes = [n for n in check.notes if not n.startswith("Cites an unreliable")]
        if notes:
            continue
        weak = any(by_id[i].reliability_grade in _BAD for i in draft.fact_ids)
        gated = weak and draft.effect_type != EffectType.EVIDENCE
        kept.append(
            Action(
                **draft.model_dump(exclude={"tier"}),
                id=f"A{len(kept) + 1}",
                persona=persona,
                tier=ActionTier.ESCALATE if gated else draft.tier,
                gated_reason=GATED if gated else None,
            )
        )
    return kept
