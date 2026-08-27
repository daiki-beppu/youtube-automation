"""Route-table based HTTP chassis for loopback application servers."""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Mapping, Sequence
from urllib.parse import parse_qs, unquote, urlsplit

from youtube_automation.core.errors import ConfigError, ValidationError
from youtube_automation.infrastructure.localserver.lifecycle import (
    LifecycleRecord,
    consume_stop_request,
    pid_file_path,
    remove_owned_pid_file,
    stop_request_path,
    write_pid_file,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_MAX_BODY_BYTES = 1024 * 1024


@dataclass(frozen=True)
class Request:
    """Parsed, transport-independent input passed to a route handler."""

    method: str
    path: str
    query: Mapping[str, list[str]]
    headers: Mapping[str, str]
    path_params: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""
    json: object | None = None


@dataclass(frozen=True)
class Response:
    payload: object = None
    status: int = HTTPStatus.OK
    headers: Mapping[str, str] = field(default_factory=dict)
    content_type: str = "application/json; charset=utf-8"
    after_send: Callable[[], None] | None = None
    """Run once the body has been flushed — for routes that end the process."""


Handler = Callable[[Request], object | Response]


class OriginDecision(Enum):
    """What the chassis does with a request's `Origin` before the route runs."""

    ALLOW = "allow"
    """Serve the route and echo the origin back in the CORS headers."""

    OMIT = "omit"
    """Serve the route but send no CORS headers, so a browser drops the response."""

    REJECT = "reject"
    """Answer 403 without running the route."""


@dataclass(frozen=True)
class OriginQuery:
    """Everything a policy may look at when judging one request's origin."""

    origin: str | None
    method: str
    path: str


OriginPolicy = Callable[[OriginQuery], OriginDecision]


@dataclass(frozen=True)
class Route:
    method: str
    path_pattern: str
    handler: Handler
    max_body_bytes: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "method", self.method.upper())
        if not self.path_pattern.startswith("/"):
            raise ValueError("route path_pattern must start with /")
        _compile_path(self.path_pattern)


class LocalHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        routes: Sequence[Route],
        origin_policy: OriginPolicy,
        *,
        max_body_bytes: int,
        stop_path: Path | None,
        idle_timeout_seconds: float | None,
    ) -> None:
        self.routes = tuple((route, _compile_path(route.path_pattern)) for route in routes)
        self.origin_policy = origin_policy
        self.max_body_bytes = max_body_bytes
        self.stop_path = stop_path
        self.idle_timeout_seconds = idle_timeout_seconds
        self.last_request_at = time.monotonic()
        super().__init__(address, _RequestHandler)

    def finish_request(self, request: object, client_address: tuple[str, int]) -> None:
        self.last_request_at = time.monotonic()
        super().finish_request(request, client_address)

    def service_actions(self) -> None:
        super().service_actions()
        if self.stop_path is not None and consume_stop_request(self.stop_path, os.getpid()):
            raise _StopRequested
        if (
            self.idle_timeout_seconds is not None
            and time.monotonic() - self.last_request_at >= self.idle_timeout_seconds
        ):
            raise _IdleTimeout


class _StopRequested(RuntimeError):
    pass


class _IdleTimeout(RuntimeError):
    pass


