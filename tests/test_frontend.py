import re
from pathlib import Path

from fastapi.testclient import TestClient

from aqstudio.config import Settings
from aqstudio.web.app import create_app
from tests.conftest import FakeLLM

FRONTEND = Path(__file__).parent.parent / "frontend"
ALLOWED_HOSTS = {"cdnjs.cloudflare.com", "tile.openstreetmap.org"}


def _client(tmp_path: Path) -> TestClient:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=str(tmp_path / "t.sqlite3"),
        frontend_dir=str(FRONTEND),
    )
    return TestClient(create_app(settings, FakeLLM()))


def test_frontend_is_served_at_root_and_api_still_works(tmp_path: Path) -> None:
    client = _client(tmp_path)
    page = client.get("/")
    assert page.status_code == 200 and '<main id="main"' in page.text
    assert (
        "script-src 'self' https://unpkg.com https://cdnjs.cloudflare.com"
        in page.headers["content-security-policy"]
    )
    assert (
        client.get("/js/main.js").status_code == 200 and client.get("/app.css").status_code == 200
    )
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/js/main.js").headers["cache-control"] == "no-cache"


def _scripts() -> str:
    return "\n".join(p.read_text() for p in sorted((FRONTEND / "js").rglob("*.js")))


def test_frontend_never_builds_html_from_strings_and_loads_only_pinned_hosts() -> None:
    script = _scripts()
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert banned not in script
    hosts = set(re.findall(r"https?://([a-z0-9.\-]+)", script))
    assert hosts <= ALLOWED_HOSTS
    assert script.count("sha384-") == 2 and "1.9.4" in script  # pinned and integrity-checked
    html = (FRONTEND / "index.html").read_text()
    assert not re.search(r"<script(?![^>]*\bsrc=)", html) and "onclick=" not in html


def test_every_api_route_the_frontend_calls_exists_in_the_contract(tmp_path: Path) -> None:
    paths = _client(tmp_path).get("/openapi.json").json()["paths"]
    for route in (
        "/api/uploads",
        "/api/briefs",
        "/api/briefs/{brief_id}",
        "/api/briefs/{brief_id}/evidence/{fact_id}",
        "/api/briefs/{brief_id}/diff",
        "/api/briefs/{brief_id}/locations",
        "/api/briefs/{brief_id}/render",
        "/api/briefs/{brief_id}/share",
        "/api/share/{share_id}",
        "/api/share/{share_id}/advisory",
        "/api/share/{share_id}/audio",
    ):
        assert route in paths
    script = _scripts()
    for call in (
        "/uploads",
        "/briefs",
        "/evidence/",
        "/diff?against=",
        "/locations",
        "/render?",
        "/share",
    ):
        assert call in script
