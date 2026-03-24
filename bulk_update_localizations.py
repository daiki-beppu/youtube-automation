#!/usr/bin/env python3
"""
Bulk Update Localizations — 既存動画の多言語メタデータ一括更新

localizations.json のテンプレートが更新された際に、
YouTube 上の既存動画の localizations を最新形式に一括更新する。

Usage:
    # チャンネルディレクトリから実行
    python3 ../../automation/bulk_update_localizations.py --dry-run
    python3 ../../automation/bulk_update_localizations.py
"""

import argparse
import json
import re
import sys
import time

import utils._path_setup  # noqa: F401
from utils.channel_config import ChannelConfig  # noqa: E402
from utils.metadata_generator import BAHMetadataGenerator  # noqa: E402
from utils.youtube_service import get_youtube  # noqa: E402


def parse_iso8601_duration(duration: str) -> int:
    """ISO 8601 duration を秒数に変換（例: PT1H28M27S → 5307）"""
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration)
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def extract_body_for_localizations(description: str) -> str | None:
    """キュレーション済み概要欄から本文部分（フッター前）を抽出"""
    for marker in ['Perfect for:', '🎮 Perfect for', '─────', '📝 Usage', 'Usage & Attribution']:
        idx = description.find(marker)
        if idx > 0:
            return description[:idx].rstrip()
    return None


def extract_md_section(text: str, heading: str) -> str | None:
    """Markdown の ## heading 直後のコードフェンス内容を抽出"""
    pattern = rf'## {re.escape(heading)}\s*\n+```\n(.*?)```'
    m = re.search(pattern, text, re.DOTALL)
    return m.group(1).strip() if m else None


def collect_live_videos(config: ChannelConfig) -> list[dict]:
    """live コレクションから video_id と collection_path を収集"""
    channel_dir = config.channel_dir()
    live_dir = channel_dir / 'collections' / 'live'

    if not live_dir.exists():
        return []

    videos = []
    for col_dir in sorted(live_dir.iterdir()):
        if not col_dir.is_dir():
            continue

        tracking_path = col_dir / '20-documentation' / 'upload_tracking.json'
        if not tracking_path.exists():
            continue

        with open(tracking_path, 'r', encoding='utf-8') as f:
            tracking = json.load(f)

        cc = tracking.get('complete_collection', {})
        video_id = cc.get('video_id')
        if video_id:
            videos.append({
                'video_id': video_id,
                'collection_path': col_dir,
            })

    return videos


def main():
    parser = argparse.ArgumentParser(description='既存動画の localizations 一括更新')
    parser.add_argument('--dry-run', action='store_true', help='更新内容をプレビューのみ')
    args = parser.parse_args()

    config = ChannelConfig.load()
    print(f"🌐 {config.channel_name} — Localizations 一括更新")
    print("=" * 60)

    # 1. live コレクションから対象動画を収集
    videos = collect_live_videos(config)
    if not videos:
        print("❌ 更新対象の動画が見つかりません")
        sys.exit(1)

    print(f"📋 対象動画: {len(videos)} 本")

    # 2. YouTube API で duration を取得
    video_ids = [v['video_id'] for v in videos]

    # duration 取得（dry-run でもタイトルプレビューのために取得）
    yt = get_youtube()

    # 50件ずつバッチ取得（API 制限）
    duration_map = {}
    for i in range(0, len(video_ids), 50):
        batch_ids = video_ids[i:i + 50]
        response = yt.videos().list(
            id=','.join(batch_ids),
            part='contentDetails'
        ).execute()
        for item in response.get('items', []):
            vid = item['id']
            iso_dur = item['contentDetails']['duration']
            duration_map[vid] = parse_iso8601_duration(iso_dur)

    # 3. 各動画の localizations を生成・更新
    updated = 0
    for video in videos:
        vid = video['video_id']
        col_path = video['collection_path']
        total_seconds = duration_map.get(vid, 0)

        if total_seconds == 0:
            print(f"⚠️  スキップ（duration 取得失敗）: {vid} — {col_path.name}")
            continue

        # BAHMetadataGenerator で localizations を生成
        gen = BAHMetadataGenerator(str(col_path))

        # scene_phrases を workflow-state.json から読み込み
        scene_phrases = gen._load_scene_phrases()

        # 英語タイトルを生成
        en_title = gen._generate_title(total_seconds)

        # descriptions.md からタイムスタンプ部分を抽出
        timestamp_body = None
        desc_md_path = col_path / '20-documentation' / 'descriptions.md'
        if desc_md_path.exists():
            desc_text = desc_md_path.read_text(encoding='utf-8')
            curated_desc = extract_md_section(desc_text, 'Complete Collection 概要欄')
            if curated_desc:
                lines = curated_desc.split('\n')
                ts_lines = [line for line in lines if re.match(r'^\d{1,2}:\d{2}', line.strip())]
                if ts_lines:
                    timestamp_body = '\n'.join(ts_lines)

        # フォールバック: 自動生成タイムスタンプ
        if timestamp_body is None:
            timestamp_body = gen.format_timestamps_text()

        localizations = gen.generate_localizations(en_title, timestamp_body or '', scene_phrases)

        # プレビュー
        ja_loc = localizations.get('ja', {})
        print(f"\n{'─' * 50}")
        print(f"🎬 {vid} — {col_path.name}")
        print(f"   EN: {en_title}")
        print(f"   JA: {ja_loc.get('title', 'N/A')}")
        print(f"   JA desc: {ja_loc.get('description', '')[:100]}...")

        if args.dry_run:
            continue

        # YouTube API で localizations を更新
        try:
            yt.videos().update(
                part='localizations',
                body={
                    'id': vid,
                    'localizations': localizations,
                }
            ).execute()
            print("   ✅ 更新完了")
            updated += 1
            time.sleep(0.5)  # API レート制限対策
        except Exception as e:
            print(f"   ❌ 更新失敗: {e}")

    print(f"\n{'=' * 60}")
    if args.dry_run:
        print(f"🔍 プレビュー完了（{len(videos)} 本）。実行するには --dry-run を外してください。")
    else:
        print(f"✅ {updated}/{len(videos)} 本の動画を更新しました。")


if __name__ == '__main__':
    main()