class _RequestHandler(BaseHTTPRequestHandler):
    server: LocalHTTPServer

    def log_message(self, format: str, *args: object) -> None:
        return None

    def send_error(
        self,
        code: int,
        message: str | None = None,
        explain: str | None = None,
    ) -> None:
        del explain
        try:
            fallback = HTTPStatus(code).phrase
        except ValueError:
            fallback = "???"
        body = json.dumps({"error": message or fallback}, ensure_ascii=False).encode()
        self.send_response(code)
        self._emit_headers(
            {"X-Content-Type-Options": "nosniff"},
            self._cors_headers(),
            {"Content-Type": "application/json; charset=utf-8", "Content-Length": str(len(body))},
        )
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self) -> None:
        self._dispatch()

    def do_POST(self) -> None:
        self._dispatch()

    def do_PUT(self) -> None:
        self._dispatch()

    def do_DELETE(self) -> None:
        self._dispatch()

    def do_PATCH(self) -> None:
        self._dispatch()

    def do_HEAD(self) -> None:
        self._dispatch()

    def do_CONNECT(self) -> None:
        self._dispatch()

    def do_TRACE(self) -> None:
        self._dispatch()

    def do_BREW(self) -> None:
        self._dispatch()

    def do_OPTIONS(self) -> None:
        split = urlsplit(self.path)
        if any(route.method == "OPTIONS" and pattern.fullmatch(split.path) for route, pattern in self.server.routes):
            self._dispatch()
            return
        if self._origin_decision() is OriginDecision.REJECT:
            self._json(HTTPStatus.FORBIDDEN, {"error": "origin not allowed"})
            return
        path = urlsplit(self.path).path
        methods = sorted(route.method for route, pattern in self.server.routes if pattern.fullmatch(path))
        if not methods:
            self._json(HTTPStatus.NOT_FOUND, {"error": "route not found"})
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self._emit_headers(
            {"X-Content-Type-Options": "nosniff"},
            self._cors_headers(),
            {
                "Access-Control-Allow-Methods": ", ".join(methods),
                "Access-Control-Allow-Headers": "Content-Type",
                "Content-Length": "0",
            },
        )

    def _dispatch(self) -> None:
        if self._origin_decision() is OriginDecision.REJECT:
            self._json(HTTPStatus.FORBIDDEN, {"error": "origin not allowed"})
            return
        split = urlsplit(self.path)
        path_matches = [
            (route, match) for route, pattern in self.server.routes if (match := pattern.fullmatch(split.path))
        ]
        matched = next((entry for entry in path_matches if entry[0].method == self.command), None)
        if matched is None:
            status = HTTPStatus.METHOD_NOT_ALLOWED if path_matches else HTTPStatus.NOT_FOUND
            self._json(status, {"error": "method not allowed" if path_matches else "route not found"})
            return
        route, match = matched
        try:
            body, payload = self._read_body(route.max_body_bytes)
            incoming = Request(
                method=self.command,
                path=split.path,
                query=parse_qs(split.query, keep_blank_values=True),
                headers={key: value for key, value in self.headers.items()},
                path_params={key: unquote(value) for key, value in match.groupdict().items()},
                body=body,
                json=payload,
            )
            result = route.handler(incoming)
            response = result if isinstance(result, Response) else Response(result)
            if isinstance(response.payload, bytes):
                self._bytes(response.status, response.payload, response.content_type, response.headers)
            else:
                self._json(response.status, response.payload, response.headers)
            if response.after_send is not None:
                self.wfile.flush()
                response.after_send()
        except _HTTPError as error:
            self._json(error.status, {"error": str(error)})
        except ValidationError as error:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        except ConfigError as error:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(error)})

    def _read_body(self, route_limit: int | None) -> tuple[bytes, object | None]:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            return b"", None
        try:
            length = int(raw_length)
        except ValueError as error:
            raise _HTTPError(HTTPStatus.BAD_REQUEST, "Bad Request") from error
        if length < 0:
            raise _HTTPError(HTTPStatus.BAD_REQUEST, "Bad Request")
        limit = route_limit if route_limit is not None else self.server.max_body_bytes
        if length > limit:
            raise _HTTPError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Payload Too Large")
        body = self.rfile.read(length)
        if not body:
            return body, None
        try:
            return body, json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise _HTTPError(HTTPStatus.BAD_REQUEST, "Bad Request") from error

    def _json(self, status: int, payload: object, headers: Mapping[str, str] | None = None) -> None:
        body = (
            b""
            if status == HTTPStatus.NO_CONTENT
            else json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        )
        self._bytes(status, body, "application/json; charset=utf-8", headers or {})

    def _bytes(self, status: int, body: bytes, content_type: str, headers: Mapping[str, str]) -> None:
        self.send_response(status)
        self._emit_headers(
            {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
            self._cors_headers(),
            headers,
            {"Content-Type": content_type, "Content-Length": str(len(body))},
        )
        if self.command != "HEAD" and body:
            self.wfile.write(body)

    def _request_origin(self) -> str | None:
        headers = getattr(self, "headers", None)
        return headers.get("Origin") if headers is not None else None

    def _origin_decision(self) -> OriginDecision:
        """Judge the request origin once, so every response path agrees on it.

        Routes never emit CORS headers themselves; the chassis owns the decision
        and the headers derived from it (#4452).
        """
        cached = getattr(self, "_origin_decision_cache", None)
        if cached is not None:
            return cached
        query = OriginQuery(
            self._request_origin(),
            getattr(self, "command", ""),
            urlsplit(getattr(self, "path", "")).path,
        )
        decision = self.server.origin_policy(query)
        self._origin_decision_cache = decision
        return decision

    def _cors_headers(self) -> Mapping[str, str]:
        origin = self._request_origin()
        if origin is None or self._origin_decision() is not OriginDecision.ALLOW:
            return {}
        return {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}

    def _emit_headers(self, *sources: Mapping[str, str]) -> None:
        """Send each header name exactly once; later sources override earlier ones.

        route handler が自前で CORS ヘッダーを載せる場合（chassis へ載せ替えた
        collection server 等）、chassis 側の既定値と同名ヘッダーが二重送信されると
        ブラウザの CORS 検証が壊れるため、送出前に名前で畳み込む（#4452）。
        """
        merged: dict[str, tuple[str, str]] = {}
        for source in sources:
            for key, value in source.items():
                merged[key.lower()] = (key, value)
        for key, value in merged.values():
            self.send_header(key, value)
        self.end_headers()


class _HTTPError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(message)


def _compile_path(path_pattern: str) -> re.Pattern[str]:
    cursor = 0
    chunks: list[str] = []
    for match in re.finditer(r"\{([A-Za-z_][A-Za-z0-9_]*)(\*)?\}", path_pattern):
        chunks.append(re.escape(path_pattern[cursor : match.start()]))
        chunks.append(f"(?P<{match.group(1)}>{'.+' if match.group(2) else '[^/]+'})")
        cursor = match.end()
    chunks.append(re.escape(path_pattern[cursor:]))
    try:
        return re.compile("".join(chunks))
    except re.error as error:
        raise ValueError(f"invalid route path_pattern: {path_pattern}") from error


def create_server(
    routes: Sequence[Route],
    *,
    port: int,
    origin_policy: OriginPolicy,
    host: str = DEFAULT_HOST,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    stop_path: Path | None = None,
    idle_timeout_seconds: float | None = None,
) -> LocalHTTPServer:
    """Build the chassis separately so integration tests need no subprocess."""
    if max_body_bytes <= 0:
        raise ValueError("max_body_bytes must be positive")
    return LocalHTTPServer(
        (host, port),
        routes,
        origin_policy,
        max_body_bytes=max_body_bytes,
        stop_path=stop_path,
        idle_timeout_seconds=idle_timeout_seconds,
    )


def serve(
    routes: Sequence[Route],
    *,
    server_kind: str,
    port: int,
    origin_policy: OriginPolicy,
    host: str = DEFAULT_HOST,
    state_root: Path = Path("."),
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    idle_timeout_seconds: float | None = None,
) -> None:
    """Serve routes and own the shared PID, stop, and idle lifecycle."""
    pid_path = pid_file_path(state_root, port, server_kind=server_kind)
    stop_path = stop_request_path(state_root, port, server_kind=server_kind)
    record = LifecycleRecord(os.getpid(), str(uuid.uuid4()), f"{host}:{port}")
    write_pid_file(pid_path, record)
    server: LocalHTTPServer | None = None
    try:
        server = create_server(
            routes,
            host=host,
            port=port,
            origin_policy=origin_policy,
            max_body_bytes=max_body_bytes,
            stop_path=stop_path,
            idle_timeout_seconds=idle_timeout_seconds,
        )
        server.serve_forever()
    except (_StopRequested, _IdleTimeout):
        pass
    finally:
        if server is not None:
            server.server_close()
        remove_owned_pid_file(pid_path, os.getpid())
        stop_path.unlink(missing_ok=True)
