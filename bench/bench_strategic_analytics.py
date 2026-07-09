"""逐次 vs ThreadPoolExecutor の理論短縮量を計測する.

`strategic_analytics.get_video_analytics_by_id` は動画ごとに API を逐次呼び出している。
実際の API レイテンシ（≈50ms）を `time.sleep` でモックし、N=100 動画での
直列 / 並列 (workers=4, 8, 16) の所要時間を比較する。

実 API は叩かないため bench_real_apis には含めず、本 bench は単独で完結する。
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bench.common import Stats, save_result, time_calls

N_VIDEOS = 100
MOCK_LATENCY_SEC = 0.05


def _mock_api_call(_: int) -> int:
    time.sleep(MOCK_LATENCY_SEC)
    return 1


def _bench_serial() -> Stats:
    def call() -> None:
        for i in range(N_VIDEOS):
            _mock_api_call(i)

    return time_calls(call, n=3, warmup=0, name="serial_n100")


def _bench_parallel(workers: int) -> Stats:
    def call() -> None:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(_mock_api_call, range(N_VIDEOS)))

    return time_calls(call, n=3, warmup=0, name=f"parallel_w{workers}_n100")


def run() -> Sequence[Stats]:
    results: list[Stats] = []
    s = _bench_serial()
    save_result(s, extra={"mock_latency_ms": MOCK_LATENCY_SEC * 1000, "n_videos": N_VIDEOS})
    results.append(s)
    print(f"  serial      n={N_VIDEOS}: p50={s.p50_ms:.1f}ms p95={s.p95_ms:.1f}ms")

    for workers in (4, 8, 16):
        sp = _bench_parallel(workers)
        save_result(sp, extra={"workers": workers, "n_videos": N_VIDEOS})
        results.append(sp)
        speedup = s.p50_ms / sp.p50_ms if sp.p50_ms else float("inf")
        print(
            f"  parallel w={workers:>2} n={N_VIDEOS}: "
            f"p50={sp.p50_ms:.1f}ms p95={sp.p95_ms:.1f}ms speedup={speedup:.1f}x"
        )
    return results


if __name__ == "__main__":
    run()
