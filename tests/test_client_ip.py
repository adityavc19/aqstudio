from types import SimpleNamespace

from starlette.requests import Request

from aqstudio.web.security import client_ip


def _request(headers: dict[str, str], trusted: str = "") -> Request:
    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": ("9.9.9.9", 1234),
        "app": SimpleNamespace(state=SimpleNamespace(trusted_ip_header=trusted)),
    }
    return Request(scope)


def test_untrusted_header_is_ignored_so_it_cannot_be_spoofed() -> None:
    request = _request({"cf-connecting-ip": "1.1.1.1"})
    assert client_ip(request) == "9.9.9.9"


def test_configured_header_wins_over_forwarded_for_and_socket() -> None:
    headers = {"cf-connecting-ip": "1.1.1.1", "x-forwarded-for": "2.2.2.2, 3.3.3.3"}
    assert client_ip(_request(headers, "CF-Connecting-IP")) == "1.1.1.1"


def test_falls_back_to_last_forwarded_entry_then_socket() -> None:
    assert (
        client_ip(_request({"x-forwarded-for": "2.2.2.2, 3.3.3.3"}, "CF-Connecting-IP"))
        == "3.3.3.3"
    )
    assert client_ip(_request({}, "CF-Connecting-IP")) == "9.9.9.9"
