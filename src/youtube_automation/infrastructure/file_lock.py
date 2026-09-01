"""Cross-platform exclusive file locking."""

from __future__ import annotations

import contextlib
import errno
import os
import threading
import time
from pathlib import Path
from typing import BinaryIO, Iterator

try:
    import fcntl as _fcntl
except ImportError:
    _fcntl = None

try:
    import msvcrt as _msvcrt
except ImportError:
    _msvcrt = None

_LOCK_FILE_SUFFIX = ".lock"
_LOCK_REGION_BYTES = 1
_MSVCRT_LOCK_RETRY_DELAY_SECONDS = 0.05
_MSVCRT_LOCK_MAX_ATTEMPTS = 20
_MSVCRT_LOCK_RETRY_ERRNOS = {
    errno.EACCES,
    errno.EAGAIN,
    getattr(errno, "EDEADLK", errno.EACCES),
}
_MSVCRT_LOCK_RETRY_WINERRORS = {
    32,  # ERROR_SHARING_VIOLATION
    33,  # ERROR_LOCK_VIOLATION
}
_IN_PROCESS_LOCK = threading.Lock()


@contextlib.contextmanager
def file_lock(path: Path) -> Iterator[None]:
    """Prevent concurrent access to the file at ``path``."""
    if _fcntl is None and _msvcrt is None:
        with _IN_PROCESS_LOCK:
            yield
        return

    lock_path = path.with_suffix(path.suffix + _LOCK_FILE_SUFFIX)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with _IN_PROCESS_LOCK:
        with lock_path.open("a+b") as lock_file:
            _prepare_lock_file(lock_file)
            _acquire_lock(lock_file)
            try:
                yield
            finally:
                _release_lock(lock_file)


def _prepare_lock_file(lock_file: BinaryIO) -> None:
    lock_file.seek(0, 2)
    size = lock_file.tell()
    if size < _LOCK_REGION_BYTES:
        lock_file.write(b"\0" * (_LOCK_REGION_BYTES - size))
        lock_file.flush()
    lock_file.seek(0)


def _acquire_lock(lock_file: BinaryIO) -> None:
    if _fcntl is not None:
        _fcntl.flock(lock_file.fileno(), _fcntl.LOCK_EX)
        return
    if _msvcrt is not None:
        _acquire_msvcrt_lock(lock_file)
        return
    raise RuntimeError("platform file locks are unavailable")


def _acquire_msvcrt_lock(lock_file: BinaryIO, *, wait_forever: bool = False) -> None:
    max_attempts = None if wait_forever else _MSVCRT_LOCK_MAX_ATTEMPTS
    last_error: OSError | None = None
    attempt = 0
    while max_attempts is None or attempt < max_attempts:
        attempt += 1
        lock_file.seek(0)
        try:
            _msvcrt.locking(lock_file.fileno(), _msvcrt.LK_NBLCK, _LOCK_REGION_BYTES)
            return
        except OSError as error:
            if not _is_msvcrt_lock_contention(error):
                raise
            last_error = error
            if max_attempts is not None and attempt == max_attempts:
                break
            time.sleep(_MSVCRT_LOCK_RETRY_DELAY_SECONDS)
    raise TimeoutError(f"msvcrt lock acquisition timed out after {max_attempts} attempts") from last_error


def _is_msvcrt_lock_contention(error: OSError) -> bool:
    return error.errno in _MSVCRT_LOCK_RETRY_ERRNOS or getattr(error, "winerror", None) in _MSVCRT_LOCK_RETRY_WINERRORS


def _release_lock(lock_file: BinaryIO) -> None:
    if _fcntl is not None:
        _fcntl.flock(lock_file.fileno(), _fcntl.LOCK_UN)
        return
    if _msvcrt is not None:
        lock_file.seek(0)
        _msvcrt.locking(lock_file.fileno(), _msvcrt.LK_UNLCK, _LOCK_REGION_BYTES)
        return
    raise RuntimeError("platform file locks are unavailable")


@contextlib.contextmanager
def file_descriptor_lock(descriptor: int) -> Iterator[None]:
    """Exclusively lock an already securely opened file descriptor."""
    with os.fdopen(descriptor, "r+b", closefd=False) as lock_file:
        _prepare_lock_file(lock_file)
        if _fcntl is not None:
            _fcntl.flock(lock_file.fileno(), _fcntl.LOCK_EX)
        elif _msvcrt is not None:
            _acquire_msvcrt_lock(lock_file, wait_forever=True)
        else:
            raise RuntimeError("platform file locks are unavailable")
        try:
            yield
        finally:
            _release_lock(lock_file)
