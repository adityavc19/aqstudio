from pathlib import Path

from fastapi.testclient import TestClient

from aqstudio.store.limits import UsageLimiter
from aqstudio.web.app import create_app
from tests.test_web import FakeInterpreter, _csv


def test_per_ip_limit_and_window_expiry(tmp_path: Path) -> None:
    now = [1000.0]
    limiter = UsageLimiter(str(tmp_path / "l.db"), 2, 100, clock=lambda: now[0])
    assert limiter.check_and_record("a").allowed
    assert limiter.check_and_record("a").allowed
    assert not limiter.check_and_record("a").allowed
    assert limiter.check_and_record("b").allowed
    now[0] += 3601
    assert limiter.check_and_record("a").allowed


def test_global_daily_cap(tmp_path: Path) -> None:
    limiter = UsageLimiter(str(tmp_path / "l.db"), 10, 2)
    assert limiter.check_and_record("a").allowed
    assert limiter.check_and_record("b").allowed
    decision = limiter.check_and_record("c")
    assert not decision.allowed and "daily" in decision.reason


def test_route_returns_429_and_blocks_cross_origin(tmp_path: Path) -> None:
    limiter = UsageLimiter(str(tmp_path / "l.db"), 1, 100)
    client = TestClient(create_app(FakeInterpreter(), limiter))
    data = {"persona": "school", "pasted": _csv()}
    assert client.post("/brief", data=data).status_code == 200
    assert client.post("/brief", data=data).status_code == 429
    evil = client.post("/brief", data=data, headers={"origin": "https://evil.example"})
    assert evil.status_code == 403
