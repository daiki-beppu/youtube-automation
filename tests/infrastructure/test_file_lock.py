from __future__ import annotations

import builtins
import contextlib
import importlib
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

_FILE_LOCK_MODULE = "youtube_automation.infrastructure.file_lock"
_MISSING_MODULE = object()


@contextlib.contextmanager
def _import_file_lock_without(
    monkeypatch: pytest.MonkeyPatch,
    unavailable_modules: set[str],
    *,
    msvcrt_module: ModuleType | None = None,
) -> Iterator[ModuleType]:
    real_import = builtins.__import__

    def import_without_platform_modules(name: str, *args, **kwargs):
        if name in unavailable_modules:
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_platform_modules)
    previous_module = sys.modules.pop(_FILE_LOCK_MODULE, _MISSING_MODULE)
    if msvcrt_module is not None:
        monkeypatch.setitem(sys.modules, "msvcrt", msvcrt_module)
    try:
        yield importlib.import_module(_FILE_LOCK_MODULE)
    finally:
        sys.modules.pop(_FILE_LOCK_MODULE, None)
        if previous_module is not _MISSING_MODULE:
            sys.modules[_FILE_LOCK_MODULE] = previous_module


def test_file_lock_uses_msvcrt_when_fcntl_is_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Given fcntl なし / msvcrt あり
    When 共通ファイルロックを取得・解放する
    Then import に成功し、msvcrt の排他ロックを利用する。
    """
    calls: list[tuple[int, int]] = []
    fake_msvcrt = ModuleType("msvcrt")
    fake_msvcrt.LK_NBLCK = 1
    fake_msvcrt.LK_UNLCK = 2
    fake_msvcrt.locking = lambda _fd, mode, size: calls.append((mode, size))

    with _import_file_lock_without(monkeypatch, {"fcntl"}, msvcrt_module=fake_msvcrt) as module:
        with module.file_lock(tmp_path / "state.json"):
            pass

    assert calls == [(fake_msvcrt.LK_NBLCK, 1), (fake_msvcrt.LK_UNLCK, 1)]


def test_file_lock_releases_msvcrt_lock_when_body_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Given msvcrt ロック取得後に処理が失敗する
    When context manager から例外が送出される
    Then ロックを解放し、元の例外を伝播する。
    """
    calls: list[tuple[int, int]] = []
    fake_msvcrt = ModuleType("msvcrt")
    fake_msvcrt.LK_NBLCK = 1
    fake_msvcrt.LK_UNLCK = 2
    fake_msvcrt.locking = lambda _fd, mode, size: calls.append((mode, size))

    with _import_file_lock_without(monkeypatch, {"fcntl"}, msvcrt_module=fake_msvcrt) as module:
        with pytest.raises(ValueError, match="critical section failed"):
            with module.file_lock(tmp_path / "state.json"):
                raise ValueError("critical section failed")

    assert calls == [(fake_msvcrt.LK_NBLCK, 1), (fake_msvcrt.LK_UNLCK, 1)]


def test_file_descriptor_lock_retries_windows_contention_until_acquired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows の競合が旧上限を超えても、解除後に descriptor lock を取得する。"""
    attempts = 0
    fake_msvcrt = ModuleType("msvcrt")
    fake_msvcrt.LK_NBLCK = 1
    fake_msvcrt.LK_UNLCK = 2

    def locking(_descriptor: int, mode: int, _size: int) -> None:
        nonlocal attempts
        if mode == fake_msvcrt.LK_NBLCK:
            attempts += 1
            if attempts <= 20:
                raise OSError(13, "lock contention")

    fake_msvcrt.locking = locking
    lock_path = tmp_path / "lease.mutex"
    lock_path.touch()

    with _import_file_lock_without(monkeypatch, {"fcntl"}, msvcrt_module=fake_msvcrt) as module:
        monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
        descriptor = lock_path.open("r+b")
        try:
            with module.file_descriptor_lock(descriptor.fileno()):
                pass
        finally:
            descriptor.close()

    assert attempts == 21


def test_file_lock_serializes_threads_without_platform_locks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Given fcntl / msvcrt の双方がない環境
    When 複数スレッドが共通ファイルロックを使う
    Then import に成功し、プロセス内ロックでクリティカルセクションを直列化する。
    """
    barrier = threading.Barrier(3)
    active_count = 0
    maximum_active_count = 0

    def enter_critical_section() -> None:
        nonlocal active_count, maximum_active_count
        barrier.wait()
        with module.file_lock(tmp_path / "state.json"):
            active_count += 1
            maximum_active_count = max(maximum_active_count, active_count)
            time.sleep(0.02)
            active_count -= 1

    with _import_file_lock_without(monkeypatch, {"fcntl", "msvcrt"}) as module:
        threads = [threading.Thread(target=enter_critical_section) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()

    assert maximum_active_count == 1
