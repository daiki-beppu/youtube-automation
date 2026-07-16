from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from youtube_automation.scripts.collection_serve_discovery import (
    DISCOVERY_HEARTBEAT_SECONDS,
    DISCOVERY_PATH,
    DISCOVERY_TTL_SECONDS,
    MAX_INSTANCE_ID_LENGTH,
    MAX_REGISTRATION_BODY_BYTES,
    MAX_REGISTRY_ENTRIES,
    DiscoveryLifecycle,
    RegistryState,
    create_registry_server,
)
from youtube_automation.utils.exceptions import DiscoveryRegistryError


class FakeClock:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def server_info(base_url: str, label: str) -> dict[str, object]:
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.hostname is None or parsed.port is None:
        raise AssertionError(f"test URL must include hostname and port: {base_url}")
    return {
        "channel_name": label,
        "channel_short": label.lower(),
        "hostname": parsed.hostname,
        "port": parsed.port,
        "base_url": base_url,
        "label": label,
    }


def registration(base_url: str, instance_id: str) -> dict[str, object]:
    return {"instance_id": instance_id, "server_info": server_info(base_url, instance_id)}


@pytest.fixture
def registry_http():
    servers = []

    def start(state: RegistryState):
        server = create_registry_server("127.0.0.1", 0, state)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append((server, thread))
        return f"http://127.0.0.1:{server.server_address[1]}"

    yield start

    for server, thread in servers:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request_json(url: str, *, method: str = "GET", body: bytes | None = None) -> tuple[int, dict[str, object], str]:
    request = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=2) as response:
        return response.status, json.loads(response.read()), response.headers.get_content_type()


def post_registration(base: str, payload: dict[str, object]) -> int:
    status, _, _ = request_json(
        f"{base}{DISCOVERY_PATH}",
        method="POST",
        body=json.dumps(payload, separators=(",", ":")).encode(),
    )
    return status


def test_registry_returns_all_servers_in_deterministic_base_url_order(registry_http):
    clock = FakeClock(100.0)
    state = RegistryState(ttl_seconds=30, clock=clock)
    state.register(registration("http://alpha.localhost:9001", "alpha"))
    state.register(registration("http://127.0.0.1:49152", "numeric"))
    base = registry_http(state)

    first = request_json(f"{base}{DISCOVERY_PATH}")
    second = request_json(f"{base}{DISCOVERY_PATH}")

    expected = {
        "schema_version": 1,
        "ttl_seconds": 30,
        "servers": [
            {**registration("http://127.0.0.1:49152", "numeric"), "expires_at": 130.0},
            {**registration("http://alpha.localhost:9001", "alpha"), "expires_at": 130.0},
        ],
    }
    assert first == (200, expected, "application/json")
    assert second[1] == expected
    assert isinstance(first[1]["schema_version"], int)
    assert first[1]["ttl_seconds"] > 0
    assert isinstance(first[1]["servers"], list)


def test_registry_matches_the_cross_language_golden_fixture(registry_http):
    fixture_path = Path(__file__).parent / "fixtures" / "collection_serve_discovery_v1.json"
    expected = json.loads(fixture_path.read_text(encoding="utf-8"))
    state = RegistryState(ttl_seconds=30, clock=FakeClock(100.0))
    state.register(
        {
            "instance_id": "fixture-instance",
            "server_info": expected["servers"][0]["server_info"],
        }
    )
    base = registry_http(state)

    _, actual, _ = request_json(f"{base}{DISCOVERY_PATH}")

    assert actual == expected


def test_heartbeat_updates_expiry_without_duplicate_and_ttl_boundary_is_exclusive():
    clock = FakeClock(100.0)
    state = RegistryState(ttl_seconds=30, clock=clock)
    payload = registration("http://alpha.localhost:9001", "instance-a")
    state.register(payload)
    clock.value = 120.0
    state.register(payload)

    clock.value = 149.999
    assert len(state.snapshot()["servers"]) == 1
    assert state.snapshot()["servers"][0]["expires_at"] == 150.0
    clock.value = 150.0
    assert state.snapshot()["servers"] == []
    clock.value = 150.001
    assert state.snapshot()["servers"] == []


