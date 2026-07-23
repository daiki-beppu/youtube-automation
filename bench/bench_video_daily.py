"""`video_daily_analytics.get_video_daily_analytics` を 28d / 90d で実測.

実 YouTube Analytics API を叩く（無料枠）。`CHANNEL_DIR` / `auth/token.json` が
必要。`--dry-run` 相当のスキップ条件は import / 認証エラー。
"""

from __future__ import annotations

import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bench.common import Stats, save_result, stats_from_samples
from youtube_automation.configuration import channel_dir
from youtube_automation.domains.analytics.service import YouTubeAnalyticsCollector
from youtube_automation.infrastructure.analytics_adapter import AnalyticsAdapter, YouTubeDataAdapter
from youtube_automation.utils.exceptions import AuthError, ConfigError
from youtube_automation.utils.reporting_api import ReportingAPIClient
from youtube_automation.utils.youtube_service import (
    get_analytics,
    get_credentials_readonly,
    get_reporting,
    get_youtube_readonly,
)


def _collector():
    c = YouTubeAnalyticsCollector(
        youtube_client=YouTubeDataAdapter(get_youtube_readonly(), retry_requests=True),
        analytics_client=AnalyticsAdapter(get_analytics(), retry_requests=True),
        reporting_client=ReportingAPIClient(get_reporting(), credentials=get_credentials_readonly()),
        channel_root=channel_dir(),
    )
    c.initialize()
    return c


def _bench_days(collector, days: int) -> Stats:
    end = date.today()
    start = end - timedelta(days=days)
    samples: list[float] = []
    rows = 0
    for _ in range(3):
        t0 = time.perf_counter()
        rows = len(collector.get_video_daily_analytics(start.isoformat(), end.isoformat()))
        samples.append((time.perf_counter() - t0) * 1000.0)
    stats = stats_from_samples(f"video_daily_{days}d", samples)
    save_result(stats, extra={"days": days, "rows": rows})
    print(f"  video_daily {days:>3}d: p50={stats.p50_ms:.0f}ms rows={rows}")
    return stats


def run() -> Sequence[Stats]:
    try:
        collector = _collector()
    except (AuthError, ConfigError, FileNotFoundError) as e:
        print(f"  [SKIP] collector の初期化失敗: {e}")
        return []

    results: list[Stats] = []
    for days in (28, 90):
        results.append(_bench_days(collector, days))
    return results


if __name__ == "__main__":
    run()
