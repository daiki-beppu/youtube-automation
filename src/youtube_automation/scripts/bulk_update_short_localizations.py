#!/usr/bin/env python3
"""Shorts ローカライズメタデータを YouTube に一括反映する CLI.

`collections/live/*/workflow-state.json` の `post_upload.shorts: list[dict]` を巡回し、
各動画について `videos().update(part='localizations')` を呼び出して、`localizations.json`
に基づく多言語タイトル / 説明文を反映する.

Usage:
    yt-shorts-bulk-update-loc            # 実反映
    yt-shorts-bulk-update-loc --dry-run  # 反映せずプレビューだけ
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time

from youtube_automation.domains.metadata import build_short_localizations
from youtube_automation.utils.collection_paths import CollectionPaths
from youtube_automation.utils.config import channel_dir, load_config
from youtube_automation.utils.cost_tracker import log_quota
from youtube_automation.utils.youtube_service import get_youtube

logger = logging.getLogger(__name__)


# per-video スリープ。quota 急上昇防止（plan アンチパターン #8）
SLEEP_SEC_PER_VIDEO = 0.5

# YouTube Data API quota 記録（Issue #2058）。units は公式 quota 表に従う
# （https://developers.google.com/youtube/v3/determine_quota_cost）。
QUOTA_SERVICE = "youtube-data-api"
VIDEOS_UPDATE_QUOTA_UNITS = 50


def collect_short_videos() -> list[dict]:
    """`collections/live/*/workflow-state.json` から Shorts video_id を集める.

    スキーマ: `post_upload.shorts: list[dict]`（`ShortUploader._update_workflow_state` と対称）.
    `20-documentation/upload_tracking.json` が無いコレクションは skip（CC URL が無いと
    description テンプレ展開が空になるため）.

    Returns:
        [{"video_id": str, "short_num": int|None, "collection_name": str,
          "theme": str, "cc_video_url": str}, ...]
    """
    ch = channel_dir()
    live_dir = ch / "collections" / "live"
    if not live_dir.exists():
        return []

    results: list[dict] = []
    for col_dir in sorted(live_dir.iterdir()):
        paths = CollectionPaths(col_dir)
        ws_path = paths.workflow_state_path
        if not ws_path.exists():
            continue
        tracking_path = paths.tracking_path
        if not tracking_path.exists():
            # tracking 無は CC URL を引けないので Shorts も skip
            continue
        try:
            with open(ws_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            with open(tracking_path, "r", encoding="utf-8") as f:
                tracking = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"⚠️  {col_dir.name} 読み込み失敗: {e}")
            continue

        cc = tracking.get("complete_collection") or {}
        cc_video_url = cc.get("video_url", "")
        collection_name = state.get("collection_name") or col_dir.name
        theme = state.get("theme", "") or ""

        for entry in (state.get("post_upload") or {}).get("shorts") or []:
            video_id = entry.get("video_id")
            if not video_id:
                continue
            results.append(
                {
                    "video_id": video_id,
                    "short_num": entry.get("short_num"),
                    "collection_name": collection_name,
                    "theme": theme,
                    "cc_video_url": cc_video_url,
                }
            )
    return results


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Shorts ローカライズメタデータ一括更新")
    parser.add_argument("--dry-run", action="store_true", help="反映せずプレビューのみ")
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = _build_parser()
    args = parser.parse_args()

    videos = collect_short_videos()
    if not videos:
        print("❌ 更新対象の Shorts が見つかりません")
        sys.exit(1)

    # 1 回だけ config をロードして全 video で使い回す（loader singleton 経由なので
    # 厳密にはキャッシュされるが、helper 呼出に渡すために明示的に保持する）
    config = load_config()

    def _locs_for(v: dict) -> dict:
        return build_short_localizations(
            config,
            collection_name=v["collection_name"],
            theme=v["theme"],
            cc_video_url=v["cc_video_url"],
        )

    print(f"🎯 対象: {len(videos)} 件")
    if args.dry_run:
        print("🔍 dry-run モード（YouTube API は呼び出しません）")
        for v in videos:
            locs = _locs_for(v)
            print(f"  - {v['video_id']} ({v['collection_name']}): langs={list(locs.keys())}")
        return

    youtube = get_youtube()
    for v in videos:
        localizations = _locs_for(v)
        if not localizations:
            print(f"  ⚠️  {v['video_id']} ({v['collection_name']}): localizations 空 — skip")
            continue

        body = {
            "id": v["video_id"],
            "localizations": localizations,
        }
        request = youtube.videos().update(part="localizations", body=body)
        try:
            request.execute()
            print(f"  ✅ {v['video_id']} ({v['collection_name']}) updated: {list(localizations.keys())}")
        except Exception as e:
            print(f"  ❌ {v['video_id']} ({v['collection_name']}) failed: {e}")
            continue
        finally:
            # quota はリクエストの成否に関わらず消費されるため、失敗時も記録する
            log_quota(
                QUOTA_SERVICE,
                "videos.update",
                VIDEOS_UPDATE_QUOTA_UNITS,
                metadata={"video_id": v["video_id"], "part": "localizations"},
            )

        # quota 急上昇防止（plan アンチパターン #8）
        time.sleep(SLEEP_SEC_PER_VIDEO)

    print("✅ done")


if __name__ == "__main__":
    main()