def test_ttl_expiry_uses_monotonic_time_when_wall_clock_moves_backwards():
    wall_clock = FakeClock(100.0)
    monotonic_clock = FakeClock(500.0)
    state = RegistryState(ttl_seconds=30, clock=wall_clock, monotonic_clock=monotonic_clock)
    state.register(registration("http://alpha.localhost:9001", "instance-a"))

    wall_clock.value = 50.0
    monotonic_clock.value = 530.0

    assert state.snapshot()["servers"] == []


def test_unregister_is_immediate_and_unknown_instance_is_idempotent():
    state = RegistryState(ttl_seconds=30, clock=FakeClock(100.0))
    state.register(registration("http://alpha.localhost:9001", "instance-a"))

    state.unregister("missing")
    assert len(state.snapshot()["servers"]) == 1
    state.unregister("instance-a")
    assert state.snapshot()["servers"] == []


@pytest.mark.parametrize(
    "url",
    ["http://localhost:7873", "http://127.0.0.1:49152", "http://channel-a.localhost:9001"],
)
def test_registry_accepts_only_supported_loopback_http_urls(registry_http, url):
    state = RegistryState(ttl_seconds=30, clock=FakeClock(100.0))
    base = registry_http(state)

    assert post_registration(base, registration(url, "accepted")) in {200, 204}
    assert len(state.snapshot()["servers"]) == 1


@pytest.mark.parametrize(
    "payload",
    [
        registration("http://example.com:9001", "external"),
        registration("https://localhost:9001", "https"),
        registration("http://user@localhost:9001", "userinfo"),
        registration("http://localhost:9001?query=1", "query"),
        registration("http://localhost:9001/#fragment", "fragment"),
        {"instance_id": "missing-info"},
        {"instance_id": 1, "server_info": {}},
        {
            **registration("http://localhost:9001", "missing-base-url"),
            "server_info": {"hostname": "localhost", "port": 9001},
        },
        {
            **registration("http://localhost:9001", "wrong-port-type"),
            "server_info": {
                **server_info("http://localhost:9001", "wrong-port-type"),
                "port": "9001",
            },
        },
    ],
)
def test_registry_rejects_invalid_registration_without_mutating_state(registry_http, payload):
    state = RegistryState(ttl_seconds=30, clock=FakeClock(100.0))
    base = registry_http(state)

    with pytest.raises(urllib.error.HTTPError) as error:
        post_registration(base, payload)

    assert 400 <= error.value.code < 500
    assert state.snapshot()["servers"] == []
    assert request_json(f"{base}{DISCOVERY_PATH}")[0] == 200


@pytest.mark.parametrize("body", [b"", b"{broken"])
def test_registry_rejects_empty_or_malformed_json_and_remains_available(registry_http, body):
    state = RegistryState(ttl_seconds=30, clock=FakeClock(100.0))
    base = registry_http(state)

    with pytest.raises(urllib.error.HTTPError) as error:
        request_json(f"{base}{DISCOVERY_PATH}", method="POST", body=body)

    assert 400 <= error.value.code < 500
    assert request_json(f"{base}{DISCOVERY_PATH}")[0] == 200


def test_registry_enforces_registration_body_size_boundary(registry_http):
    state = RegistryState(ttl_seconds=30, clock=FakeClock(100.0))
    base = registry_http(state)
    payload = registration("http://localhost:9001", "body-boundary")
    encoded = json.dumps(payload).encode()
    payload["server_info"]["label"] = str(payload["server_info"]["label"]) + "x" * (
        MAX_REGISTRATION_BODY_BYTES - len(encoded)
    )
    at_limit = json.dumps(payload).encode()
    assert len(at_limit) == MAX_REGISTRATION_BODY_BYTES

    assert request_json(f"{base}{DISCOVERY_PATH}", method="POST", body=at_limit)[0] in {200, 204}
    with pytest.raises(urllib.error.HTTPError) as error:
        request_json(f"{base}{DISCOVERY_PATH}", method="POST", body=at_limit + b" ")
    assert error.value.code == 413


