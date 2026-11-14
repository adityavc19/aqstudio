"""FastAPI app: upload or paste a long-format CSV and get a verified brief."""

from collections import Counter
from pathlib import Path
from typing import Annotated

import anthropic
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from aqstudio.clean.long import clean_long
from aqstudio.config import MAX_UPLOAD_BYTES, Settings
from aqstudio.facts.engine import build_facts
from aqstudio.ingest.long_csv import IngestError, parse_long_csv
from aqstudio.llm.anthropic_client import AnthropicInterpreter
from aqstudio.llm.base import Interpreter, LLMError
from aqstudio.quality.detectors import detect_all
from aqstudio.schemas import Persona
from aqstudio.verify.claims import verify_claims

_BASE = Path(__file__).parent
_ALLOWED_SUFFIXES = {".csv", ".txt"}
_CSP = "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"


def _default_interpreter() -> Interpreter | None:
    """Build the real interpreter, or None when no API key is configured."""
    settings = Settings()
    key = settings.anthropic_api_key.get_secret_value()
    if not key:
        return None
    return AnthropicInterpreter(anthropic.Anthropic(api_key=key), settings.anthropic_model)


def create_app(interpreter: Interpreter | None = None) -> FastAPI:
    """Create the app; the interpreter is injected so tests can substitute a fake."""
    app = FastAPI(title="Civic Air Quality Briefing Studio", docs_url=None, redoc_url=None)
    templates = Jinja2Templates(directory=_BASE / "templates")
    app.mount("/static", StaticFiles(directory=_BASE / "static"), name="static")
    resolved = interpreter if interpreter is not None else _default_interpreter()

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        response: Response = await call_next(request)
        response.headers["Content-Security-Policy"] = _CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    def page(request: Request, name: str, status: int = 200, **ctx: object) -> HTMLResponse:
        return templates.TemplateResponse(request, name, ctx, status_code=status)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return page(request, "index.html", personas=list(Persona))

    @app.post("/brief", response_class=HTMLResponse)
    async def brief(
        request: Request,
        persona: Annotated[Persona, Form()],
        pasted: Annotated[str, Form()] = "",
        file: Annotated[UploadFile | None, File()] = None,
    ) -> HTMLResponse:
        def fail(message: str, status: int) -> HTMLResponse:
            return page(request, "error.html", status, message=message)

        text = pasted
        if file is not None and file.filename:
            if Path(file.filename).suffix.lower() not in _ALLOWED_SUFFIXES:
                return fail("Only .csv or .txt files are accepted.", 415)
            data = await file.read(MAX_UPLOAD_BYTES + 1)
            if len(data) > MAX_UPLOAD_BYTES:
                return fail("Upload exceeds the maximum file size.", 413)
            try:
                text = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                return fail("The file is not valid UTF-8 text.", 400)
        try:
            cleaned = clean_long(parse_long_csv(text))
        except IngestError as exc:
            return fail(str(exc), 400)
        flags = detect_all(cleaned.readings)
        facts = build_facts(cleaned.readings, flags)
        if resolved is None:
            return fail("The AI service is not configured on this server (no API key).", 503)
        try:
            drafts = resolved.interpret_facts(
                facts, dict(Counter(f.kind.value for f in flags)), persona
            )
        except LLMError as exc:
            return fail(f"Could not generate the interpretation: {exc} No brief was produced.", 502)
        return page(
            request,
            "brief.html",
            persona=persona,
            claims=verify_claims(drafts, facts),
            facts=facts,
            flags=flags,
            ledger=cleaned.ledger,
            ledger_counts=dict(Counter(e.rule for e in cleaned.ledger)),
        )

    return app
