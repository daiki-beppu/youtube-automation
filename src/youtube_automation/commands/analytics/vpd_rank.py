#!/usr/bin/env python3
"""yt-vpd-rank: 全チャンネル動画の views-per-day 群を出力する。"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from datetime import datetime

from youtube_automation.commands.analytics.analytics_system import AnalyticsSystem
from youtube_automation.core.errors import AuthError, AutomationError
from youtube_automation.infrastructure.analytics.vpd_metrics import (
    build_vpd_ranking,
    collect_all_video_statistics,
)

logger = logging.getLogger(__name__)


def _load_ranking(*, min_age_days: int, top_count: int | None, now: datetime | None = None) -> dict[str, object]:
    system = AnalyticsSystem()
    if not system.authenticate():
        raise AuthError("YouTube read-only 認証に失敗しました")
    if system.collector is None:
        raise AuthError("YouTube collector を初期化できませんでした")
    videos = collect_all_video_statistics(system.collector)
    return build_vpd_ranking(videos, now=now, min_age_days=min_age_days, top_count=top_count)


def _print_text(result: dict[str, object]) -> None:
    print(
        f"VPD ranking: N={result['n']} K={result['k']} "
        f"min_age_days={result['min_age_days']} excluded={result['excluded_count']}"
    )
    groups = result["groups"]
    assert isinstance(groups, dict)
    for name in ("top", "middle", "bottom"):
        group = groups[name]
        assert isinstance(group, dict)
        print(f"\n{name.upper()} ({group['count']}) vpd={group['min_vpd']}..{group['max_vpd']}")
        for item in group["items"]:
            print(
                f"- {item['video_id']}  vpd={item['vpd']}  views={item['cumulative_views']}  "
                f"days={item['days_since_publish']}  {item['title']}"
            )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="全動画の累計 views-per-day 上位・中間・下位群を確定")
    parser.add_argument("--min-age-days", type=int, default=7, help="公開後の最低経過日数 (default: 7)")
    parser.add_argument("--top-count", type=int, help="上位群・下位群それぞれの件数")
    parser.add_argument("--text", action="store_true", help="人間向けテキスト出力")
    args = parser.parse_args(argv)

    try:
        result = _load_ranking(min_age_days=args.min_age_days, top_count=args.top_count)
        if args.text:
            _print_text(result)
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except AutomationError as error:
        logger.error(str(error))
        return 2
    except Exception as error:
        logger.exception("VPD ranking の作成に失敗しました: %s", error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
