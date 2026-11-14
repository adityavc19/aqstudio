from fastapi.testclient import TestClient

from aqstudio.advisory.compose import strip_fact_markers
from aqstudio.advisory.translate import TranslationError, numbers_preserved
from aqstudio.config import Settings
from aqstudio.web.app import create_app
from tests.conftest import FakeLLM, hourly_csv


class FakeTranslator:
    """Prefixes text with the language; can drop digits or fail to test the safeguards."""

    def __init__(self, mode: str = "ok") -> None:
        self.mode = mode

    def translate(self, text: str, target: str) -> str:
        if self.mode == "fail":
            raise TranslationError("down")
        if self.mode == "drop_numbers":
            return f"[{target}] " + "".join(c for c in text if not c.isdigit())
        devanagari = str.maketrans("0123456789", "०१२३४५६७८९")
        return f"[{target}] {text.translate(devanagari)}"


def _brief(client: TestClient) -> str:
    upload = client.post("/api/uploads", json={"text": hourly_csv()}).json()["upload_id"]
    return str(
        client.post("/api/briefs", json={"upload_id": upload, "persona": "school"}).json()[
            "brief_id"
        ]
    )


def test_numbers_survive_translation_in_any_digit_script() -> None:
    assert numbers_preserved("AQI is 112 at 3 sites", "एक्यूआई ११२ है, ३ जगह")
    assert not numbers_preserved("AQI is 112", "एक्यूआई है")


def test_internal_note_is_built_from_verified_content_without_new_ai_text(
    settings: Settings,
) -> None:
    llm = FakeLLM()
    client = TestClient(create_app(settings, llm))
    brief_id = _brief(client)
    calls = llm.calls
    note = client.get(f"/api/briefs/{brief_id}/render", params={"format": "note"}).json()
    assert [s["key"] for s in note["sections"]] == [
        "summary",
        "findings",
        "actions",
        "data",
        "limits",
    ]
    assert (
        "Grounded" in note["sections"][1]["text"] and "Invented" not in note["sections"][1]["text"]
    )
    assert llm.calls == calls


def test_citizen_advisory_has_group_guidance_verified_and_cached(settings: Settings) -> None:
    llm = FakeLLM()
    client = TestClient(create_app(settings, llm))
    brief_id = _brief(client)
    first = client.get(f"/api/briefs/{brief_id}/render").json()
    keys = [s["key"] for s in first["sections"]]
    assert keys == ["headline", "everyone", "children", "older_adults", "sensitive_groups", "data"]
    assert all(s["verified"] for s in first["sections"]) and "doctor" in first["disclaimer"]
    calls = llm.calls
    assert client.get(f"/api/briefs/{brief_id}/render").json() == first and llm.calls == calls


def test_translation_keeps_numbers_or_falls_back_to_english(settings: Settings) -> None:
    good = TestClient(create_app(settings, FakeLLM(), FakeTranslator()))
    brief_id = _brief(good)
    hindi = good.get(f"/api/briefs/{brief_id}/render", params={"language": "hi"}).json()
    assert hindi["citations_preserved"] and all(s["translated"] for s in hindi["sections"])
    assert hindi["sections"][0]["text"].startswith("[hi-IN]")
    lossy = TestClient(create_app(settings, FakeLLM(), FakeTranslator("drop_numbers")))
    kannada = lossy.get(f"/api/briefs/{brief_id}/render", params={"language": "kn"}).json()
    headline = kannada["sections"][0]
    assert not kannada["citations_preserved"] and not headline["translated"]
    assert any(ch.isdigit() for ch in headline["text"])
    down = TestClient(create_app(settings, FakeLLM(), FakeTranslator("fail")))
    marathi = down.get(f"/api/briefs/{brief_id}/render", params={"language": "mr"}).json()
    assert not marathi["citations_preserved"] and not any(
        s["translated"] for s in marathi["sections"]
    )


def test_render_rejects_unknown_language_and_missing_translator(settings: Settings) -> None:
    client = TestClient(create_app(settings, FakeLLM()))
    brief_id = _brief(client)
    bad = client.get(f"/api/briefs/{brief_id}/render", params={"language": "xx"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "unsupported_language"
    none = client.get(f"/api/briefs/{brief_id}/render", params={"language": "hi"})
    assert none.status_code == 503 and none.json()["error"]["code"] == "translation_unavailable"


def test_internal_fact_markers_never_reach_citizen_text() -> None:
    assert strip_fact_markers("AQI is 326 (Very Poor) [F12].") == "AQI is 326 (Very Poor)."
    assert strip_fact_markers("Mean 42 (F3, F4) today") == "Mean 42 today"
    assert strip_fact_markers("Use PM2.5 masks (N95)") == "Use PM2.5 masks (N95)"
