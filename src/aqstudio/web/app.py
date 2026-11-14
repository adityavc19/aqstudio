"""FastAPI app factory: JSON API under /api, optional static frontend at /."""

import secrets
import time
from pathlib import Path

import anthropic
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from aqstudio.advisory.translate import SarvamTranslator, Translator
from aqstudio.config import (
    DAILY_CAP,
    RATE_LIMIT_PER_HOUR,
    UPLOAD_DAILY_CAP,
    UPLOAD_RATE_LIMIT_PER_HOUR,
    Settings,
)
from aqstudio.llm.anthropic_client import AnthropicClient
from aqstudio.llm.cache import CachedLLMClient
from aqstudio.llm.client import LLMClient
from aqstudio.llm.sarvam_client import SarvamClient
from aqstudio.store.db import Database
from aqstudio.store.limits import UsageLimiter
from aqstudio.store.repos import BriefRepo, UploadRepo
from aqstudio.web.deps import Deps
from aqstudio.web.errors import install_error_handlers
from aqstudio.web.routes import briefs, health, locations, render, uploads
from aqstudio.web.security import install_security

_SESSION_MAX_AGE = 30 * 24 * 3600


def _build_llm(settings: Settings, db: Database) -> LLMClient | None:
    """Build the real, cached LLM client for the configured provider; None if no key is set."""
    anthropic_key = settings.anthropic_api_key.get_secret_value()
    sarvam_key = settings.sarvam_api_key.get_secret_value()
    provider = settings.llm_provider
    if provider == "anthropic" or (provider == "auto" and anthropic_key):
        if not anthropic_key:
            return None
        model = settings.anthropic_model
        inner: LLMClient = AnthropicClient(anthropic.Anthropic(api_key=anthropic_key), model)
        return CachedLLMClient(inner, db, f"anthropic:{model}")
    if sarvam_key:
        model = settings.sarvam_model
        return CachedLLMClient(SarvamClient(sarvam_key, model), db, f"sarvam:{model}")
    return None


def _build_translator(settings: Settings) -> Translator | None:
    """Sarvam translator when its key is configured."""
    key = settings.sarvam_api_key.get_secret_value()
    return SarvamTranslator(key) if key else None


def create_app(
    settings: Settings | None = None,
    llm: LLMClient | None = None,
    translator: Translator | None = None,
) -> FastAPI:
    """Create the app; settings and the LLM client are injectable so tests can substitute fakes."""
    settings = settings or Settings()
    db = Database(settings.database_path)
    app = FastAPI(
        title="Civic Air Quality Briefing Studio", version="0.2.0", docs_url=None, redoc_url=None
    )
    app.state.trusted_ip_header = settings.trusted_ip_header
    app.state.deps = Deps(
        db=db,
        uploads=UploadRepo(db),
        briefs=BriefRepo(db),
        limiter=UsageLimiter(settings.database_path, RATE_LIMIT_PER_HOUR, DAILY_CAP),
        upload_limiter=UsageLimiter(
            settings.database_path, UPLOAD_RATE_LIMIT_PER_HOUR, UPLOAD_DAILY_CAP, scope="upload"
        ),
        llm=llm if llm is not None else _build_llm(settings, db),
        translator=translator or _build_translator(settings),
    )
    db.purge_expired(time.time())
    app.state.deps.briefs.fail_orphaned()
    secret = settings.session_secret.get_secret_value() or secrets.token_hex(32)
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret,
        same_site="lax",
        https_only=settings.cookie_secure,
        max_age=_SESSION_MAX_AGE,
    )
    install_security(app)
    install_error_handlers(app)
    app.include_router(health.router, prefix="/api")
    app.include_router(uploads.router, prefix="/api")
    app.include_router(briefs.router, prefix="/api")
    app.include_router(locations.router, prefix="/api")
    app.include_router(render.router, prefix="/api")
    frontend = Path(settings.frontend_dir)
    if frontend.is_dir():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app
