"""Bench helpers: timing, statistics, JSON 結果保存.

各 bench スクリプトはこの module の `time_calls` と `save_result` を使って
統計を JSON 出力する。
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"


@dataclass
class Stats:
    name: str
    n: int
    p50_ms: float
    p95_ms: float
    max_ms: float
    min_ms: float
    mean_ms: float
    samples_ms: list[float]


def time_calls(fn: Callable[[], Any], n: int = 10, warmup: int = 1, name: str = "") -> Stats:
    for _ in range(warmup):
        fn()
    samples = []
    for _ in range(n):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000.0)
    return _build_stats(name or fn.__name__, samples)


def _build_stats(name: str, samples_ms: list[float]) -> Stats:
    s = sorted(samples_ms)
    n = len(s)
    p50 = median(s)
    p95 = s[max(0, int(n * 0.95) - 1)]
    return Stats(
        name=name,
        n=n,
        p50_ms=round(p50, 3),
        p95_ms=round(p95, 3),
        max_ms=round(s[-1], 3),
        min_ms=round(s[0], 3),
        mean_ms=round(mean(s), 3),
        samples_ms=[round(v, 3) for v in samples_ms],
    )


def stats_from_samples(name: str, samples_ms: list[float]) -> Stats:
    """既に計測済みのサンプル列から Stats を組み立てる。"""
    return _build_stats(name, samples_ms)


def session_dir() -> Path:
    """環境変数 BENCH_SESSION で固定できる結果保存先（同セッションでまとめたいとき）."""
    name = os.environ.get("BENCH_SESSION")
    if not name:
        name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = RESULTS / name
    out.mkdir(parents=True, exist_ok=True)
    return out


def save_result(stats: Stats, *, extra: dict[str, Any] | None = None) -> Path:
    out = session_dir() / f"{stats.name}.json"
    payload = {
        "stats": asdict(stats),
        "env": _env_info(),
        "extra": extra or {},
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def _env_info() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "git_rev": _git_rev(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _git_rev() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=ROOT.parent,
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def format_table(rows: list[dict[str, Any]]) -> str:
    """Markdown 表生成（bench/main.py の REPORT.md 用）."""
    if not rows:
        return "(no results)"
    headers = list(rows[0].keys())
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
    return "\n".join(lines)
