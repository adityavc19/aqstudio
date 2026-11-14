import json

import httpx
import pytest

from aqstudio.llm.client import LLMError
from aqstudio.llm.sarvam_client import SarvamClient
from aqstudio.schemas import Fact, Persona, ReliabilityGrade

FACT = Fact(
    id="F1",
    kind="pollutant_mean",
    values={"mean": 1.0},
    coverage_pct=90,
    reliability_grade=ReliabilityGrade.GOOD,
)
GOOD = json.dumps(
    {"claims": [{"text": "ok", "fact_ids": ["F1"], "confidence": 0.5, "quoted_values": []}]}
)


def _client(
    replies: list[tuple[int, str]],
    seen: list[dict[str, object]],
    sleeps: list[float] | None = None,
) -> SarvamClient:
    queue = iter(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer secret-key"
        status, content = next(queue)
        body = {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
        return httpx.Response(status, json=body)

    return SarvamClient(
        "secret-key",
        "sarvam-105b",
        httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=(sleeps if sleeps is not None else []).append,
    )


def test_valid_output_parsed_and_request_is_schema_constrained() -> None:
    seen: list[dict[str, object]] = []
    [claim] = _client([(200, GOOD)], seen).interpret_facts([FACT], Persona.SCHOOL, None)
    assert claim.fact_ids == ["F1"]
    request = seen[0]
    assert request["response_format"]["type"] == "json_schema"  # type: ignore[index]
    assert request["reasoning_effort"] == "none" and "<facts>" in request["messages"][1]["content"]  # type: ignore[index]


def test_invalid_then_valid_retries_once_with_the_error() -> None:
    seen: list[dict[str, object]] = []
    client = _client([(200, "not json"), (200, GOOD)], seen)
    assert client.interpret_facts([FACT], Persona.SCHOOL, None)
    assert len(seen) == 2 and "last output was invalid" in seen[1]["messages"][1]["content"]  # type: ignore[index]


def test_two_invalid_outputs_raise_honest_error() -> None:
    with pytest.raises(LLMError, match="failed validation twice"):
        _client([(200, "{}"), (200, "[]")], []).interpret_facts([FACT], Persona.SCHOOL, None)


def test_http_failure_is_generic_and_never_leaks_the_key() -> None:
    with pytest.raises(LLMError) as info:
        _client([(402, "")], []).interpret_facts([FACT], Persona.SCHOOL, None)
    assert "HTTP 402" in str(info.value) and "secret-key" not in str(info.value)


def test_retries_overload_with_backoff_then_succeeds_and_gives_up_after_three() -> None:
    sleeps: list[float] = []
    seen: list[dict[str, object]] = []
    client = _client([(503, ""), (429, ""), (200, GOOD)], seen, sleeps)
    assert client.interpret_facts([FACT], Persona.SCHOOL, None)
    assert len(seen) == 3 and sleeps == [1.0, 2.0]
    with pytest.raises(LLMError, match="HTTP 429"):
        _client([(429, "")] * 3, [], []).interpret_facts([FACT], Persona.SCHOOL, None)
