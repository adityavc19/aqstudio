from aqstudio.schemas import ClaimDraft, ClaimStatus, Fact, QuotedValue
from aqstudio.verify.claims import verify_claims

FACT = Fact(id="S1.PM2.5.mean", statement_data={"mean": 42.0}, coverage_pct=90, reliable=True)


def _draft(ids: list[str], quotes: list[QuotedValue]) -> ClaimDraft:
    return ClaimDraft(text="t", cited_fact_ids=ids, confidence=0.5, quoted_values=quotes)


def test_valid_claim_verified() -> None:
    quote = QuotedValue(fact_id=FACT.id, field="mean", value=42.0)
    [claim] = verify_claims([_draft([FACT.id], [quote])], [FACT])
    assert claim.status == ClaimStatus.VERIFIED


def test_unknown_missing_and_mismatched_rejected() -> None:
    bad_quote = QuotedValue(fact_id=FACT.id, field="mean", value=80.0)
    claims = verify_claims(
        [_draft(["nope"], []), _draft([], []), _draft([FACT.id], [bad_quote])], [FACT]
    )
    assert all(c.status == ClaimStatus.UNVERIFIED for c in claims)
    assert "Unknown fact id" in claims[0].notes[0]
    assert "No fact cited" in claims[1].notes[0]
    assert "does not match" in claims[2].notes[0]
