"""cost_tracker.log_generation のフル JSON 書き戻しコストを計測する.

`audio_costs.json` は実運用で 156+ 件まで膨らんでおり、1 件追記のたびに全エントリを
パース＋書き戻している。サイズ別に挙動を見る。
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bench.common import Stats, save_result, time_calls

SIZES = (156, 500, 1000)


def _seed_log(path: Path, size: int) -> None:
    entries = [
        {
            "timestamp": "2026-01-01T00:00:00+00:00",
            "category": "audio",
            "model": "lyria-3.0-1-preview",
            "quantity": 30,
            "unit": "30sec",
            "estimated_cost_usd": 0.06,
            "metadata": {"seed": i},
        }
        for i in range(size)
    ]
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@contextlib.contextmanager
def _scoped_channel_dir(path: Path):
    """CHANNEL_DIR を tmp に切り替え、終了時に必ず元へ戻す."""
    from youtube_automation.utils import config as cfg

    original = os.environ.get("CHANNEL_DIR")
    os.environ["CHANNEL_DIR"] = str(path)
    cfg.reset()
    try:
        yield
    finally:
        if original is None:
            os.environ.pop("CHANNEL_DIR", None)
        else:
            os.environ["CHANNEL_DIR"] = original
        cfg.reset()


def _bench_log_generation(size: int) -> Stats:
    with tempfile.TemporaryDirectory() as tmpdir:
        channel_dir = Path(tmpdir) / "channel"
        (channel_dir / "data").mkdir(parents=True)
        with _scoped_channel_dir(channel_dir):
            from youtube_automation.utils import cost_tracker

            log_path = channel_dir / "data" / "audio_costs.json"
            _seed_log(log_path, size)

            def call() -> None:
                cost_tracker.log_generation(
                    "audio",
                    model="lyria-3.0-1-preview",
                    quantity=30,
                    metadata={"bench": True},
                )

            return time_calls(call, n=50, warmup=2, name=f"log_generation_n{size}")


def _bench_read_all(size: int) -> Stats:
    with tempfile.TemporaryDirectory() as tmpdir:
        channel_dir = Path(tmpdir) / "channel"
        (channel_dir / "data").mkdir(parents=True)
        with _scoped_channel_dir(channel_dir):
            from youtube_automation.utils import cost_tracker

            for cat in ("image", "video", "audio"):
                _seed_log(channel_dir / "data" / f"{cat}_costs.json", size)

            return time_calls(cost_tracker.read_all, n=20, warmup=1, name=f"read_all_n{size}")


def run() -> Sequence[Stats]:
    results: list[Stats] = []
    for size in SIZES:
        s1 = _bench_log_generation(size)
        s2 = _bench_read_all(size)
        save_result(s1, extra={"size": size, "category": "audio"})
        save_result(s2, extra={"size_per_category": size})
        results.extend([s1, s2])
        print(f"  log_generation n={size:>4}: p50={s1.p50_ms:.3f}ms p95={s1.p95_ms:.3f}ms")
        print(f"  read_all       n={size:>4}: p50={s2.p50_ms:.3f}ms p95={s2.p95_ms:.3f}ms")
    return results


if __name__ == "__main__":
    run()
