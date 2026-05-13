#!/usr/bin/env python3
"""Bulk Update Short Localizations — 既存 Shorts 動画の多言語メタデータ一括更新.

`localizations.json` の `short_title_template` / `short_description_template` を使い、
YouTube 上の既存 Shorts 動画の localizations を一括更新する。
ロジックは BAHMetadataGenerator.generate_shorts_metadata と共有する。

Usage:
    uv run yt-shorts-bulk-update-loc            # 反映実行
    uv run yt-shorts-bulk-update-loc --dry-run  # プレビューのみ
"""

import argparse
import json
import sys
import time
from pathlib import Path

from googleapiclient.errors import HttpError

from youtube_automation.utils.config import channel_dir, load_config
from youtube_automation.utils.exceptions import YouTubeAPIError
from youtube_automation.utils.metadata_generator import BAHMetadataGenerator
from youtube_automation.utils.youtube_service import get_youtube


def _collect_short_videos(channel_root: Path) -> list[dict]:
    """`live/` 配下の workflow-state.json から Shorts video_id を収集する."""
    live_dir = channel_root / "collections" / "live"
    if not live_dir.exists():
        return []

    videos: list[dict] = []
    for col_dir in sorted(live_dir.iterdir()):
        if not col_dir.is_dir():
            continue

        ws_path = col_dir / "workflow-state.json"
        if not ws_path.exists():
            continue

        with open(ws_path, "r", encoding="utf-8") as f:
            ws = json.load(f)

        tracking_path = col_dir / "20-documentation" / "upload_tracking.json"
        if not tracking_path.exists():
            continue

        with open(tracking_path, "r", encoding="utf-8") as f:
            tracking = json.load(f)

        collection_name = ws.get("collection_name", col_dir.name)
        cc_video_url = tracking.get("complete_collection", {}).get("video_url", "")

        short_data = ws.get("post_upload", {}).get("short", {})
        short_videos = short_data.get("videos", []) or []
        # 単一 Shorts 形式（dict）も受ける
        single_id = short_data.get("video_id")
        if single_id and not short_videos:
            short_videos = [{"video_id": single_id, "title": short_data.get("title", "")}]

        for sv in short_videos:
            vid = sv.get("video_id")
            if vid:
                videos.append(
                    {
                        "video_id": vid,
                        "title": sv.get("title", ""),
                        "collection_name": collection_name,
                        "cc_video_url": cc_video_url,
                        "collection_dir": col_dir,
                    }
                )

    return videos


def main():
    parser = argparse.ArgumentParser(description="既存 Shorts 動画の localizations 一括更新")
    parser.add_argument("--dry-run", action="store_true", help="更新内容をプレビューのみ")
    args = parser.parse_args()

    config = load_config()
    channel_root = channel_dir()

    print(f"🌐 {config.meta.channel_name} — Shorts Localizations 一括更新")
    print("=" * 60)

    videos = _collect_short_videos(channel_root)
    if not videos:
        print("❌ 更新対象の Shorts 動画が見つかりません")
        sys.exit(1)

    print(f"📋 対象 Shorts: {len(videos)} 本")

    yt = get_youtube()

    current_collection: Path | None = None
    localizations: dict = {}
    updated = 0

    for video in videos:
        col_dir = video["collection_dir"]

        if col_dir != current_collection:
            current_collection = col_dir
            generator = BAHMetadataGenerator(str(col_dir))
            generator.collection_name = video["collection_name"]
            localizations = generator._generate_shorts_localizations(video["cc_video_url"])
            print(f"\n{'─' * 50}")
            print(f"📁 {video['collection_name']} ({len(localizations)} 言語)")
            if localizations.get("ja"):
                print(f"   JA: {localizations['ja']['title']}")

        print(f"   🎬 {video['video_id']} — {video['title'][:60]}")

        if args.dry_run:
            continue

        try:
            yt.videos().update(
                part="localizations",
                body={
                    "id": video["video_id"],
                    "localizations": localizations,
                },
            ).execute()
            print("      ✅ 更新完了")
            updated += 1
            time.sleep(0.5)
        except HttpError as e:
            print(f"      ❌ 更新失敗: {YouTubeAPIError.from_http_error(e, 'videos.update')}")

    print(f"\n{'=' * 60}")
    if args.dry_run:
        print(f"🔍 プレビュー完了（{len(videos)} 本）。実行するには --dry-run を外してください。")
    else:
        print(f"✅ {updated}/{len(videos)} 本の Shorts 動画を更新しました。")


if __name__ == "__main__":
    main()
