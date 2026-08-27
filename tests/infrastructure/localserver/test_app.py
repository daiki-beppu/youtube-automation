from __future__ import annotations

import http.client
import threading
from contextlib import contextmanager
from typing import Iterator

import pytest

from youtube_automation.core.errors import ConfigError, ValidationError
from youtube_automation.infrastructure.localserver.app import (
    OriginDecision,
    OriginQuery,
    Request,
    Response,
    Route,
    create_server,
)


def _reject_unknown_origins(query: OriginQuery) -> OriginDecision:
    if query.origin is None:
        return OriginDecision.OMIT
    if query.origin == "https://allowed.example":
        return OriginDecision.ALLOW
    return OriginDecision.REJECT


@contextmanager
def running(routes: list[Route], *, max_body_bytes: int = 32) -> Iterator[tuple[str, int]]:
    server = create_server(
        routes,
        port=0,
        origin_policy=_reject_unknown_origins,
        max_body_bytes=max_body_bytes,
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def request(address: tuple[str, int], method: str, path: str, **kwargs: object) -> http.client.HTTPResponse:
    connection = http.client.HTTPConnection(*address)
    connection.request(method, path, **kwargs)
    return connection.getresponse()


def test_route_params_and_json_payload_do_not_require_a_socket_in_handler() -> None:
    seen: list[Request] = []

    def update(incoming: Request) -> object:
        seen.append(incoming)
        return {"track": incoming.path_params["track"], "value": incoming.json["value"]}

    with running([Route("PUT", "/tracks/{track}", update)]) as address:
        response = request(
            address,
            "PUT",
            "/tracks/intro?preview=1",
            body=b'{"value":2}',
            headers={"Origin": "https://allowed.example", "Content-Length": "11"},
        )
        assert response.status == 200
        assert response.read() == b'{"track":"intro","value":2}'
    assert seen[0].query == {"preview": ["1"]}


def test_origin_rejection_and_options_are_handled_by_chassis() -> None:
    with running([Route("POST", "/items", lambda _request: {"ok": True})]) as address:
        denied = request(address, "POST", "/items", body=b"{}", headers={"Origin": "https://denied.example"})
        assert denied.status == 403
        assert denied.getheader("Content-Type") == "application/json; charset=utf-8"

        options = request(
            address,
            "OPTIONS",
            "/items",
            headers={"Origin": "https://allowed.example", "Access-Control-Request-Method": "POST"},
        )
        assert options.status == 204
        assert options.getheader("Access-Control-Allow-Origin") == "https://allowed.example"
        assert "POST" in options.getheader("Access-Control-Allow-Methods")


def test_body_limit_is_rejected_before_handler() -> None:
    called = False

    def handler(_request: Request) -> object:
        nonlocal called
        called = True
        return {}

    with running([Route("POST", "/items", handler)], max_body_bytes=4) as address:
        response = request(address, "POST", "/items", body=b"12345", headers={"Content-Length": "5"})
        assert response.status == 413
    assert not called


def test_route_body_limit_can_be_stricter_than_server_limit() -> None:
    route = Route("POST", "/items", lambda _request: {}, max_body_bytes=2)
    with running([route], max_body_bytes=32) as address:
        response = request(address, "POST", "/items", body=b"123", headers={"Content-Length": "3"})
    assert response.status == 413


def test_binary_response_is_written_without_json_encoding() -> None:
    route = Route("GET", "/asset", lambda _request: Response(b"asset", content_type="audio/mpeg"))
    with running([route]) as address:
        response = request(address, "GET", "/asset")
        assert response.status == 200
        assert response.getheader("Content-Type") == "audio/mpeg"
        assert response.read() == b"asset"


def test_route_supplied_headers_replace_chassis_defaults_instead_of_duplicating() -> None:
    """route が自前で CORS ヘッダーを返す場合でも同名ヘッダーを二重送信しない（#4452）."""
    route = Route(
        "GET",
        "/asset",
        lambda _request: Response(
            b"asset",
            content_type="audio/mpeg",
            headers={"Access-Control-Allow-Origin": "https://allowed.example", "Vary": "Origin"},
        ),
    )
    with running([route]) as address:
        connection = http.client.HTTPConnection(*address)
        connection.request("GET", "/asset", headers={"Origin": "https://allowed.example"})
        response = connection.getresponse()
        assert response.status == 200
        assert response.getheader("Content-Type") == "audio/mpeg"
        assert response.msg.get_all("Access-Control-Allow-Origin") == ["https://allowed.example"]
        assert response.msg.get_all("Vary") == ["Origin"]
        assert response.msg.get_all("Content-Length") == ["5"]


@pytest.mark.parametrize(
    ("error", "status"),
    [(ValidationError("bad input"), 400), (ConfigError("bad config"), 500)],
)
def test_domain_errors_are_mapped_to_json(error: Exception, status: int) -> None:
    def fail(_request: Request) -> object:
        raise error

    with running([Route("GET", "/fail", fail)]) as address:
        response = request(address, "GET", "/fail")
        assert response.status == status
        assert response.read().decode() == f'{{"error":"{error}"}}'
