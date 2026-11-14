import pytest

from aqstudio.config import Settings


def test_default_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    assert Settings(_env_file=None).anthropic_model == "claude-sonnet-5-5"  # type: ignore[call-arg]


def test_api_key_not_in_repr() -> None:
    settings = Settings(anthropic_api_key="sk-secret", _env_file=None)  # type: ignore[arg-type,call-arg]
    assert "sk-secret" not in repr(settings)
