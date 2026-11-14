"""Build advisory and internal-note documents from a verified brief."""

from aqstudio.advisory.translate import TranslationError, Translator, numbers_preserved
from aqstudio.config import ADVISORY_DISCLAIMER, ADVISORY_LANGUAGES
from aqstudio.schemas import (
    AdvisoryDraft,
    Brief,
    ClaimDraft,
    ClaimStatus,
    Rendered,
    RenderedSection,
)
from aqstudio.verify.claims import verify_claims

_ADVISORY_TITLES = {
    "headline": "Air quality advisory",
    "everyone": "For everyone",
    "children": "For children",
    "older_adults": "For older adults",
    "sensitive_groups": "For people with asthma, heart or lung conditions, and pregnant people",
    "data": "About the data",
}


def data_note(brief: Brief) -> str:
    """Plain statement of data limits, built in code so it can never be softened."""
    parts: list[str] = []
    summary = brief.summary
    total = len(brief.stations)
    if summary and summary.worst_category == "insufficient_data":
        parts.append("There is not enough data to give an air quality category.")
    if summary and summary.unreliable_count:
        parts.append(
            f"Data from {summary.unreliable_count} of {total} stations is unreliable, "
            "so treat this advice with caution."
        )
    if not parts:
        parts.append(f"Based on data from {total} station{'s' if total != 1 else ''}.")
    return " ".join(parts)


def advisory_sections(draft: AdvisoryDraft, brief: Brief) -> list[RenderedSection]:
    """Advisory sections in English, each checked by the claim verifier."""
    sections: list[RenderedSection] = []
    for key in ("headline", "everyone", "children", "older_adults", "sensitive_groups"):
        text = str(getattr(draft, key))
        [check] = verify_claims(
            [ClaimDraft(text=text, fact_ids=draft.fact_ids, confidence=draft.confidence)],
            brief.facts,
        )
        sections.append(
            RenderedSection(
                key=key,
                title=_ADVISORY_TITLES[key],
                text=text,
                verified=check.status == ClaimStatus.VERIFIED,
                translated=False,
            )
        )
    sections.append(
        RenderedSection(
            key="data",
            title=_ADVISORY_TITLES["data"],
            text=data_note(brief),
            verified=True,
            translated=False,
        )
    )
    return sections


def note_sections(brief: Brief) -> list[RenderedSection]:
    """Internal briefing note composed only from already-verified content (no new AI text)."""
    verified = [c.text for c in brief.claims if c.status == ClaimStatus.VERIFIED]
    actions = [f"{a.text} ({a.owner}, {a.horizon.value})" for a in brief.actions]
    issues = [f.detail for f in brief.flags if f.severity.value != "info"][:8]
    blocks = [
        ("summary", "Summary", brief.summary.status_line if brief.summary else "No summary."),
        ("findings", "Verified findings", " ".join(verified) or "No verified findings."),
        ("actions", "Recommended actions", " ".join(actions) or "No actions passed the checks."),
        ("data", "Data issues", " ".join(issues) or "No major data issues."),
        ("limits", "Data limits", data_note(brief)),
    ]
    return [
        RenderedSection(key=k, title=t, text=x, verified=True, translated=False)
        for k, t, x in blocks
    ]


def translate_sections(
    sections: list[RenderedSection], language: str, translator: Translator
) -> tuple[list[RenderedSection], bool]:
    """Translate titles and texts; keep English where numbers would not survive."""
    target = ADVISORY_LANGUAGES[language]
    out: list[RenderedSection] = []
    preserved = True
    for section in sections:
        try:
            text = translator.translate(section.text, target)
            title = translator.translate(section.title, target)
        except TranslationError:
            out.append(section)
            preserved = False
            continue
        if not numbers_preserved(section.text, text):
            out.append(section)
            preserved = False
            continue
        out.append(section.model_copy(update={"text": text, "title": title, "translated": True}))
    return out, preserved


def rendered(
    sections: list[RenderedSection],
    language: str,
    level: str,
    fmt: str,
    fact_ids: list[str],
    preserved: bool,
) -> Rendered:
    """Assemble the response."""
    return Rendered(
        language=language,
        level=level,
        format=fmt,
        sections=sections,
        citations_preserved=preserved,
        fact_ids=fact_ids,
        disclaimer=ADVISORY_DISCLAIMER,
    )
