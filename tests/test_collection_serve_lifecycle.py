"""yt-collection-serve のプロセス lifecycle 契約テスト（#1725）。"""

from __future__ import annotations

import argparse
import contextlib
import http.client
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from youtube_automation.scripts import collection_serve


class _NoopDiscoveryLifecycle:
    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


def _make_collection(root: Path) -> None:
    (root / "example-collection").mkdir(parents=True)


def _unused_local_port() -> int:
    with socket.socket() as listener:
        listener.bind(("localhost", 0))
        return listener.getsockname()[1]


def _read_record(path: Path) -> collection_serve._LifecycleRecord:
    record = collection_serve._read_pid_file(path)
    assert record is not None
    return record


def test_main_writes_pid_file_while_serving_and_removes_it_on_shutdown(monkeypatch, tmp_path):
    planning = tmp_path / "collections" / "planning"
    _make_collection(planning)
    pid_path = planning / ".collection-serve-7873.pid"

    class FakeServer:
        server_address = ("localhost", 7873)

        def serve_forever(self) -> None:
            assert _read_record(pid_path).pid == os.getpid()
            raise KeyboardInterrupt

        def server_close(self) -> None:
            pass

    monkeypatch.setattr(collection_serve, "create_server", lambda *args, **kwargs: FakeServer())
    monkeypatch.setattr(
        collection_serve,
        "create_discovery_lifecycle",
        lambda *args, **kwargs: _NoopDiscoveryLifecycle(),
    )
    monkeypatch.setattr(sys, "argv", ["yt-collection-serve", str(planning)])

    collection_serve.main()

    assert not pid_path.exists()


def test_main_handles_explicit_stop_immediately_after_pid_publication(monkeypatch, tmp_path):
    planning = tmp_path / "collections" / "planning"
    _make_collection(planning)
    pid_path = planning / ".collection-serve-7873.pid"
    stop_path = planning / ".collection-serve-7873.stop"
    original_write_pid_file = collection_serve._write_pid_file
    previous_sigterm_handler = signal.getsignal(signal.SIGTERM)

    class FakeServer:
        server_address = ("localhost", 7873)

        def serve_forever(self) -> None:
            pytest.fail("the stop request must be handled before serving")

        def server_close(self) -> None:
            pass

    def publish_then_stop(path: Path, record: collection_serve._LifecycleRecord) -> None:
        original_write_pid_file(path, record)
        original_write_pid_file(stop_path, record)
        os.kill(os.getpid(), signal.SIGTERM)

    monkeypatch.setattr(collection_serve, "create_server", lambda *args, **kwargs: FakeServer())
    monkeypatch.setattr(collection_serve, "_write_pid_file", publish_then_stop)
    monkeypatch.setattr(sys, "argv", ["yt-collection-serve", str(planning)])

    with pytest.raises(SystemExit) as stopped:
        collection_serve.main()

    assert stopped.value.code == 0
    assert signal.getsignal(signal.SIGTERM) == previous_sigterm_handler
    assert not pid_path.exists()
    assert not stop_path.exists()


def test_pid_record_is_published_atomically_before_parallel_claim_can_observe_it(monkeypatch, tmp_path):
    pid_path = tmp_path / ".collection-serve-7873.pid"
    lock_path = collection_serve._startup_lock_path(tmp_path, 7873)
    record = collection_serve._LifecycleRecord(os.getpid(), "atomic-token", "configuration")
    writer_started = threading.Event()
    allow_writer_to_finish = threading.Event()
    contender_finished = threading.Event()
    observed: list[collection_serve._LifecycleRecord | None] = []
    original_dump = json.dump

    def blocked_dump(*args, **kwargs):
        writer_started.set()
        assert allow_writer_to_finish.wait(timeout=5)
        return original_dump(*args, **kwargs)

    def writer() -> None:
        with collection_serve._startup_lock(lock_path):
            collection_serve._write_pid_file(pid_path, record)

    def contender() -> None:
        with collection_serve._startup_lock(lock_path):
            observed.append(collection_serve._read_pid_file(pid_path))
        contender_finished.set()

    monkeypatch.setattr(collection_serve.json, "dump", blocked_dump)
    writer_thread = threading.Thread(target=writer)
    contender_thread = threading.Thread(target=contender)
    writer_thread.start()
    assert writer_started.wait(timeout=5)
    contender_thread.start()

    assert not pid_path.exists()
    assert not contender_finished.wait(timeout=0.1)

    allow_writer_to_finish.set()
    writer_thread.join(timeout=5)
    contender_thread.join(timeout=5)

    assert not writer_thread.is_alive()
    assert not contender_thread.is_alive()
    assert observed == [record]


