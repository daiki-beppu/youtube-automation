"""`benchmark_collector.collect_channel` の `channels.list` バッチ化効果を実測.

現状は 1 チャンネル ID ごとに `channels().list()` を呼んでいる。
YouTube Data API は最大 50 ID をカンマ区切りで一括取得できるため、
1 件 × N 回 vs 50 件カンマ区切り 1 回 のレイテンシを比較する。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bench.common import Stats, save_result, stats_from_samples  # noqa: E402

# 大手チャンネル ID（YouTube の永続 ID。bench でのみ参照）
CHANNEL_IDS = [
    "UC_x5XG1OV2P6uZZ5FSM9Ttw",  # Google Developers
    "UCBR8-60-B28hp2BmDPdntcQ",  # YouTube
    "UCWfWY7-yX_Pm0bOpkJUL5DA",  # GitHub
]


def _youtube_client():
    from youtube_automation.utils.youtube_service import get_youtube

    return get_youtube()


def _bench_individual(yt, ids: list[str]) -> Stats:
    samples: list[float] = []
    for _ in range(2):
        t0 = time.perf_counter()
        for cid in ids:
            yt.channels().list(part="snippet,statistics", id=cid).execute()
        samples.append((time.perf_counter() - t0) * 1000.0)
    return stats_from_samples(f"channels_list_individual_n{len(ids)}", samples)


def _bench_batched(yt, ids: list[str]) -> Stats:
    samples: list[float] = []
    for _ in range(2):
        t0 = time.perf_counter()
        yt.channels().list(part="snippet,statistics", id=",".join(ids)).execute()
        samples.append((time.perf_counter() - t0) * 1000.0)
    return stats_from_samples(f"channels_list_batched_n{len(ids)}", samples)


def run() -> Sequence[Stats]:
    try:
        yt = _youtube_client()
    except Exception as e:  # noqa: BLE001
        print(f"  [SKIP] youtube client 取得失敗: {e}")
        return []

    s1 = _bench_individual(yt, CHANNEL_IDS)
    s2 = _bench_batched(yt, CHANNEL_IDS)
    save_result(s1, extra={"strategy": "individual", "n": len(CHANNEL_IDS)})
    save_result(s2, extra={"strategy": "batched", "n": len(CHANNEL_IDS)})

    speedup = s1.p50_ms / s2.p50_ms if s2.p50_ms else float("inf")
    print(f"  individual n={len(CHANNEL_IDS)}: p50={s1.p50_ms:.0f}ms")
    print(f"  batched    n={len(CHANNEL_IDS)}: p50={s2.p50_ms:.0f}ms  speedup={speedup:.1f}x")
    return [s1, s2]


if __name__ == "__main__":
    run()
