"""Verify LLM claims against computed facts: citations, quoted numbers, text numbers, hedging."""

import re

from aqstudio.config import AQI_CATEGORIES, HEDGE_WORDS, VERIFIER_DROP_UNVERIFIED
from aqstudio.schemas import Claim, ClaimDraft, ClaimStatus, Fact, ReliabilityGrade

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_LABEL_WITH_DIGITS = re.compile(r"\b[A-Za-z][A-Za-z.]*\d+(?:\.\d+)?\b")  # PM2.5, NO2, S1, F3, m3
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_HEDGE = re.compile("|".join(re.escape(w) for w in HEDGE_WORDS), re.IGNORECASE)
_CATEGORY_NAMES = [name for _, name in AQI_CATEGORIES]
_CATEGORY = re.compile(
    r"\b("
    + "|".join(sorted(_CATEGORY_NAMES, key=len, reverse=True))
    + r")\b(?!\s+(?:reliab|coverage|quality))"
)
_BAD_GRADES = {ReliabilityGrade.POOR, ReliabilityGrade.UNRELIABLE}


def _decimals(text: str) -> int:
    """Digits after the decimal point as written (trailing zeros ignored)."""
    return len(text.split(".")[1].rstrip("0")) if "." in text else 0


def _close(actual: float, written: str) -> bool:
    """True when a written number equals the actual value rounded to the digits it shows."""
    return bool(abs(actual - float(written)) <= 0.5 * 10 ** -_decimals(written) + 1e-9)


def _numbers(text: str) -> list[str]:
    """Numbers in free text, ignoring dates, fact ids, pollutant names and units like m3."""
    return _NUMBER.findall(_LABEL_WITH_DIGITS.sub(" ", _DATE.sub(" ", text)))


def _field_value(fact: Fact, field: str) -> float | str | None:
    """Look a quoted field up in the fact's values, or its top-level coverage_pct."""
    return fact.coverage_pct if field == "coverage_pct" else fact.values.get(field)


def _allowed_numbers(facts: list[Fact]) -> list[float]:
    """Every number a claim may mention: values, coverage, and numbers inside text values."""
    allowed: list[float] = []
    for fact in facts:
        allowed.append(fact.coverage_pct)
        for value in fact.values.values():
            if isinstance(value, int | float):
                allowed.append(float(value))
            elif isinstance(value, str):
                allowed.extend(float(n) for n in _numbers(value))
    return allowed


def _check(draft: ClaimDraft, by_id: dict[str, Fact]) -> list[str]:
    """Return the reasons a claim cannot be verified (empty when it can)."""
    notes: list[str] = []
    if not draft.fact_ids:
        notes.append("No fact cited.")
    notes.extend(f"Unknown fact id: {i}" for i in draft.fact_ids if i not in by_id)
    cited = [by_id[i] for i in draft.fact_ids if i in by_id]
    for quote in draft.quoted_values:
        fact = by_id.get(quote.fact_id)
        if fact is None or quote.fact_id not in draft.fact_ids:
            notes.append(f"Quoted number refers to uncited or unknown fact: {quote.fact_id}")
            continue
        actual = _field_value(fact, quote.field)
        if not isinstance(actual, int | float) or not _close(float(actual), repr(quote.value)):
            notes.append(f"Quoted {quote.field}={quote.value} does not match fact value {actual}.")
    if cited:
        allowed = _allowed_numbers(cited)
        notes.extend(
            f"Number {n} in the text is not in the cited facts."
            for n in dict.fromkeys(_numbers(draft.text))
            if not any(_close(a, n) for a in allowed)
        )
        categories = {str(f.values["category"]) for f in cited if "category" in f.values}
        if categories:
            notes.extend(
                f"Category '{c}' in the text does not match the cited AQI category."
                for c in dict.fromkeys(_CATEGORY.findall(draft.text))
                if c not in categories
            )
        if any(f.reliability_grade in _BAD_GRADES for f in cited) and not _HEDGE.search(draft.text):
            notes.append("Cites an unreliable fact without saying it is unreliable.")
    return notes


def verify_claims(drafts: list[ClaimDraft], facts: list[Fact]) -> list[Claim]:
    """Mark each claim verified only if every check passes; failures are visible, not hidden."""
    by_id = {f.id: f for f in facts}
    verified: list[Claim] = []
    for draft in drafts:
        notes = _check(draft, by_id)
        if notes and VERIFIER_DROP_UNVERIFIED:
            continue
        status = ClaimStatus.UNVERIFIED if notes else ClaimStatus.VERIFIED
        verified.append(
            Claim(**draft.model_dump(), id=f"C{len(verified) + 1}", status=status, notes=notes)
        )
    return verified
