#!/usr/bin/env python3
"""yt-win-pattern: VPD 上位・下位群の属性別件数とパターンを出力する。"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from youtube_automation.commands.analytics import vpd_rank
from youtube_automation.commands.analytics.analytics_system import AnalyticsSystem
from youtube_automation.configuration import load_config
from youtube_automation.configuration.skills import load_skill_config
from youtube_automation.core.errors import AuthError, AutomationError, ValidationError
from youtube_automation.infrastructure.analytics.win_pattern import (
    build_automatic_attributes,
    build_win_pattern_result,
    load_annotations,
    validate_ranking,
)

logger = logging.getLogger(__name__)


def _read_ranking(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValidationError(f"ranking JSON を読めません: {path}") from error
    return validate_ranking(payload)


def _load_live_details(video_ids: list[str]) -> dict[str, dict]:
    system = AnalyticsSystem()
    if not system.authenticate() or system.collector is None:
        raise AuthError("YouTube read-only 認証に失敗しました")
    return system.collector.get_video_details(video_ids)


def _title_patterns() -> object:
    config = load_skill_config("analytics")
    win_pattern = config.get("win_pattern")
    if not isinstance(win_pattern, dict) or "title_patterns" not in win_pattern:
        raise ValidationError("analytics.win_pattern.title_patterns が未設定です")
    return win_pattern["title_patterns"]


def _load_result(
    *,
    ranking_path: Path | None,
    annotations_path: Path | None,
    min_age_days: int,
    top_count: int | None,
) -> dict[str, object]:
    if ranking_path is None:
        ranking = vpd_rank._load_ranking(min_age_days=min_age_days, top_count=top_count)
        video_ids = [item["video_id"] for item in ranking["ranking"]]
        details = _load_live_details(video_ids)
    else:
        ranking = _read_ranking(ranking_path)
        details = {}
    ranking = validate_ranking(ranking)
    videos = ranking["ranking"]
    video_ids = {item["video_id"] for item in videos}
    config = load_config()
    automatic = build_automatic_attributes(
        videos,
        details=details,
        theme_keywords=config.content.tags.themes,
        title_patterns=_title_patterns(),
    )
    visual = load_annotations(annotations_path, known_video_ids=video_ids)
    return build_win_pattern_result(ranking, {**automatic, **visual})


def _print_text(result: dict[str, object]) -> None:
    print(f"Win patterns: N={result['n']} K={result['k']}")
    attributes = result["attributes"]
    assert isinstance(attributes, dict)
    for attribute, summary in attributes.items():
        print(f"\n{attribute}")
        for value, record in summary["values"].items():
            print(
                f"- {value}: {record['classification']} "
                f"top={record['top_count']}/{record['top_known_count']} ({record['top_percentage']}%) "
                f"bottom={record['bottom_count']}/{record['bottom_known_count']} "
                f"({record['bottom_percentage']}%) pp={record['pp_difference']} "
                f"ids={','.join(record['representative_video_ids'])}"
            )
        undetermined = summary["undetermined_count"]
        print(f"  undetermined: top={undetermined['top']} bottom={undetermined['bottom']}")
    print(f"\n{result['disclaimer']}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="VPD 上位・下位群の属性別本数と勝ち・負けパターンを判定")
    parser.add_argument(
        "--ranking", type=Path, help="yt-vpd-rank で取得済みの JSON（指定時は live ranking を取得しない）"
    )
    parser.add_argument("--annotations", type=Path, help="目視 5 属性の annotation JSON")
    parser.add_argument("--min-age-days", type=int, default=7, help="live ranking の最低公開日齢 (default: 7)")
    parser.add_argument("--top-count", type=int, help="live ranking の上位・下位群件数")
    parser.add_argument("--text", action="store_true", help="人間向けテキスト出力")
    args = parser.parse_args(argv)
    if args.ranking is not None and (args.min_age_days != 7 or args.top_count is not None):
        parser.error("--ranking と --min-age-days / --top-count は同時指定できません")
    try:
        result = _load_result(
            ranking_path=args.ranking,
            annotations_path=args.annotations,
            min_age_days=args.min_age_days,
            top_count=args.top_count,
        )
        if args.text:
            _print_text(result)
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except AutomationError as error:
        logger.error(str(error))
        return 2
    except Exception as error:
        logger.exception("win pattern の作成に失敗しました: %s", error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
