"""Route-table based HTTP chassis for loopback application servers."""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
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


Handler = Callable[[Request], object | Response]
OriginPolicy = Callable[[str | None], bool]


@dataclass(frozen=True)
class Route:
    method: str
    path_pattern: str
    handler: Handler

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

    def do_OPTIONS(self) -> None:
        origin = self.headers.get("Origin")
        if not self.server.origin_policy(origin):
            self._json(HTTPStatus.FORBIDDEN, {"error": "origin not allowed"})
            return
        path = urlsplit(self.path).path
        methods = sorted(route.method for route, pattern in self.server.routes if pattern.fullmatch(path))
        if not methods:
            self._json(HTTPStatus.NOT_FOUND, {"error": "route not found"})
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self._common_headers(origin)
        self.send_header("Access-Control-Allow-Methods", ", ".join(methods))
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _dispatch(self) -> None:
        origin = self.headers.get("Origin")
        if origin is not None and not self.server.origin_policy(origin):
            self._json(HTTPStatus.FORBIDDEN, {"error": "origin not allowed"})
            return
        split = urlsplit(self.path)
        matched = next(
            (
                (route, match)
                for route, pattern in self.server.routes
                if route.method == self.command and (match := pattern.fullmatch(split.path))
            ),
            None,
        )
        if matched is None:
            self._json(HTTPStatus.NOT_FOUND, {"error": "route not found"})
            return
        route, match = matched
        try:
            body, payload = self._read_body()
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
            self._json(response.status, response.payload, response.headers)
        except _HTTPError as error:
            self._json(error.status, {"error": str(error)})
        except ValidationError as error:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        except ConfigError as error:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(error)})

    def _read_body(self) -> tuple[bytes, object | None]:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            return b"", None
        try:
            length = int(raw_length)
        except ValueError as error:
            raise _HTTPError(HTTPStatus.BAD_REQUEST, "invalid Content-Length") from error
        if length < 0:
            raise _HTTPError(HTTPStatus.BAD_REQUEST, "invalid Content-Length")
        if length > self.server.max_body_bytes:
            raise _HTTPError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request body too large")
        body = self.rfile.read(length)
        if not body:
            return body, None
        try:
            return body, json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise _HTTPError(HTTPStatus.BAD_REQUEST, "invalid JSON body") from error

    def _json(self, status: int, payload: object, headers: Mapping[str, str] | None = None) -> None:
        body = (
            b""
            if status == HTTPStatus.NO_CONTENT
            else json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._common_headers(self.headers.get("Origin"))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD" and body:
            self.wfile.write(body)

    def _common_headers(self, origin: str | None) -> None:
        if origin is not None and self.server.origin_policy(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("X-Content-Type-Options", "nosniff")


class _HTTPError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(message)


def _compile_path(path_pattern: str) -> re.Pattern[str]:
    cursor = 0
    chunks: list[str] = []
    for match in re.finditer(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", path_pattern):
        chunks.append(re.escape(path_pattern[cursor : match.start()]))
        chunks.append(f"(?P<{match.group(1)}>[^/]+)")
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
