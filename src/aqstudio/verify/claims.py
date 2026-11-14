"""Verify LLM claims against computed facts."""

from aqstudio.schemas import Claim, ClaimDraft, ClaimStatus, Fact

NUMBER_TOLERANCE = 0.51  # facts are rounded for display; allow rounding differences only.


def verify_claims(drafts: list[ClaimDraft], facts: list[Fact]) -> list[Claim]:
    """Mark each claim verified only if it cites known facts and quotes matching numbers."""
    by_id = {f.id: f for f in facts}
    verified: list[Claim] = []
    for draft in drafts:
        notes: list[str] = []
        if not draft.cited_fact_ids:
            notes.append("No fact cited.")
        notes.extend(f"Unknown fact id: {i}" for i in draft.cited_fact_ids if i not in by_id)
        for quote in draft.quoted_values:
            fact = by_id.get(quote.fact_id)
            if fact is None or quote.fact_id not in draft.cited_fact_ids:
                notes.append(f"Quoted number refers to uncited or unknown fact: {quote.fact_id}")
                continue
            actual = fact.statement_data.get(quote.field)
            if not isinstance(actual, int | float) or abs(actual - quote.value) > NUMBER_TOLERANCE:
                notes.append(
                    f"Quoted {quote.field}={quote.value} does not match fact value {actual}."
                )
        status = ClaimStatus.UNVERIFIED if notes else ClaimStatus.VERIFIED
        verified.append(Claim(**draft.model_dump(), status=status, notes=notes))
    return verified
