"""Citizen view: an unguessable public link to a brief's station categories and advisory."""

import base64
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response

from aqstudio.advisory.compose import data_note
from aqstudio.advisory.speech import SpeechError, fit_for_speech
from aqstudio.config import ADVISORY_LANGUAGES
from aqstudio.llm.cache import cache_key
from aqstudio.schemas import Brief, CitizenPage, Rendered, ShareCreated
from aqstudio.web.deps import Deps, get_deps, session_id
from aqstudio.web.errors import ApiError
from aqstudio.web.routes.render import render_document
from aqstudio.web.security import client_ip

router = APIRouter()
NOTICE = (
    "Unofficial: based on data uploaded by a local user and checked by this tool. Not an official "
    "government advisory."
)


def _shared_brief(share_id: str, deps: Deps) -> Brief:
    """Load the brief behind a share link or raise 404."""
    brief_id = deps.shares.brief_id(share_id)
    stored = deps.briefs.get(brief_id) if brief_id else None
    if stored is None or stored.brief is None:
        raise ApiError(404, "not_found", "This citizen page does not exist or has expired.")
    return stored.brief


@router.post("/briefs/{brief_id}/share")
def share_brief(
    brief_id: str, request: Request, deps: Annotated[Deps, Depends(get_deps)]
) -> ShareCreated:
    """Create (or return) the public citizen link for a brief; only its creator may do this."""
    stored = deps.briefs.get(brief_id)
    if stored is None or stored.brief is None:
        raise ApiError(404, "not_found", "Brief not found or not ready.")
    if session_id(request) != stored.session_id:
        raise ApiError(
            403, "forbidden", "Only the browser session that created a brief can share it."
        )
    share_id = deps.shares.share(brief_id)
    return ShareCreated(share_id=share_id, url=f"/#/c/{share_id}")


@router.get("/share/{share_id}")
def citizen_page(share_id: str, deps: Annotated[Deps, Depends(get_deps)]) -> CitizenPage:
    """Read-only public view: station categories and data limits, never raw upload rows."""
    brief = _shared_brief(share_id, deps)
    summary = brief.summary
    return CitizenPage(
        share_id=share_id,
        created_at=brief.created_at,
        period=next((f.period for f in brief.facts if f.period), None),
        status_line=summary.status_line if summary else "Air quality summary",
        worst_category=summary.worst_category if summary else "insufficient_data",
        stations=brief.stations,
        data_note=data_note(brief),
        notice=NOTICE,
    )


@router.get("/share/{share_id}/advisory")
def citizen_advisory(
    share_id: str,
    request: Request,
    deps: Annotated[Deps, Depends(get_deps)],
    language: Annotated[str, Query()] = "en",
    level: Annotated[Literal["simple", "standard"], Query()] = "simple",
) -> Rendered:
    """The citizen advisory for a shared brief, in a language and reading level."""
    return render_document(_shared_brief(share_id, deps), language, level, "citizen", deps, request)


Group = Literal["everyone", "children", "older_adults", "sensitive_groups", "data"]


@router.get("/share/{share_id}/audio", response_class=Response)
def citizen_audio(
    share_id: str,
    request: Request,
    deps: Annotated[Deps, Depends(get_deps)],
    language: Annotated[str, Query()] = "en",
    level: Annotated[Literal["simple", "standard"], Query()] = "simple",
    group: Annotated[Group, Query()] = "everyone",
) -> Response:
    """WAV audio of the advisory headline and one group's advice (the Listen button)."""
    doc = citizen_advisory(share_id, request, deps, language, level)
    key = cache_key(kind="audio", share=share_id, language=language, level=level, group=group)
    hit = deps.db.cache_get(key)
    if hit is None:
        if deps.speaker is None:
            raise ApiError(503, "speech_unavailable", "Audio is not configured on this server.")
        decision = deps.limiter.check_and_record(client_ip(request))
        if not decision.allowed:
            raise ApiError(429, "rate_limited", decision.reason)
        sections = {s.key: s for s in doc.sections}
        text = fit_for_speech(f"{sections['headline'].text} {sections[group].text}")
        spoken_language = doc.language if sections[group].translated else "en"
        try:
            audio = deps.speaker.speak(text, ADVISORY_LANGUAGES[spoken_language])
        except SpeechError as exc:
            raise ApiError(502, "speech_unavailable", str(exc)) from exc
        deps.db.cache_put(key, base64.b64encode(audio).decode())
    else:
        audio = base64.b64decode(hit)
    return Response(content=audio, media_type="audio/wav")
