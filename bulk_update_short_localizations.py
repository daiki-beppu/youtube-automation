#!/usr/bin/env python3
"""
Bulk Update Short Localizations — 既存ショート動画の多言語メタデータ一括更新

localizations.json の short_title_template / short_description_template を使い、
YouTube 上の既存ショート動画の localizations を一括更新する。

Usage:
    # チャンネルディレクトリから実行
    python3 ../../automation/bulk_update_short_localizations.py --dry-run
    python3 ../../automation/bulk_update_short_localizations.py
"""

import argparse
import json
import sys
import time

import utils._path_setup  # noqa: F401
from utils.channel_config import ChannelConfig  # noqa: E402
from utils.youtube_service import get_youtube  # noqa: E402


def collect_short_videos(config: ChannelConfig) -> list[dict]:
    """live コレクションから short video_id を収集"""
    channel_dir = config.channel_dir()
    live_dir = channel_dir / 'collections' / 'live'

    if not live_dir.exists():
        return []

    videos = []
    for col_dir in sorted(live_dir.iterdir()):
        if not col_dir.is_dir():
            continue

        ws_path = col_dir / 'workflow-state.json'
        if not ws_path.exists():
            continue

        with open(ws_path, 'r', encoding='utf-8') as f:
            ws = json.load(f)

        tracking_path = col_dir / '20-documentation' / 'upload_tracking.json'
        if not tracking_path.exists():
            continue

        with open(tracking_path, 'r', encoding='utf-8') as f:
            tracking = json.load(f)

        collection_name = ws.get('collection_name', col_dir.name)
        cc_video_url = tracking.get('complete_collection', {}).get('video_url', '')

        short_data = ws.get('post_upload', {}).get('short', {})
        short_videos = short_data.get('videos', [])

        for sv in short_videos:
            vid = sv.get('video_id')
            if vid:
                videos.append({
                    'video_id': vid,
                    'title': sv.get('title', ''),
                    'collection_name': collection_name,
                    'cc_video_url': cc_video_url,
                    'collection_dir': col_dir.name,
                })

    return videos


def generate_short_localizations(config: ChannelConfig, collection_name: str, cc_video_url: str) -> dict:
    """ShortUploader._generate_localizations() と同じロジック"""
    localizations = {}
    loc_config = config.localizations_config
    channel_name = config.channel_name
    tagline_default = config.tagline

    for lang in loc_config.get('supported_languages', []):
        lang_data = loc_config.get('languages', {}).get(lang, {})

        short_title_tpl = lang_data.get('short_title_template')
        if not short_title_tpl:
            continue

        loc_title = short_title_tpl.format(
            theme=collection_name,
            channel_name=channel_name,
        )[:100]

        short_desc_tpl = lang_data.get('short_description_template')
        tagline = lang_data.get('description', {}).get('tagline', tagline_default)

        if short_desc_tpl:
            loc_desc = short_desc_tpl.format(
                collection_name=collection_name,
                channel_name=channel_name,
                cc_video_url=cc_video_url,
                tagline=tagline,
            )[:5000]
        else:
            loc_desc = '\n'.join([
                f"{collection_name} | {channel_name}",
                "",
                f"♫ → {cc_video_url}",
                "",
                tagline,
            ])[:5000]

        localizations[lang] = {
            'title': loc_title,
            'description': loc_desc,
        }

    return localizations


def main():
    parser = argparse.ArgumentParser(description='既存ショート動画の localizations 一括更新')
    parser.add_argument('--dry-run', action='store_true', help='更新内容をプレビューのみ')
    args = parser.parse_args()

    config = ChannelConfig.load()
    print(f"🌐 {config.channel_name} — Short Localizations 一括更新")
    print("=" * 60)

    videos = collect_short_videos(config)
    if not videos:
        print("❌ 更新対象のショート動画が見つかりません")
        sys.exit(1)

    print(f"📋 対象ショート: {len(videos)} 本")

    yt = get_youtube()

    # コレクション別にグループ化してプレビュー
    current_collection = None
    updated = 0

    for video in videos:
        vid = video['video_id']
        col_dir = video['collection_dir']

        if col_dir != current_collection:
            current_collection = col_dir
            localizations = generate_short_localizations(
                config, video['collection_name'], video['cc_video_url']
            )
            lang_count = len(localizations)
            print(f"\n{'─' * 50}")
            print(f"📁 {video['collection_name']} ({lang_count} 言語)")
            if localizations.get('ja'):
                print(f"   JA: {localizations['ja']['title']}")

        print(f"   🎬 {vid} — {video['title'][:60]}")

        if args.dry_run:
            continue

        try:
            yt.videos().update(
                part='localizations',
                body={
                    'id': vid,
                    'localizations': localizations,
                }
            ).execute()
            print("      ✅ 更新完了")
            updated += 1
            time.sleep(0.5)
        except Exception as e:
            print(f"      ❌ 更新失敗: {e}")

    print(f"\n{'=' * 60}")
    if args.dry_run:
        print(f"🔍 プレビュー完了（{len(videos)} 本）。実行するには --dry-run を外してください。")
    else:
        print(f"✅ {updated}/{len(videos)} 本のショート動画を更新しました。")


if __name__ == '__main__':
    main()
