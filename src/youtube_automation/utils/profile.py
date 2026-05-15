"""Section profiler for CLI performance measurement.

`YT_PROFILE=1` で有効化し、`with section("name"):` で囲んだブロックの経過時間を計測する。
無効時は `nullcontext` を返してオーバーヘッドゼロ。

Environment variables:
- ``YT_PROFILE``: ``1`` / ``true`` / ``yes`` で計測 ON。それ以外は no-op。
- ``YT_PROFILE_OUT``: 指定したパスに JSONL で 1 行ずつ追記。未指定なら stderr。
- ``YT_PROFILE_SUMMARY``: ``1`` で ``atexit`` に p50 / p95 / max / 件数を出力。

Usage:
    from youtube_automation.utils.profile import section

    with section("cost_tracker.write", category="audio"):
        path.write_text(...)
"""

from __future__ import annotations

import atexit
import json
import os
import sys
import time
from collections import defaultdict
from contextlib import contextmanager, nullcontext
from pathlib import Path
from statistics import median
from typing import Any, ContextManager, Iterator

_TRUTHY = {"1", "true", "yes"}
_NOOP: ContextManager[None] = nullcontext()
_records: dict[str, list[float]] = defaultdict(list)
_out_path: Path | None = None
_initialized = False


def _flag(name: str) -> bool:
    return os.environ.get(name, "").lower() in _TRUTHY


def _initialize() -> None:
    global _initialized, _out_path
    if _initialized:
        return
    raw = os.environ.get("YT_PROFILE_OUT")
    if raw:
        _out_path = Path(raw).expanduser()
        _out_path.parent.mkdir(parents=True, exist_ok=True)
    if _flag("YT_PROFILE_SUMMARY"):
        atexit.register(_dump_summary)
    _initialized = True


@contextmanager
def _timed(name: str, extra: dict[str, Any] | None) -> Iterator[None]:
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        _records[name].append(elapsed_ms)
        record: dict[str, Any] = {"section": name, "elapsed_ms": round(elapsed_ms, 3)}
        if extra:
            record.update(extra)
        if _out_path is not None:
            with _out_path.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(record, ensure_ascii=False) + "\n")
        else:
            suffix = ""
            if extra:
                suffix = " " + " ".join(f"{k}={v}" for k, v in extra.items())
            print(
                f"[PROFILE] section={name} elapsed_ms={elapsed_ms:.3f}{suffix}",
                file=sys.stderr,
            )


def section(name: str, **extra: Any) -> ContextManager[None]:
    """Measure a named section. Returns no-op context manager unless ``YT_PROFILE`` is set."""
    if not _flag("YT_PROFILE"):
        return _NOOP
    _initialize()
    return _timed(name, extra or None)


def _dump_summary() -> None:
    if not _records:
        return
    print("[PROFILE SUMMARY]", file=sys.stderr)
    for name in sorted(_records):
        values = sorted(_records[name])
        n = len(values)
        p50 = median(values)
        p95 = values[max(0, int(n * 0.95) - 1)]
        max_ms = values[-1]
        print(
            f"  {name}: n={n} p50={p50:.3f}ms p95={p95:.3f}ms max={max_ms:.3f}ms",
            file=sys.stderr,
        )


def reset() -> None:
    """Reset internal state. Test-only helper."""
    global _initialized, _out_path
    _records.clear()
    _out_path = None
    _initialized = False