def test_process_exit_watcher_uses_pidfd_and_closes_descriptor(monkeypatch):
    closed: list[int] = []
    monkeypatch.setattr(collection_serve.os, "pidfd_open", lambda pid: 123, raising=False)
    monkeypatch.setattr(collection_serve.select, "select", lambda read, write, errors, timeout: ([123], [], []))
    monkeypatch.setattr(collection_serve.os, "close", closed.append)

    with collection_serve._process_exit_watcher(9876) as wait_for_exit:
        assert wait_for_exit is not None
        assert wait_for_exit(5.0) is True

    assert closed == [123]


def test_process_exit_watcher_uses_kqueue_and_closes_queue_when_pidfd_is_unavailable(monkeypatch):
    controls: list[tuple[object, int, float]] = []
    closed: list[bool] = []

    class FakeQueue:
        def control(self, changes, max_events: int, timeout: float):
            controls.append((changes, max_events, timeout))
            return [] if changes is not None else [object()]

        def close(self) -> None:
            closed.append(True)

    def unavailable_pidfd(pid: int) -> int:
        raise OSError("unsupported")

    monkeypatch.setattr(collection_serve.os, "pidfd_open", unavailable_pidfd, raising=False)
    monkeypatch.setattr(collection_serve.select, "kqueue", FakeQueue, raising=False)
    monkeypatch.setattr(collection_serve.select, "kevent", lambda *args, **kwargs: (args, kwargs), raising=False)
    monkeypatch.setattr(collection_serve.select, "KQ_NOTE_EXIT", 1, raising=False)
    monkeypatch.setattr(collection_serve.select, "KQ_FILTER_PROC", 2, raising=False)
    monkeypatch.setattr(collection_serve.select, "KQ_EV_ADD", 4, raising=False)
    monkeypatch.setattr(collection_serve.select, "KQ_EV_ENABLE", 8, raising=False)

    with collection_serve._process_exit_watcher(9876) as wait_for_exit:
        assert wait_for_exit is not None
        assert wait_for_exit(5.0) is True

    assert len(controls) == 2
    assert controls[1] == (None, 1, 5.0)
    assert closed == [True]


def test_process_exit_watcher_falls_back_when_platform_has_no_process_handle(monkeypatch):
    monkeypatch.delattr(collection_serve.os, "pidfd_open", raising=False)
    monkeypatch.delattr(collection_serve.select, "kqueue", raising=False)
    monkeypatch.delattr(collection_serve.select, "KQ_NOTE_EXIT", raising=False)

    with collection_serve._process_exit_watcher(9876) as wait_for_exit:
        assert wait_for_exit is None


def test_main_reuses_live_server_without_creating_another_process(monkeypatch, capsys, tmp_path):
    planning = tmp_path / "collections" / "planning"
    _make_collection(planning)
    configuration = collection_serve._configuration_fingerprint(
        path=planning,
        mode="dir",
        allow_origin=None,
        capture_root=None,
        distrokid_source=None,
        idle_timeout_seconds=collection_serve.DEFAULT_IDLE_TIMEOUT_SECONDS,
    )
    record = collection_serve._LifecycleRecord(os.getpid(), "reuse-token", configuration)
    server = collection_serve.create_server(
        0,
        None,
        prompts_path=None,
        collection_dir=None,
        distrokid=None,
        collections_root=planning,
        lifecycle_record=record,
    )
    port = server.server_address[1]
    pid_path = planning / f".collection-serve-{port}.pid"
    collection_serve._write_pid_file(pid_path, record)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        monkeypatch.setattr(sys, "argv", ["yt-collection-serve", str(planning), "--port", str(port)])

        collection_serve.main()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

    assert _read_record(pid_path) == record
    assert f"Reusing collection server on port {port} (PID {os.getpid()})." in capsys.readouterr().out


