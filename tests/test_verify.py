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
    quote = QuotedValue(fact_id="F1", field="mean", value=42.0)
    [claim] = verify_claims([_draft(["F1"], [quote])], [FACT])
    assert claim.status == ClaimStatus.VERIFIED and claim.id == "C1"


def test_unknown_missing_and_mismatched_rejected() -> None:
    bad = QuotedValue(fact_id="F1", field="mean", value=80.0)
    claims = verify_claims([_draft(["nope"], []), _draft([], []), _draft(["F1"], [bad])], [FACT])
    assert all(c.status == ClaimStatus.UNVERIFIED for c in claims)
    assert "Unknown fact id" in claims[0].notes[0]
    assert "No fact cited" in claims[1].notes[0]
    assert "does not match" in claims[2].notes[0]


def test_coverage_pct_is_a_quotable_field() -> None:
    ok = QuotedValue(fact_id="F1", field="coverage_pct", value=90.0)
    bad = QuotedValue(fact_id="F1", field="coverage_pct", value=50.0)
    first, second = verify_claims([_draft(["F1"], [ok]), _draft(["F1"], [bad])], [FACT])
    assert first.status == ClaimStatus.VERIFIED and second.status == ClaimStatus.UNVERIFIED


def _claim(text: str, ids: list[str] | None = None) -> ClaimDraft:
    return ClaimDraft(text=text, fact_ids=ids or ["F1"], confidence=0.5)


def test_numbers_written_in_text_are_checked_against_cited_facts() -> None:
    fact = FACT.model_copy(update={"values": {"pollutant": "PM2.5", "mean": 36.5, "unit": "ug/m3"}})
    texts = [
        "PM2.5 mean is 36.5 ug/m3 (F1) over 2024-01-01..2024-01-02 at S1 with 90.0% coverage.",
        "PM2.5 mean is about 37 ug/m3.",
        "PM2.5 mean is 99 ug/m3.",
    ]
    ok, rounded, invented = verify_claims([_claim(t) for t in texts], [fact])
    assert ok.status == ClaimStatus.VERIFIED and rounded.status == ClaimStatus.VERIFIED
    assert invented.status == ClaimStatus.UNVERIFIED and "Number 99" in invented.notes[0]


def test_category_must_match_the_cited_aqi_fact_and_unreliable_facts_need_a_hedge() -> None:
    aqi = Fact(
        id="F2",
        kind="aqi_latest",
        values={"aqi": 112.0, "category": "Moderate"},
        coverage_pct=100,
        reliability_grade=ReliabilityGrade.GOOD,
    )
    shaky = FACT.model_copy(update={"reliability_grade": ReliabilityGrade.UNRELIABLE})
    wrong, right = verify_claims(
        [_claim("AQI of 112 is Poor today.", ["F2"]), _claim("AQI of 112 is Moderate.", ["F2"])],
        [aqi],
    )
    assert wrong.status == ClaimStatus.UNVERIFIED and "Category 'Poor'" in wrong.notes[0]
    assert right.status == ClaimStatus.VERIFIED
    plain, hedged = verify_claims(
        [_claim("The mean is 42.0."), _claim("The mean of 42.0 is unreliable.")], [shaky]
    )
    assert "without saying" in plain.notes[0] and hedged.status == ClaimStatus.VERIFIED