def test_registry_delete_enforces_body_and_instance_id_boundaries(registry_http):
    state = RegistryState(ttl_seconds=30, clock=FakeClock(100.0))
    state.register(registration("http://localhost:9001", "registered"))
    base = registry_http(state)

    invalid_bodies = [
        json.dumps({"instance_id": ""}).encode(),
        json.dumps({"instance_id": "x" * (MAX_INSTANCE_ID_LENGTH + 1)}).encode(),
    ]
    for body in invalid_bodies:
        with pytest.raises(urllib.error.HTTPError) as error:
            request_json(f"{base}{DISCOVERY_PATH}", method="DELETE", body=body)
        assert error.value.code == 400

    oversized = b" " * (MAX_REGISTRATION_BODY_BYTES + 1)
    with pytest.raises(urllib.error.HTTPError) as error:
        request_json(f"{base}{DISCOVERY_PATH}", method="DELETE", body=oversized)
    assert error.value.code == 413
    assert [entry["instance_id"] for entry in state.snapshot()["servers"]] == ["registered"]


def test_registry_requires_json_content_type_without_mutating_state(registry_http):
    state = RegistryState(ttl_seconds=30, clock=FakeClock(100.0))
    base = registry_http(state)
    body = json.dumps(registration("http://localhost:9001", "wrong-content-type")).encode()
    request = urllib.request.Request(f"{base}{DISCOVERY_PATH}", data=body, method="POST")

    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(request, timeout=2)

    assert error.value.code == 415
    assert state.snapshot()["servers"] == []