def test_parallel_console_starts_publish_one_owner_and_reuse_it(tmp_path):
    channel_root = tmp_path / "channel"
    planning = channel_root / "collections" / "planning"
    _make_collection(planning)
    fixture_channel = Path("tests/fixtures/sample_channel")
    shutil.copytree(fixture_channel / "config", channel_root / "config")
    port = _unused_local_port()
    pid_path = planning / f".collection-serve-{port}.pid"
    console_script = Path(sys.executable).parent / "yt-collection-serve"
    environment = os.environ | {"CHANNEL_DIR": str(channel_root)}
    command = [str(console_script), str(planning), "--port", str(port)]
    processes = [
        subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment)
        for _ in range(2)
    ]
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if pid_path.exists() and sum(process.poll() is None for process in processes) == 1:
                break
            time.sleep(0.05)

        running = [process for process in processes if process.poll() is None]
        reused = [process for process in processes if process.poll() is not None]
        assert len(running) == 1
        assert len(reused) == 1
        record = _read_record(pid_path)
        assert record.pid == running[0].pid
        reused_stdout, reused_stderr = reused[0].communicate(timeout=5)
        assert reused[0].returncode == 0
        assert f"Reusing collection server on port {port} (PID {running[0].pid})." in reused_stdout
        assert reused_stderr == ""

        stopped = subprocess.run(
            [str(console_script), "--stop", "--port", str(port)],
            capture_output=True,
            text=True,
            env=environment,
            timeout=10,
        )
        running[0].communicate(timeout=10)
        assert stopped.returncode == 0
        assert not pid_path.exists()
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate()


@pytest.mark.parametrize(
    "requested_args",
    [
        ["--allow-origin", "chrome-extension://abcdefghijklmnopabcdefghijklmnop"],
        ["--distrokid-capture-root", "."],
        ["--idle-timeout", "30"],
    ],
    ids=["origin-lock", "capture-capability", "idle-timeout"],
)
def test_main_does_not_reuse_server_with_incompatible_configuration(monkeypatch, tmp_path, requested_args):
    planning = tmp_path / "collections" / "planning"
    _make_collection(planning)
    configuration = collection_serve._configuration_fingerprint(
        path=planning,
        mode="dir",
        allow_origin=None,
        capture_root=None,
        distrokid_source=None,
        idle_timeout_seconds=collection_serve.DEFAULT_IDLE_TIMEOUT_SECONDS,
    )
    record = collection_serve._LifecycleRecord(os.getpid(), "configuration-token", configuration)
    server = collection_serve.create_server(
        0,
        None,
        prompts_path=None,
        collection_dir=None,
        distrokid=None,
        collections_root=planning,
        lifecycle_record=record,
    )
    port = server.server_address[1]
    pid_path = planning / f".collection-serve-{port}.pid"
    collection_serve._write_pid_file(pid_path, record)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        monkeypatch.setattr(
            collection_serve,
            "create_server",
            lambda *args, **kwargs: pytest.fail("incompatible server must not be reported as reused"),
        )
        monkeypatch.setattr(
            sys,
            "argv",
            ["yt-collection-serve", str(planning), "--port", str(port), *requested_args],
        )

        with pytest.raises(collection_serve.ConfigError, match="different configuration; use another port"):
            collection_serve.main()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        pid_path.unlink(missing_ok=True)


def test_main_does_not_reuse_dir_server_for_single_file_mode(monkeypatch, tmp_path):
    planning = tmp_path / "collections" / "planning"
    collection = planning / "example-collection"
    prompts = collection / "20-documentation" / "suno-prompts.json"
    prompts.parent.mkdir(parents=True)
    prompts.write_text("[]", encoding="utf-8")
    configuration = collection_serve._configuration_fingerprint(
        path=planning,
        mode="dir",
        allow_origin=None,
        capture_root=None,
        distrokid_source=None,
        idle_timeout_seconds=collection_serve.DEFAULT_IDLE_TIMEOUT_SECONDS,
    )
    record = collection_serve._LifecycleRecord(os.getpid(), "mode-token", configuration)
    server = collection_serve.create_server(
        0,
        None,
        prompts_path=None,
        collection_dir=None,
        distrokid=None,
        collections_root=planning,
        lifecycle_record=record,
    )
    port = server.server_address[1]
    pid_path = planning / f".collection-serve-{port}.pid"
    collection_serve._write_pid_file(pid_path, record)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        monkeypatch.setattr(
            collection_serve,
            "create_server",
            lambda *args, **kwargs: pytest.fail("dir server must not be reused for single-file mode"),
        )
        monkeypatch.setattr(sys, "argv", ["yt-collection-serve", str(prompts), "--port", str(port)])

        with pytest.raises(collection_serve.ConfigError, match="different configuration; use another port"):
            collection_serve.main()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        pid_path.unlink(missing_ok=True)


