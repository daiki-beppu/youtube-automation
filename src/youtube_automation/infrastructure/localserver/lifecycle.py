"""Filesystem lifecycle records shared by loopback local servers."""

from __future__ import annotations

import json
import os
import re
import select
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Callable, Iterator

from youtube_automation.core.errors import ConfigError

COLLECTION_SERVER_KIND = "collection-serve"
_SERVER_KIND_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class LifecycleRecord:
    pid: int
    token: str
    configuration: str


def pid_file_path(root: Path, port: int, *, server_kind: str = COLLECTION_SERVER_KIND) -> Path:
    return _state_path(root, port, server_kind=server_kind, suffix="pid")


def stop_request_path(root: Path, port: int, *, server_kind: str = COLLECTION_SERVER_KIND) -> Path:
    return _state_path(root, port, server_kind=server_kind, suffix="stop")


def startup_lock_path(root: Path, port: int, *, server_kind: str = COLLECTION_SERVER_KIND) -> Path:
    _validate_server_kind(server_kind)
    return root / f".{server_kind}-{port}"


def read_pid_file(path: Path) -> LifecycleRecord | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigError(f"PID file を読み取れません: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ConfigError(f"PID file が不正です: {path}")
    pid = payload.get("pid")
    token = payload.get("token")
    configuration = payload.get("configuration")
    if (
        not isinstance(pid, int)
        or isinstance(pid, bool)
        or pid <= 0
        or not isinstance(token, str)
        or not token
        or not isinstance(configuration, str)
        or not configuration
    ):
        raise ConfigError(f"PID file が不正です: {path}")
    return LifecycleRecord(pid=pid, token=token, configuration=configuration)


def write_pid_file(path: Path, record: LifecycleRecord) -> None:
    """Publish a lifecycle record without replacing an existing owner."""
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            json.dump(
                {"pid": record.pid, "token": record.token, "configuration": record.configuration},
                stream,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary_path, path)
        except FileExistsError as exc:
            raise ConfigError(f"PID file already exists: {path}") from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def pid_is_running(
    pid: int,
    *,
    platform: str | None = None,
    os_module: ModuleType = os,
    subprocess_module: ModuleType = subprocess,
    windows_checker: Callable[[int], bool] | None = None,
) -> bool:
    current_platform = platform or sys.platform
    if current_platform == "win32":
        checker = windows_checker or pid_is_running_windows
        return checker(pid)
    try:
        os_module.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        status = subprocess_module.run(
            ["ps", "-o", "stat=", "-p", str(pid)],
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError:
        return True
    return not (status.returncode == 0 and status.stdout.lstrip().startswith("Z"))


@contextmanager
def process_exit_watcher(
    pid: int,
    *,
    os_module: ModuleType = os,
    select_module: ModuleType = select,
) -> Iterator[Callable[[float], bool] | None]:
    """Yield an efficient process-exit waiter when the platform provides one."""
    pidfd_open = getattr(os_module, "pidfd_open", None)
    if callable(pidfd_open):
        try:
            descriptor = pidfd_open(pid)
        except OSError:
            pass
        else:
            try:
                yield lambda timeout: bool(select_module.select([descriptor], [], [], timeout)[0])
            finally:
                os_module.close(descriptor)
            return

    if hasattr(select_module, "kqueue") and hasattr(select_module, "KQ_NOTE_EXIT"):
        queue = select_module.kqueue()
        try:
            event = select_module.kevent(
                pid,
                filter=select_module.KQ_FILTER_PROC,
                flags=select_module.KQ_EV_ADD | select_module.KQ_EV_ENABLE,
                fflags=select_module.KQ_NOTE_EXIT,
            )
            queue.control([event], 0, 0)
        except OSError:
            queue.close()
        else:
            try:
                yield lambda timeout: bool(queue.control(None, 1, timeout))
            finally:
                queue.close()
            return

    yield None


def remove_owned_pid_file(path: Path, pid: int) -> None:
    try:
        record = read_pid_file(path)
        if record is not None and record.pid == pid:
            path.unlink()
    except FileNotFoundError:
        return


def remove_matching_record(path: Path, expected: LifecycleRecord) -> None:
    try:
        if read_pid_file(path) == expected:
            path.unlink()
    except FileNotFoundError:
        return


def consume_stop_request(path: Path, pid: int) -> bool:
    try:
        request = read_pid_file(path)
    except ConfigError:
        return False
    if request is None or request.pid != pid:
        return False
    path.unlink(missing_ok=True)
    return True


def _state_path(root: Path, port: int, *, server_kind: str, suffix: str) -> Path:
    _validate_server_kind(server_kind)
    return root / f".{server_kind}-{port}.{suffix}"


def _validate_server_kind(server_kind: str) -> None:
    if not _SERVER_KIND_PATTERN.fullmatch(server_kind):
        raise ValueError("server_kind must be a lowercase ASCII slug")


def pid_is_running_windows(pid: int) -> bool:
    """Use WinAPI because ``os.kill(pid, 0)`` is unsupported on Windows."""
    import ctypes

    process_query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)
