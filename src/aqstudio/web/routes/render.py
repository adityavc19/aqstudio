"""Render a brief as a citizen advisory or internal note, in a language and reading level."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request

from aqstudio.advisory.compose import (
    advisory_sections,
    note_sections,
    rendered,
    translate_sections,
)
from aqstudio.config import ADVISORY_LANGUAGES
from aqstudio.llm.cache import cache_key
from aqstudio.llm.client import LLMError
from aqstudio.llm.prompts.advisory import PROMPT_VERSION
from aqstudio.pipeline import priority_facts
from aqstudio.schemas import Brief, ClaimStatus, Rendered, RenderedSection
from aqstudio.web.deps import Deps, get_deps
from aqstudio.web.errors import ApiError
from aqstudio.web.security import client_ip

router = APIRouter()


def _english(
    brief: Brief, fmt: str, level: str, deps: Deps
) -> tuple[list[RenderedSection], list[str]]:
    """English sections: composed in code for the note, AI-written and verified for the advisory."""
    if fmt == "note":
        cited = sorted(
            {i for c in brief.claims if c.status == ClaimStatus.VERIFIED for i in c.fact_ids}
        )
        return note_sections(brief), cited
    if deps.llm is None:
        raise ApiError(503, "llm_unavailable", "The AI service is not configured on this server.")
    try:
        draft = deps.llm.write_advisory(priority_facts(brief.facts), level)
    except LLMError as exc:
        raise ApiError(502, "llm_unavailable", f"Could not write the advisory: {exc}") from exc
    return advisory_sections(draft, brief), draft.fact_ids


@router.get("/briefs/{brief_id}/render")
def render_brief(
    brief_id: str,
    request: Request,
    deps: Annotated[Deps, Depends(get_deps)],
    language: Annotated[str, Query(description="en, hi, kn, mr, bn or ml")] = "en",
    level: Annotated[Literal["simple", "standard"], Query()] = "simple",
    format: Annotated[Literal["citizen", "note"], Query()] = "citizen",  # noqa: A002
) -> Rendered:
    """A citizen advisory (AI-written, verified) or an internal note (from verified content)."""
    if language not in ADVISORY_LANGUAGES:
        raise ApiError(
            422, "unsupported_language", "Supported languages: " + ", ".join(ADVISORY_LANGUAGES)
        )
    stored = deps.briefs.get(brief_id)
    if stored is None or stored.brief is None:
        raise ApiError(404, "not_found", "Brief not found or not ready.")
    key = cache_key(
        kind="render",
        brief=brief_id,
        language=language,
        level=level,
        fmt=format,
        prompt=PROMPT_VERSION,
    )
    hit = deps.db.cache_get(key)
    if hit is not None:
        return Rendered.model_validate_json(hit)
    if language != "en" and deps.translator is None:
        raise ApiError(
            503, "translation_unavailable", "Translation is not configured on this server."
        )
    decision = deps.limiter.check_and_record(client_ip(request))
    if not decision.allowed:
        raise ApiError(429, "rate_limited", decision.reason)
    sections, fact_ids = _english(stored.brief, format, level, deps)
    preserved = True
    if language != "en" and deps.translator is not None:
        sections, preserved = translate_sections(sections, language, deps.translator)
    result = rendered(sections, language, level, format, fact_ids, preserved)
    deps.db.cache_put(key, result.model_dump_json())
    return result
