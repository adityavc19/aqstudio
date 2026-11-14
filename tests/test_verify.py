from aqstudio.schemas import ClaimDraft, ClaimStatus, Fact, QuotedValue, ReliabilityGrade
from aqstudio.verify.claims import verify_claims

FACT = Fact(
    id="F1",
    kind="pollutant_mean",
    values={"mean": 42.0},
    coverage_pct=90,
    reliability_grade=ReliabilityGrade.GOOD,
)


def _draft(ids: list[str], quotes: list[QuotedValue]) -> ClaimDraft:
    return ClaimDraft(text="t", fact_ids=ids, confidence=0.5, quoted_values=quotes)


def test_valid_claim_verified_with_id() -> None:
    quote = QuotedValue(fact_id="F1", field="mean", value=42.2)
    [claim] = verify_claims([_draft(["F1"], [quote])], [FACT])
    assert claim.status == ClaimStatus.VERIFIED and claim.id == "C1"


def test_unknown_missing_and_mismatched_rejected() -> None:
    bad = QuotedValue(fact_id="F1", field="mean", value=80.0)
    claims = verify_claims([_draft(["nope"], []), _draft([], []), _draft(["F1"], [bad])], [FACT])
    assert all(c.status == ClaimStatus.UNVERIFIED for c in claims)
    assert "Unknown fact id" in claims[0].notes[0]
    assert "No fact cited" in claims[1].notes[0]
    assert "does not match" in claims[2].notes[0]