def test_stop_cli_requests_owner_shutdown_from_channel_planning_and_removes_file(monkeypatch, capsys, tmp_path):
    channel_root = tmp_path / "channel"
    planning = channel_root / "collections" / "planning"
    planning.mkdir(parents=True)
    pid_path = planning / ".collection-serve-7874.pid"
    record = collection_serve._LifecycleRecord(9876, "stop-token", "configuration")
    collection_serve._write_pid_file(pid_path, record)
    running = True
    requested: list[tuple[int, collection_serve._LifecycleRecord, str]] = []

    def fake_request(port: int, candidate: collection_serve._LifecycleRecord, attempt_token: str) -> bool:
        nonlocal running
        requested.append((port, candidate, attempt_token))
        running = False
        return True

    monkeypatch.setattr(collection_serve, "channel_dir", lambda: channel_root)
    monkeypatch.setattr(collection_serve, "_pid_is_running", lambda pid: running)
    monkeypatch.setattr(collection_serve, "_process_exit_watcher", lambda pid: contextlib.nullcontext(None))
    monkeypatch.setattr(collection_serve, "_request_server_stop", fake_request)
    monkeypatch.setattr(collection_serve.os, "kill", lambda *args: pytest.fail("stop CLI must not signal a PID"))
    monkeypatch.setattr(sys, "argv", ["yt-collection-serve", "--stop", "--port", "7874"])

    collection_serve.main()

    assert requested[0][:2] == (7874, record)
    assert len(requested[0][2]) == 32
    assert not pid_path.exists()
    assert "Stopped collection server on port 7874 (PID 9876)." in capsys.readouterr().out


