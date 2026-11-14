"""Dependencies shared by routes, held on app.state and injected at app creation."""

import uuid
from dataclasses import dataclass

from fastapi import Request

from aqstudio.advisory.translate import Translator
from aqstudio.llm.client import LLMClient
from aqstudio.store.db import Database
from aqstudio.store.limits import UsageLimiter
from aqstudio.store.repos import BriefRepo, UploadRepo


@dataclass(frozen=True)
class Deps:
    """Everything routes need; the LLM client is None when no API key is configured."""

    db: Database
    uploads: UploadRepo
    briefs: BriefRepo
    limiter: UsageLimiter
    upload_limiter: UsageLimiter
    llm: LLMClient | None
    translator: Translator | None = None


def get_deps(request: Request) -> Deps:
    """Return the app's dependencies."""
    deps: Deps = request.app.state.deps
    return deps


def session_id(request: Request, create: bool = False) -> str | None:
    """The signed-cookie session id for this browser; created on demand."""
    sid = request.session.get("sid")
    if sid is None and create:
        sid = uuid.uuid4().hex
        request.session["sid"] = sid
    return str(sid) if sid else None