def test_registry_rejects_browser_origin_without_mutating_state(registry_http):
    state = RegistryState(ttl_seconds=30, clock=FakeClock(100.0))
    base = registry_http(state)
    body = json.dumps(registration("http://localhost:9001", "browser-origin")).encode()
    request = urllib.request.Request(f"{base}{DISCOVERY_PATH}", data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("Origin", "https://example.com")

    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(request, timeout=2)

    assert error.value.code == 403
    assert state.snapshot()["servers"] == []


def test_registry_enforces_instance_id_length_without_mutating_existing_state(registry_http):
    state = RegistryState(ttl_seconds=30, clock=FakeClock(100.0))
    base = registry_http(state)
    accepted_id = "a" * MAX_INSTANCE_ID_LENGTH
    rejected_id = "b" * (MAX_INSTANCE_ID_LENGTH + 1)

    assert post_registration(base, registration("http://localhost:9001", accepted_id)) == 200
    with pytest.raises(urllib.error.HTTPError) as error:
        post_registration(base, registration("http://localhost:9002", rejected_id))

    assert error.value.code == 400
    assert [entry["instance_id"] for entry in state.snapshot()["servers"]] == [accepted_id]


def test_registry_enforces_entry_limit_but_allows_heartbeat_update(registry_http):
    state = RegistryState(ttl_seconds=30, clock=FakeClock(100.0))
    for index in range(MAX_REGISTRY_ENTRIES):
        state.register(registration(f"http://localhost:{10000 + index}", f"instance-{index}"))
    base = registry_http(state)

    assert post_registration(base, registration("http://localhost:10000", "instance-0")) == 200
    with pytest.raises(urllib.error.HTTPError) as error:
        post_registration(base, registration("http://localhost:20000", "one-too-many"))

    assert error.value.code == 429
    snapshot = state.snapshot()["servers"]
    assert len(snapshot) == MAX_REGISTRY_ENTRIES
    assert all(entry["instance_id"] != "one-too-many" for entry in snapshot)


@pytest.mark.parametrize("method", ["CONNECT", "HEAD", "OPTIONS", "PATCH", "PUT", "TRACE", "BREW"])
def test_registry_rejects_unknown_paths_and_unsupported_methods(registry_http, method):
    state = RegistryState(ttl_seconds=30, clock=FakeClock(100.0))
    base = registry_http(state)

    with pytest.raises(urllib.error.HTTPError) as unknown:
        request_json(f"{base}/unknown")
    with pytest.raises(urllib.error.HTTPError) as method_error:
        request_json(f"{base}{DISCOVERY_PATH}", method=method, body=b"{}")

    assert unknown.value.code == 404
    assert method_error.value.code == 405


class ControlledWait:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.releases = 0
        self.calls = 0
        self.condition = threading.Condition()

    def release(self) -> None:
        with self.condition:
            self.releases += 1
            self.condition.notify_all()

    def __call__(self, seconds: float) -> bool:
        with self.condition:
            self.condition.wait_for(lambda: self.releases > self.calls, timeout=2)
            if self.releases <= self.calls:
                return True
            self.calls += 1
            self.clock.value += seconds
            return False


class RecordingTransport:
    def __init__(self, state: RegistryState, *, fail_unregister: bool = False) -> None:
        self.state = state
        self.fail_unregister = fail_unregister
        self.registered: list[dict[str, object]] = []

    def register(self, payload: dict[str, object]) -> None:
        self.registered.append(payload)
        self.state.register(payload)

    def unregister(self, instance_id: str) -> None:
        if self.fail_unregister:
            raise OSError("registry unavailable")
        self.state.unregister(instance_id)


class InitiallyUnavailableTransport(RecordingTransport):
    def __init__(self, state: RegistryState) -> None:
        super().__init__(state)
        self.attempts = 0

    def register(self, payload: dict[str, object]) -> None:
        self.attempts += 1
        if self.attempts == 1:
            raise urllib.error.URLError("registry is starting")
        super().register(payload)


class HeartbeatRejectedTransport(RecordingTransport):
    def register(self, payload: dict[str, object]) -> None:
        if self.registered:
            raise urllib.error.HTTPError(
                url="http://127.0.0.1:7872/.well-known/yt-collection-serve",
                code=403,
                msg="Forbidden",
                hdrs=None,
                fp=None,
            )
        super().register(payload)


def wait_until(assertion, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            assertion()
            return
        except AssertionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.001)


def assert_registration_count(transport: RecordingTransport, expected: int) -> None:
    assert len(transport.registered) >= expected


def test_lifecycle_heartbeats_beyond_ttl_and_unregisters_on_stop():
    assert 0 < DISCOVERY_HEARTBEAT_SECONDS < DISCOVERY_TTL_SECONDS
    clock = FakeClock(100.0)
    state = RegistryState(ttl_seconds=DISCOVERY_TTL_SECONDS, clock=clock)
    wait = ControlledWait(clock)
    transport = RecordingTransport(state)
    lifecycle = DiscoveryLifecycle(
        server_info=server_info("http://alpha.localhost:9001", "Alpha"),
        instance_id="instance-a",
        heartbeat_seconds=DISCOVERY_HEARTBEAT_SECONDS,
        wait=wait,
        transport=transport,
    )

    try:
        lifecycle.start()
        for expected in range(2, 5):
            wait.release()
            wait_until(lambda expected=expected: assert_registration_count(transport, expected))
        assert clock.value - 100.0 > DISCOVERY_TTL_SECONDS
        assert len(state.snapshot()["servers"]) == 1

        lifecycle.stop()
        registration_count = len(transport.registered)
        wait.release()
        assert len(transport.registered) == registration_count
        assert state.snapshot()["servers"] == []
        assert not lifecycle.heartbeat_thread.is_alive()
    finally:
        lifecycle.stop()


def test_lifecycle_recovers_when_initial_follower_registration_races_registry_startup():
    clock = FakeClock(100.0)
    state = RegistryState(ttl_seconds=30, clock=clock)
    wait = ControlledWait(clock)
    transport = InitiallyUnavailableTransport(state)
    lifecycle = DiscoveryLifecycle(
        server_info=server_info("http://alpha.localhost:9001", "Alpha"),
        instance_id="instance-a",
        heartbeat_seconds=10,
        wait=wait,
        transport=transport,
    )

    try:
        lifecycle.start()
        wait.release()
        wait_until(lambda: assert_registration_count(transport, 1))
        assert len(state.snapshot()["servers"]) == 1
    finally:
        lifecycle.stop()


def test_lifecycle_heartbeat_reports_permanent_http_rejection(monkeypatch):
    clock = FakeClock(100.0)
    state = RegistryState(ttl_seconds=30, clock=clock)
    wait = ControlledWait(clock)
    transport = HeartbeatRejectedTransport(state)
    lifecycle = DiscoveryLifecycle(
        server_info=server_info("http://alpha.localhost:9001", "Alpha"),
        instance_id="instance-a",
        heartbeat_seconds=10,
        wait=wait,
        transport=transport,
    )
    thread_error: list[BaseException] = []
    error_reported = threading.Event()

    def record_thread_error(args: threading.ExceptHookArgs) -> None:
        thread_error.append(args.exc_value)
        error_reported.set()

    monkeypatch.setattr(threading, "excepthook", record_thread_error)

    try:
        lifecycle.start()
        wait.release()
        assert error_reported.wait(timeout=2)
        assert len(thread_error) == 1
        assert isinstance(thread_error[0], DiscoveryRegistryError)
        assert str(thread_error[0]) == "discovery registry rejected registration: HTTP 403"
    finally:
        lifecycle.stop()


def test_lifecycle_stops_thread_when_unregister_fails_and_entry_expires_at_ttl():
    clock = FakeClock(100.0)
    state = RegistryState(ttl_seconds=30, clock=clock)
    transport = RecordingTransport(state, fail_unregister=True)
    wait = ControlledWait(clock)
    lifecycle = DiscoveryLifecycle(
        server_info=server_info("http://alpha.localhost:9001", "Alpha"),
        instance_id="instance-a",
        heartbeat_seconds=10,
        wait=wait,
        transport=transport,
    )
    try:
        lifecycle.start()
        lifecycle.stop()

        assert not lifecycle.heartbeat_thread.is_alive()
        clock.value = 130.0
        assert state.snapshot()["servers"] == []
    finally:
        lifecycle.stop()


def test_real_socket_owner_follower_takeover_keeps_public_endpoint_available():
    lifecycle_a = DiscoveryLifecycle.for_loopback_test(
        server_info("http://alpha.localhost:9001", "Alpha"), discovery_port=0
    )
    lifecycle_b = None
    try:
        lifecycle_a.start()
        port = lifecycle_a.registry_port
        lifecycle_b = DiscoveryLifecycle.for_loopback_test(
            server_info("http://beta.localhost:49152", "Beta"), discovery_port=port
        )
        lifecycle_b.start()
        endpoint = f"http://127.0.0.1:{port}{DISCOVERY_PATH}"
        expected = {"http://alpha.localhost:9001", "http://beta.localhost:49152"}
        wait_until(lambda: assert_urls(endpoint, expected))
        assert sum(item.is_owner for item in (lifecycle_a, lifecycle_b)) == 1
        initial_beta_expiry = expiry_for(endpoint, "http://beta.localhost:49152")
        wait_until(lambda: assert_expiry_advanced(endpoint, "http://beta.localhost:49152", initial_beta_expiry))

        lifecycle_a.stop()
        assert not lifecycle_a.heartbeat_thread.is_alive()
        assert not lifecycle_a.ownership_thread.is_alive()
        wait_until(lambda: assert_owner(lifecycle_b))
        assert_urls(endpoint, {"http://beta.localhost:49152"})
    finally:
        lifecycle_a.stop()
        if lifecycle_b is not None:
            lifecycle_b.stop()

    assert lifecycle_b is not None
    assert not lifecycle_b.heartbeat_thread.is_alive()
    assert not lifecycle_b.ownership_thread.is_alive()


def test_lifecycle_start_fails_when_fixed_port_http_responder_returns_404():
    methods: list[str] = []

    class NotARegistryHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            methods.append("GET")
            self.send_error(404)

        def do_DELETE(self) -> None:
            methods.append("DELETE")
            self.send_response(204)
            self.end_headers()

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), NotARegistryHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    lifecycle = DiscoveryLifecycle.for_loopback_test(
        server_info("http://alpha.localhost:9001", "Alpha"),
        discovery_port=int(server.server_address[1]),
    )

    try:
        with pytest.raises(DiscoveryRegistryError, match="incompatible schema"):
            lifecycle.start()

        lifecycle.stop()
        assert not lifecycle.heartbeat_thread.is_alive()
        assert not lifecycle.ownership_thread.is_alive()
        assert "DELETE" not in methods
    finally:
        lifecycle.stop()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_lifecycle_rejects_competing_registry_response_over_entry_limit():
    entries = [
        {
            **registration(f"http://localhost:{10000 + index}", f"instance-{index}"),
            "expires_at": 130,
        }
        for index in range(MAX_REGISTRY_ENTRIES + 1)
    ]

    class OversizedRegistryHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = json.dumps(
                {"schema_version": 1, "ttl_seconds": 30, "servers": entries},
                separators=(",", ":"),
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), OversizedRegistryHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    lifecycle = DiscoveryLifecycle.for_loopback_test(
        server_info("http://alpha.localhost:9001", "Alpha"),
        discovery_port=int(server.server_address[1]),
    )

    try:
        assert lifecycle._registry_endpoint_is_compatible() is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_lifecycle_start_fails_without_unregistering_when_registry_rejects_post():
    methods: list[str] = []

    class RejectingRegistryHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            methods.append("GET")
            body = json.dumps(
                {"schema_version": 1, "ttl_seconds": 30, "servers": []},
                separators=(",", ":"),
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            methods.append("POST")
            self.send_error(403)

        def do_DELETE(self) -> None:
            methods.append("DELETE")
            self.send_response(204)
            self.end_headers()

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), RejectingRegistryHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    lifecycle = DiscoveryLifecycle.for_loopback_test(
        server_info("http://alpha.localhost:9001", "Alpha"),
        discovery_port=int(server.server_address[1]),
    )

    try:
        with pytest.raises(DiscoveryRegistryError, match="rejected registration: HTTP 403"):
            lifecycle.start()

        lifecycle.stop()
        assert methods.count("POST") == 1
        assert "DELETE" not in methods
        assert not lifecycle.heartbeat_thread.is_alive()
        assert not lifecycle.ownership_thread.is_alive()
    finally:
        lifecycle.stop()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_lifecycle_start_fails_when_fixed_port_never_serves_compatible_registry(monkeypatch):
    lifecycle = DiscoveryLifecycle(
        server_info=server_info("http://alpha.localhost:9001", "Alpha"),
        startup_timeout_seconds=0.01,
        startup_retry_seconds=0.001,
    )
    ownership_attempts = 0

    def lose_bind_race() -> bool:
        nonlocal ownership_attempts
        ownership_attempts += 1
        return False

    monkeypatch.setattr(lifecycle, "_become_owner", lose_bind_race)
    monkeypatch.setattr(
        lifecycle,
        "_current_transport",
        lambda: InitiallyUnavailableTransport(RegistryState()),
    )

    with pytest.raises(DiscoveryRegistryError, match="startup timeout"):
        lifecycle.start()

    assert ownership_attempts > 1
    assert not lifecycle.heartbeat_thread.is_alive()
    assert not lifecycle.ownership_thread.is_alive()


def test_embedded_lifecycle_registers_and_removes_its_server_from_collection_state():
    state = RegistryState(ttl_seconds=30, clock=FakeClock(100.0))
    lifecycle = DiscoveryLifecycle(
        server_info=server_info("http://localhost:7872", "Collection server"),
        instance_id="collection-server",
        embedded_registry_state=state,
    )

    lifecycle.start()

    assert lifecycle.is_owner is True
    assert [entry["instance_id"] for entry in state.snapshot()["servers"]] == ["collection-server"]

    lifecycle.stop()

    assert state.snapshot()["servers"] == []


def assert_urls(endpoint: str, expected: set[str]) -> None:
    _, payload, _ = request_json(endpoint)
    assert {entry["server_info"]["base_url"] for entry in payload["servers"]} == expected


def assert_owner(lifecycle: DiscoveryLifecycle) -> None:
    assert lifecycle.is_owner


def expiry_for(endpoint: str, base_url: str) -> float:
    _, payload, _ = request_json(endpoint)
    return next(entry["expires_at"] for entry in payload["servers"] if entry["server_info"]["base_url"] == base_url)


def assert_expiry_advanced(endpoint: str, base_url: str, previous: float) -> None:
    assert expiry_for(endpoint, base_url) > previous
