"""Loopback discovery registry for running ``yt-collection-serve`` processes."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Protocol

from youtube_automation.infrastructure.errors import DiscoveryRegistryError

DISCOVERY_HOST = "127.0.0.1"
DISCOVERY_PORT = 7872
DISCOVERY_PATH = "/.well-known/yt-collection-serve"
DISCOVERY_SCHEMA_VERSION = 1
DISCOVERY_TTL_SECONDS = 30
DISCOVERY_HEARTBEAT_SECONDS = 11
DISCOVERY_STARTUP_TIMEOUT_SECONDS = 3
DISCOVERY_STARTUP_RETRY_SECONDS = 0.05
DISCOVERY_REQUEST_TIMEOUT_SECONDS = 0.25
MAX_REGISTRATION_BODY_BYTES = 16 * 1024
MAX_INSTANCE_ID_LENGTH = 128
MAX_REGISTRY_ENTRIES = 128


class RegistryCapacityError(DiscoveryRegistryError):
    """Raised when a new registration would exceed the bounded registry."""


def _is_loopback_http_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    hostname = parsed.hostname or ""
    return (
        parsed.scheme == "http"
        and parsed.username is None
        and parsed.password is None
        and port is not None
        and (hostname in {"localhost", "127.0.0.1"} or hostname.endswith(".localhost"))
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
    )


def _validated_registration(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("registration must be an object")
    instance_id = payload.get("instance_id")
    server_info = payload.get("server_info")
    instance_id = _validated_instance_id(instance_id)
    if not isinstance(server_info, dict):
        raise ValueError("server_info must be an object")
    string_fields = ("channel_name", "channel_short", "hostname", "base_url", "label")
    if any(not isinstance(server_info.get(field), str) or not server_info[field] for field in string_fields):
        raise ValueError("server_info string fields are required")
    port = server_info.get("port")
    if not isinstance(port, int) or isinstance(port, bool) or not 0 < port <= 65535:
        raise ValueError("server_info.port must be a valid port")
    if not _is_loopback_http_url(server_info["base_url"]):
        raise ValueError("server_info.base_url must be loopback HTTP")
    parsed = urllib.parse.urlsplit(str(server_info["base_url"]))
    if parsed.hostname != server_info["hostname"] or parsed.port != port:
        raise ValueError("server_info hostname and port must match base_url")
    return {"instance_id": instance_id, "server_info": dict(server_info)}


def _validated_instance_id(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("instance_id must be a non-empty string")
    if len(value) > MAX_INSTANCE_ID_LENGTH:
        raise ValueError(f"instance_id must be at most {MAX_INSTANCE_ID_LENGTH} characters")
    return value


class RegistryState:
    """Thread-safe in-memory registrations with exclusive TTL expiry."""

    def __init__(
        self,
        *,
        ttl_seconds: float = DISCOVERY_TTL_SECONDS,
        clock: Callable[[], float] = time.time,
        monotonic_clock: Callable[[], float] | None = None,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._monotonic_clock = (
            monotonic_clock if monotonic_clock is not None else (clock if clock is not time.time else time.monotonic)
        )
        self._entries: dict[str, dict[str, object]] = {}
        self._lock = threading.Lock()

    def register(self, payload: object) -> None:
        registration = _validated_registration(payload)
        with self._lock:
            self._discard_expired_locked()
            instance_id = str(registration["instance_id"])
            if instance_id not in self._entries and len(self._entries) >= MAX_REGISTRY_ENTRIES:
                raise RegistryCapacityError(f"registry is limited to {MAX_REGISTRY_ENTRIES} entries")
            self._entries[instance_id] = {
                **registration,
                "expires_at": self._clock() + self.ttl_seconds,
                "expires_monotonic": self._monotonic_clock() + self.ttl_seconds,
            }

    def unregister(self, instance_id: str) -> None:
        with self._lock:
            self._entries.pop(instance_id, None)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            self._discard_expired_locked()
            servers = sorted(
                (
                    {key: value for key, value in entry.items() if key != "expires_monotonic"}
                    for entry in self._entries.values()
                ),
                key=lambda entry: str(dict(entry["server_info"])["base_url"]),
            )
        return {
            "schema_version": DISCOVERY_SCHEMA_VERSION,
            "ttl_seconds": self.ttl_seconds,
            "servers": servers,
        }

    def _discard_expired_locked(self) -> None:
        now = self._monotonic_clock()
        self._entries = {
            instance_id: entry
            for instance_id, entry in self._entries.items()
            if float(entry["expires_monotonic"]) > now
        }


def create_registry_server(host: str, port: int, state: RegistryState) -> ThreadingHTTPServer:
    class RegistryHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if not handle_registry_request(self, state):
                _write_registry_json(self, 404, {"error": "not found"})

        def do_POST(self) -> None:
            if not handle_registry_request(self, state):
                _write_registry_json(self, 404, {"error": "not found"})

        def do_DELETE(self) -> None:
            if not handle_registry_request(self, state):
                _write_registry_json(self, 404, {"error": "not found"})

        def _method_not_allowed(self) -> None:
            status = 405 if self.path == DISCOVERY_PATH else 404
            payload = {"error": "method not allowed" if status == 405 else "not found"}
            _write_registry_json(self, status, payload)

        do_CONNECT = _method_not_allowed
        do_HEAD = _method_not_allowed
        do_OPTIONS = _method_not_allowed
        do_PATCH = _method_not_allowed
        do_PUT = _method_not_allowed
        do_TRACE = _method_not_allowed

        def send_error(
            self,
            code: int,
            message: str | None = None,
            explain: str | None = None,
        ) -> None:
            if code == 501:
                self._method_not_allowed()
                return
            super().send_error(code, message, explain)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return ThreadingHTTPServer((host, port), RegistryHandler)


def _write_registry_json(handler: BaseHTTPRequestHandler, status: int, payload: object) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_registry_json(handler: BaseHTTPRequestHandler) -> object:
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except ValueError as error:
        raise ValueError("invalid Content-Length") from error
    if length <= 0:
        raise ValueError("request body is required")
    if length > MAX_REGISTRATION_BODY_BYTES:
        raise OverflowError("request body is too large")
    return json.loads(handler.rfile.read(length))


def handle_registry_request(handler: BaseHTTPRequestHandler, state: RegistryState) -> bool:
    """Serve the discovery contract from either a dedicated or collection server."""
    if handler.path != DISCOVERY_PATH:
        return False
    if handler.command == "GET":
        _write_registry_json(handler, 200, state.snapshot())
        return True
    if handler.command not in {"POST", "DELETE"}:
        _write_registry_json(handler, 405, {"error": "method not allowed"})
        return True
    if handler.headers.get("Origin") is not None:
        _write_registry_json(handler, 403, {"error": "Origin header is not allowed"})
        return True
    if handler.headers.get_content_type() != "application/json":
        _write_registry_json(handler, 415, {"error": "Content-Type must be application/json"})
        return True
    try:
        payload = _read_registry_json(handler)
        if handler.command == "POST":
            state.register(payload)
        else:
            if not isinstance(payload, dict):
                raise ValueError("unregistration must be an object")
            state.unregister(_validated_instance_id(payload.get("instance_id")))
    except RegistryCapacityError as error:
        _write_registry_json(handler, 429, {"error": str(error)})
    except OverflowError as error:
        _write_registry_json(handler, 413, {"error": str(error)})
    except (json.JSONDecodeError, ValueError) as error:
        _write_registry_json(handler, 400, {"error": str(error)})
    else:
        _write_registry_json(handler, 200, {})
    return True


class RegistrationTransport(Protocol):
    def register(self, payload: dict[str, object]) -> None: ...

    def unregister(self, instance_id: str) -> None: ...


class _HttpTransport:
    def __init__(self, endpoint: str, *, timeout_seconds: float = DISCOVERY_REQUEST_TIMEOUT_SECONDS) -> None:
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds

    def _send(self, method: str, payload: object) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        request = urllib.request.Request(self.endpoint, data=body, method=method)
        request.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(request, timeout=self.timeout_seconds):
            return

    def register(self, payload: dict[str, object]) -> None:
        self._send("POST", payload)

    def unregister(self, instance_id: str) -> None:
        self._send("DELETE", {"instance_id": instance_id})


class DiscoveryLifecycle:
    """Heartbeat registration plus fixed-port owner/follower takeover."""

    def __init__(
        self,
        *,
        server_info: dict[str, object],
        instance_id: str | None = None,
        heartbeat_seconds: float = DISCOVERY_HEARTBEAT_SECONDS,
        wait: Callable[[float], bool] | None = None,
        transport: RegistrationTransport | None = None,
        embedded_registry_state: RegistryState | None = None,
        discovery_host: str = DISCOVERY_HOST,
        discovery_port: int = DISCOVERY_PORT,
        startup_timeout_seconds: float = DISCOVERY_STARTUP_TIMEOUT_SECONDS,
        startup_retry_seconds: float = DISCOVERY_STARTUP_RETRY_SECONDS,
        request_timeout_seconds: float = DISCOVERY_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self.server_info = server_info
        self.instance_id = instance_id or uuid.uuid4().hex
        self.heartbeat_seconds = heartbeat_seconds
        self._stop_event = threading.Event()
        self._wait = wait or self._stop_event.wait
        self._transport = transport
        self._embedded_registry_state = embedded_registry_state
        self._host = discovery_host
        self._port = discovery_port
        self._startup_timeout_seconds = startup_timeout_seconds
        self._startup_retry_seconds = startup_retry_seconds
        self._request_timeout_seconds = request_timeout_seconds
        self._registry_server: ThreadingHTTPServer | None = None
        self._registry_thread: threading.Thread | None = None
        self._state: RegistryState | None = None
        self._registered = False
        self.is_owner = False
        self.registry_port = discovery_port
        self.heartbeat_thread = threading.Thread(target=lambda: None)
        self.ownership_thread = threading.Thread(target=lambda: None)

    @classmethod
    def for_loopback_test(cls, server_info: dict[str, object], *, discovery_port: int) -> DiscoveryLifecycle:
        return cls(server_info=server_info, discovery_port=discovery_port, heartbeat_seconds=0.1)

    def _endpoint(self) -> str:
        return f"http://{self._host}:{self.registry_port}{DISCOVERY_PATH}"

    def _become_owner(self) -> bool:
        try:
            state = RegistryState()
            server = create_registry_server(self._host, self._port, state)
        except OSError as bind_error:
            if self._registry_endpoint_is_compatible():
                return False
            # A competing registry may be between bind and serve_forever.  The
            # heartbeat retries that transient state; an HTTP responder with an
            # incompatible contract is a permanent conflict and must be loud.
            if self._endpoint_responds():
                raise DiscoveryRegistryError("discovery registry endpoint has incompatible schema") from bind_error
            return False
        self._state = state
        self._registry_server = server
        self.registry_port = int(server.server_address[1])
        self.is_owner = True
        self._registry_thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._registry_thread.start()
        return True

    def _endpoint_responds(self) -> bool:
        try:
            with urllib.request.urlopen(self._endpoint(), timeout=self._request_timeout_seconds):
                return True
        except urllib.error.HTTPError:
            return True
        except (OSError, urllib.error.URLError):
            return False

    def _registry_endpoint_is_compatible(self) -> bool:
        try:
            with urllib.request.urlopen(self._endpoint(), timeout=self._request_timeout_seconds) as response:
                if response.status != 200:
                    return False
                payload = json.load(response)
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            return False
        if not isinstance(payload, dict):
            return False
        if payload.get("schema_version") != DISCOVERY_SCHEMA_VERSION:
            return False
        ttl = payload.get("ttl_seconds")
        servers = payload.get("servers")
        if not isinstance(ttl, (int, float)) or isinstance(ttl, bool) or ttl <= 0 or not isinstance(servers, list):
            return False
        if len(servers) > MAX_REGISTRY_ENTRIES:
            return False
        try:
            for entry in servers:
                if not isinstance(entry, dict):
                    return False
                expires_at = entry.get("expires_at")
                if not isinstance(expires_at, (int, float)) or isinstance(expires_at, bool) or expires_at <= 0:
                    return False
                _validated_registration(entry)
        except ValueError:
            return False
        return True

    def _current_transport(self) -> RegistrationTransport:
        if self.is_owner and self._state is not None:
            return _StateTransport(self._state)
        if self._transport is not None:
            return self._transport
        return _HttpTransport(self._endpoint(), timeout_seconds=self._request_timeout_seconds)

    def _register(self) -> None:
        try:
            self._current_transport().register({"instance_id": self.instance_id, "server_info": self.server_info})
        except urllib.error.HTTPError as error:
            raise DiscoveryRegistryError(f"discovery registry rejected registration: HTTP {error.code}") from error
        self._registered = True

    def start(self) -> None:
        if self.heartbeat_thread.is_alive():
            return
        if self._embedded_registry_state is not None:
            self._state = self._embedded_registry_state
            self.is_owner = True
        elif self._transport is None:
            self._register_with_startup_retry()
        else:
            try:
                self._register()
            except (OSError, urllib.error.URLError):
                pass
        if self._embedded_registry_state is not None:
            self._register()
        self.heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self.heartbeat_thread.start()
        self.ownership_thread = threading.Thread(target=self._ownership_loop, daemon=True)
        self.ownership_thread.start()

    def _register_with_startup_retry(self) -> None:
        deadline = time.monotonic() + self._startup_timeout_seconds
        last_error: OSError | None = None
        while True:
            self._become_owner()
            try:
                self._register()
                return
            except (OSError, urllib.error.URLError) as error:
                last_error = error
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DiscoveryRegistryError(
                    "discovery registry did not become available before startup timeout"
                ) from last_error
            self._stop_event.wait(min(self._startup_retry_seconds, remaining))

    def _heartbeat_loop(self) -> None:
        while not self._wait(self.heartbeat_seconds):
            try:
                self._register()
            except (OSError, urllib.error.URLError):
                continue

    def _ownership_loop(self) -> None:
        if self._transport is not None:
            return
        while not self._stop_event.wait(self.heartbeat_seconds):
            if self.is_owner:
                continue
            try:
                with urllib.request.urlopen(self._endpoint(), timeout=1):
                    continue
            except (OSError, urllib.error.URLError):
                if self._become_owner():
                    self._register()

    def stop(self) -> None:
        self._stop_event.set()
        if self.heartbeat_thread.is_alive():
            self.heartbeat_thread.join(timeout=3)
        if self.ownership_thread.is_alive():
            self.ownership_thread.join(timeout=2)
        if self._registered:
            try:
                self._current_transport().unregister(self.instance_id)
            except (OSError, urllib.error.URLError):
                pass
            else:
                self._registered = False
        if self._registry_server is not None:
            self._registry_server.shutdown()
            self._registry_server.server_close()
        if self._registry_thread is not None and self._registry_thread.is_alive():
            self._registry_thread.join(timeout=2)
        self.is_owner = False


class _StateTransport:
    def __init__(self, state: RegistryState) -> None:
        self.state = state

    def register(self, payload: dict[str, object]) -> None:
        self.state.register(payload)

    def unregister(self, instance_id: str) -> None:
        self.state.unregister(instance_id)


def create_discovery_lifecycle(
    server_info: dict[str, object], *, embedded_registry_state: RegistryState | None = None
) -> DiscoveryLifecycle:
    return DiscoveryLifecycle(server_info=server_info, embedded_registry_state=embedded_registry_state)