def test_distrokid_fallback_console_commands_stop_server_cleanly_without_traceback(tmp_path):
    channel_root = tmp_path / "channel"
    planning = channel_root / "collections" / "planning"
    _make_collection(planning)
    fixture_channel = Path("tests/fixtures/sample_channel")
    shutil.copytree(fixture_channel / "config", channel_root / "config")
    port = _unused_local_port()
    pid_path = planning / f".collection-serve-{port}.pid"
    console_script = Path(sys.executable).parent / "yt-collection-serve"
    environment_without_channel = os.environ.copy()
    environment_without_channel.pop("CHANNEL_DIR", None)
    environment = environment_without_channel | {"CHANNEL_DIR": str(channel_root)}
    server = subprocess.Popen(
        [str(console_script), str(planning), "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    try:
        deadline = time.monotonic() + 5
        while not pid_path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        record = _read_record(pid_path)
        assert collection_serve._server_process_id(port, record) == server.pid

        stopped = subprocess.run(
            [str(console_script), "--stop", "--port", str(port)],
            capture_output=True,
            text=True,
            env=environment,
            timeout=10,
        )
        stdout, stderr = server.communicate(timeout=10)
    finally:
        if server.poll() is None:
            server.kill()
            server.communicate()

    assert stopped.returncode == 0
    assert server.returncode == 0
    assert not pid_path.exists()
    assert "Stopped collection server" in stopped.stdout
    assert "Traceback" not in stdout
    assert stderr == ""


def test_public_stop_cli_waits_for_server_process_cleanup_before_returning(tmp_path):
    channel_root = tmp_path / "channel"
    planning = channel_root / "collections" / "planning"
    _make_collection(planning)
    fixture_channel = Path("tests/fixtures/sample_channel")
    shutil.copytree(fixture_channel / "config", channel_root / "config")
    port = _unused_local_port()
    pid_path = planning / f".collection-serve-{port}.pid"
    cleanup_started = tmp_path / "cleanup-started"
    allow_cleanup = tmp_path / "allow-cleanup"
    console_script = Path(sys.executable).parent / "yt-collection-serve"
    environment = os.environ | {"CHANNEL_DIR": str(channel_root)}
    server_program = f"""
import sys
import time
from pathlib import Path
from youtube_automation.scripts import collection_serve

cleanup_started = Path({str(cleanup_started)!r})
allow_cleanup = Path({str(allow_cleanup)!r})

class DelayedDiscoveryLifecycle:
    def start(self):
        pass

    def stop(self):
        cleanup_started.touch()
        while not allow_cleanup.exists():
            time.sleep(0.01)

collection_serve.create_discovery_lifecycle = lambda *args, **kwargs: DelayedDiscoveryLifecycle()
sys.argv = ["yt-collection-serve", {str(planning)!r}, "--port", {str(port)!r}]
collection_serve.main()
"""
    server = subprocess.Popen(
        [sys.executable, "-c", server_program],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    stopper: subprocess.Popen[str] | None = None
    try:
        deadline = time.monotonic() + 5
        while not pid_path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert _read_record(pid_path).pid == server.pid

        stopper = subprocess.Popen(
            [str(console_script), "--stop", "--port", str(port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
        )
        deadline = time.monotonic() + 5
        while not cleanup_started.exists() and time.monotonic() < deadline:
            time.sleep(0.05)

        assert cleanup_started.exists()
        assert server.poll() is None
        with pytest.raises(subprocess.TimeoutExpired):
            stopper.wait(timeout=0.5)

        allow_cleanup.touch()
        deadline = time.monotonic() + 5
        while server.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.returncode == 0
        stopped_stdout, stopped_stderr = stopper.communicate(timeout=5)
        assert stopper.returncode == 0, stopped_stderr
        assert "Stopped collection server" in stopped_stdout
        assert stopped_stderr == ""
    finally:
        allow_cleanup.touch()
        if stopper is not None and stopper.poll() is None:
            stopper.kill()
            stopper.communicate()
        if server.poll() is None:
            server.kill()
            server.communicate()


def test_console_script_unexpected_sigterm_remains_traceable_failure(tmp_path):
    channel_root = tmp_path / "channel"
    planning = channel_root / "collections" / "planning"
    _make_collection(planning)
    fixture_channel = Path("tests/fixtures/sample_channel")
    shutil.copytree(fixture_channel / "config", channel_root / "config")
    port = _unused_local_port()
    pid_path = planning / f".collection-serve-{port}.pid"
    console_script = Path(sys.executable).parent / "yt-collection-serve"
    environment = os.environ | {"CHANNEL_DIR": str(channel_root)}
    server = subprocess.Popen(
        [str(console_script), str(planning), "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    try:
        deadline = time.monotonic() + 5
        while not pid_path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        record = _read_record(pid_path)
        assert collection_serve._server_process_id(port, record) == server.pid

        os.kill(server.pid, signal.SIGTERM)
        _stdout, stderr = server.communicate(timeout=10)
    finally:
        if server.poll() is None:
            server.kill()
            server.communicate()

    assert server.returncode != 0
    assert not pid_path.exists()
    assert "Traceback" in stderr
    assert "SIGTERM (signal 15) requested server termination" in stderr


def test_stop_cli_preserves_live_pid_when_server_identity_cannot_be_verified(monkeypatch, tmp_path):
    channel_root = tmp_path / "channel"
    planning = channel_root / "collections" / "planning"
    planning.mkdir(parents=True)
    pid_path = planning / ".collection-serve-7874.pid"
    record = collection_serve._LifecycleRecord(9876, "stale-token", "configuration")
    collection_serve._write_pid_file(pid_path, record)

    monkeypatch.setattr(collection_serve, "channel_dir", lambda: channel_root)
    monkeypatch.setattr(collection_serve, "_pid_is_running", lambda pid: pid == 9876)
    monkeypatch.setattr(collection_serve, "_process_exit_watcher", lambda pid: contextlib.nullcontext(None))
    monkeypatch.setattr(collection_serve, "_request_server_stop", lambda port, candidate, attempt: False)
    monkeypatch.setattr(
        collection_serve.os,
        "kill",
        lambda pid, signum: pytest.fail("stale PID must not be signalled"),
    )
    monkeypatch.setattr(sys, "argv", ["yt-collection-serve", "--stop", "--port", "7874"])

    with pytest.raises(collection_serve.ConfigError, match="identity on port 7874 could not be verified"):
        collection_serve.main()

    assert _read_record(pid_path) == record


def test_console_stop_fails_and_preserves_pid_file_while_server_is_temporarily_unreachable(tmp_path):
    channel_root = tmp_path / "channel"
    planning = channel_root / "collections" / "planning"
    _make_collection(planning)
    fixture_channel = Path("tests/fixtures/sample_channel")
    shutil.copytree(fixture_channel / "config", channel_root / "config")
    port = _unused_local_port()
    pid_path = planning / f".collection-serve-{port}.pid"
    console_script = Path(sys.executable).parent / "yt-collection-serve"
    environment = os.environ | {"CHANNEL_DIR": str(channel_root)}
    server = subprocess.Popen(
        [str(console_script), str(planning), "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    resumed = False
    try:
        deadline = time.monotonic() + 5
        while not pid_path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        record = _read_record(pid_path)
        assert record.pid == server.pid

        os.kill(server.pid, signal.SIGSTOP)
        stopped = subprocess.run(
            [str(console_script), "--stop", "--port", str(port)],
            capture_output=True,
            text=True,
            env=environment,
            timeout=10,
        )

        assert stopped.returncode != 0
        assert server.poll() is None
        assert _read_record(pid_path) == record
        assert f"collection server PID {server.pid} is running" in stopped.stderr
        assert "identity" in stopped.stderr

        os.kill(server.pid, signal.SIGCONT)
        resumed = True
        clean_stop = subprocess.run(
            [str(console_script), "--stop", "--port", str(port)],
            capture_output=True,
            text=True,
            env=environment,
            timeout=10,
        )
        server.communicate(timeout=10)
        assert clean_stop.returncode == 0
    finally:
        if server.poll() is None:
            if not resumed:
                os.kill(server.pid, signal.SIGCONT)
            server.kill()
            server.communicate()


def test_stop_cli_fails_if_server_drops_http_but_does_not_finish_cleanup(monkeypatch, tmp_path):
    channel_root = tmp_path / "channel"
    planning = channel_root / "collections" / "planning"
    planning.mkdir(parents=True)
    pid_path = planning / ".collection-serve-7874.pid"
    record = collection_serve._LifecycleRecord(9876, "blocked-cleanup-token", "configuration")
    collection_serve._write_pid_file(pid_path, record)
    clock = iter([0.0, 6.0, 6.0])

    monkeypatch.setattr(collection_serve, "channel_dir", lambda: channel_root)
    monkeypatch.setattr(collection_serve, "_pid_is_running", lambda pid: True)
    monkeypatch.setattr(collection_serve, "_process_exit_watcher", lambda pid: contextlib.nullcontext(None))
    monkeypatch.setattr(collection_serve, "_request_server_stop", lambda port, candidate, attempt: True)
    monkeypatch.setattr(collection_serve.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(sys, "argv", ["yt-collection-serve", "--stop", "--port", "7874"])

    with pytest.raises(collection_serve.ConfigError, match="did not stop within 5 seconds"):
        collection_serve.main()

    assert pid_path.exists()


def test_stop_cli_never_signals_a_reused_pid_after_owner_accepts_stop(monkeypatch, tmp_path):
    channel_root = tmp_path / "channel"
    planning = channel_root / "collections" / "planning"
    planning.mkdir(parents=True)
    record = collection_serve._LifecycleRecord(9876, "owner-token", "configuration")
    request_paths: list[str] = []

    class OwnerHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            request_paths.append(self.path)
            body = json.dumps({"process_id": record.pid, "configuration": record.configuration}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:
            pass

    owner = ThreadingHTTPServer(("localhost", 0), OwnerHandler)
    port = owner.server_address[1]
    pid_path = planning / f".collection-serve-{port}.pid"
    collection_serve._write_pid_file(pid_path, record)
    owner_thread = threading.Thread(target=owner.serve_forever)
    owner_thread.start()
    clock = iter([0.0, 6.0, 6.0])
    monkeypatch.setattr(collection_serve, "channel_dir", lambda: channel_root)
    monkeypatch.setattr(collection_serve, "_pid_is_running", lambda pid: True)
    monkeypatch.setattr(collection_serve, "_process_exit_watcher", lambda pid: contextlib.nullcontext(None))
    monkeypatch.setattr(collection_serve.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(
        collection_serve.os,
        "kill",
        lambda pid, signum: pytest.fail("stop CLI must not signal a PID after identity verification"),
    )
    monkeypatch.setattr(sys, "argv", ["yt-collection-serve", "--stop", "--port", str(port)])
    try:
        with pytest.raises(collection_serve.ConfigError, match="did not stop within 5 seconds"):
            collection_serve.main()
    finally:
        owner.shutdown()
        owner.server_close()
        owner_thread.join()

    assert len(request_paths) == 1
    assert request_paths[0].startswith(f"/.well-known/yt-collection-serve-lifecycle/{record.token}/stop/")
    assert _read_record(pid_path) == record


def test_server_rejects_queued_stop_request_after_a_new_attempt_marker_is_published(monkeypatch, tmp_path):
    record = collection_serve._LifecycleRecord(os.getpid(), "owner-token", "configuration")
    server = collection_serve.create_server(
        0,
        None,
        prompts_path=None,
        collection_dir=None,
        distrokid=None,
        collections_root=tmp_path,
        lifecycle_record=record,
        lifecycle_root=tmp_path,
    )
    port = server.server_address[1]
    marker_path = collection_serve._stop_request_path(tmp_path, port)
    first_attempt = collection_serve._LifecycleRecord(record.pid, "first-attempt", record.configuration)
    second_attempt = collection_serve._LifecycleRecord(record.pid, "second-attempt", record.configuration)
    collection_serve._write_pid_file(marker_path, first_attempt)
    request_queued = threading.Event()
    response_status: list[int] = []

    def send_first_attempt() -> None:
        connection = http.client.HTTPConnection("localhost", port, timeout=5)
        connection.request("POST", collection_serve._lifecycle_stop_path(record, first_attempt.token))
        request_queued.set()
        response = connection.getresponse()
        response.read()
        response_status.append(response.status)
        connection.close()

    client = threading.Thread(target=send_first_attempt)
    client.start()
    assert request_queued.wait(timeout=5)
    collection_serve._remove_matching_record(marker_path, first_attempt)
    collection_serve._write_pid_file(marker_path, second_attempt)
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(collection_serve.os, "kill", lambda pid, signum: signals.append((pid, signum)))
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.start()
    try:
        client.join(timeout=5)
        assert not client.is_alive()
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join()

    assert response_status == [409]
    assert signals == []
    assert _read_record(marker_path) == second_attempt


def test_idle_timeout_raises_after_configured_inactivity(tmp_path):
    server = collection_serve.create_server(
        0,
        None,
        prompts_path=None,
        collection_dir=None,
        distrokid=None,
        collections_root=tmp_path,
        idle_timeout_seconds=0.01,
    )
    try:
        with pytest.raises(collection_serve._IdleTimeout):
            server.serve_forever(poll_interval=0.01)
    finally:
        server.server_close()


@pytest.mark.parametrize(
    ("cli_args", "expected_timeout"),
    [
        ([], collection_serve.DEFAULT_IDLE_TIMEOUT_SECONDS),
        (["--idle-timeout", "12.5"], 12.5),
    ],
)
def test_main_passes_idle_timeout_and_cleans_pid_file(monkeypatch, capsys, tmp_path, cli_args, expected_timeout):
    planning = tmp_path / "collections" / "planning"
    _make_collection(planning)
    recorded: list[float] = []

    class FakeServer:
        server_address = ("localhost", 7873)

        def serve_forever(self) -> None:
            raise collection_serve._IdleTimeout(12.5)

        def server_close(self) -> None:
            pass

    def fake_create_server(*args, **kwargs):
        recorded.append(kwargs["idle_timeout_seconds"])
        return FakeServer()

    monkeypatch.setattr(collection_serve, "create_server", fake_create_server)
    monkeypatch.setattr(
        collection_serve,
        "create_discovery_lifecycle",
        lambda *args, **kwargs: _NoopDiscoveryLifecycle(),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["yt-collection-serve", str(planning), *cli_args],
    )

    collection_serve.main()

    assert recorded == [expected_timeout]
    assert not (planning / ".collection-serve-7873.pid").exists()
    assert "Idle timeout reached:" in capsys.readouterr().out


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "0", "-1"])
def test_idle_timeout_rejects_non_finite_and_non_positive_values(value):
    with pytest.raises(argparse.ArgumentTypeError, match="finite number greater than zero"):
        collection_serve._positive_float(value)


@pytest.mark.parametrize("skill", ["suno-helper", "distrokid-helper"])
def test_helper_skill_stops_collection_server_after_user_workflow(skill):
    text = (Path(".claude/skills") / skill / "SKILL.md").read_text(encoding="utf-8")
    hard_gates = "\n".join(text.splitlines()[:60])

    assert "## 完了条件" in hard_gates
    assert "プロセス" in hard_gates
    assert "yt-collection-serve --stop --port" in text
    assert "ps aux" in text
    if skill == "distrokid-helper":
        assert "CHANNEL_DIR=/path/to/channel uv run yt-collection-serve --stop --port 7874" in text
