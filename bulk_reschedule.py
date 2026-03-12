#!/usr/bin/env python3
"""
Bulk Reschedule — スケジュール済み動画の公開時刻を一括変更

チャンネル上の private（スケジュール公開待ち）動画の publishAt を変更する。
ショート（5分未満）のみ、またはロング（5分以上）のみにフィルタ可能。

Usage:
    # チャンネルディレクトリから実行
    python3 ../../automation/bulk_reschedule.py --shorts-only --new-time 17:00 --dry-run
    python3 ../../automation/bulk_reschedule.py --shorts-only --new-time 17:00
    python3 ../../automation/bulk_reschedule.py --longs-only --new-time 08:00
"""

import argparse
import re
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import utils._path_setup  # noqa: F401
from utils.channel_config import ChannelConfig  # noqa: E402
from utils.youtube_service import get_youtube  # noqa: E402


def parse_iso8601_duration(duration: str) -> int:
    """ISO 8601 duration を秒数に変換"""
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration)
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def is_short(duration_iso: str) -> bool:
    return parse_iso8601_duration(duration_iso) < 300


def fetch_scheduled_videos(youtube, channel_id: str) -> list[dict]:
    """チャンネルのスケジュール済み（private + publishAt あり）動画を取得"""
    videos = []
    # uploads playlist ID = UC... → UU...
    uploads_id = "UU" + channel_id[2:]

    next_page = None
    while True:
        resp = youtube.playlistItems().list(
            playlistId=uploads_id,
            part="snippet",
            maxResults=50,
            pageToken=next_page,
        ).execute()

        video_ids = [item["snippet"]["resourceId"]["videoId"] for item in resp.get("items", [])]
        if not video_ids:
            break

        # 動画の詳細を取得（status + contentDetails）
        detail_resp = youtube.videos().list(
            id=",".join(video_ids),
            part="status,contentDetails,snippet",
        ).execute()

        for v in detail_resp.get("items", []):
            status = v.get("status", {})
            if status.get("privacyStatus") == "private" and status.get("publishAt"):
                videos.append({
                    "id": v["id"],
                    "title": v["snippet"]["title"],
                    "duration_iso": v["contentDetails"]["duration"],
                    "publish_at": status["publishAt"],
                    "privacy": status["privacyStatus"],
                })

        next_page = resp.get("nextPageToken")
        if not next_page:
            break
        time.sleep(0.3)

    return videos


def reschedule_video(youtube, video_id: str, new_publish_at: str, dry_run: bool) -> bool:
    """動画の publishAt を変更"""
    if dry_run:
        return True
    try:
        youtube.videos().update(
            part="status",
            body={
                "id": video_id,
                "status": {
                    "privacyStatus": "private",
                    "publishAt": new_publish_at,
                },
            },
        ).execute()
        return True
    except Exception as e:
        print(f"  ❌ エラー: {e}")
        return False


def calculate_new_publish_at(old_publish_at: str, new_time: str, tz: ZoneInfo) -> str:
    """既存の publishAt の日付を維持しつつ、時刻だけ new_time に変更"""
    old_dt = datetime.fromisoformat(old_publish_at.replace("Z", "+00:00"))
    old_local = old_dt.astimezone(tz)
    hour, minute = map(int, new_time.split(":"))
    new_local = old_local.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # 時刻変更で過去になる場合は翌日にスライド
    if new_local <= datetime.now(tz):
        new_local += timedelta(days=1)

    return new_local.isoformat()


def main():
    parser = argparse.ArgumentParser(description="スケジュール済み動画の公開時刻を一括変更")
    parser.add_argument("--new-time", required=True, help="新しい公開時刻 (HH:MM、例: 17:00)")
    parser.add_argument("--shorts-only", action="store_true", help="ショート（5分未満）のみ")
    parser.add_argument("--longs-only", action="store_true", help="ロング（5分以上）のみ")
    parser.add_argument("--dry-run", action="store_true", help="変更せず確認のみ")
    args = parser.parse_args()

    if args.shorts_only and args.longs_only:
        print("❌ --shorts-only と --longs-only は同時に指定できません")
        sys.exit(1)

    # 時刻バリデーション
    try:
        h, m = map(int, args.new_time.split(":"))
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError
    except (ValueError, AttributeError):
        print(f"❌ 無効な時刻: {args.new_time}（HH:MM 形式で指定）")
        sys.exit(1)

    config = ChannelConfig.load()
    channel_id = config._data['channel']['channel_id']
    tz = ZoneInfo("Asia/Tokyo")

    print(f"{'🔍 [DRY RUN] ' if args.dry_run else ''}スケジュール変更開始")
    print(f"  チャンネル: {config.channel_name} ({channel_id})")
    print(f"  新時刻: {args.new_time} JST")
    filter_label = "ショートのみ" if args.shorts_only else "ロングのみ" if args.longs_only else "全動画"
    print(f"  フィルタ: {filter_label}")
    print()

    youtube = get_youtube()

    # スケジュール済み動画を取得
    print("📡 スケジュール済み動画を取得中...")
    videos = fetch_scheduled_videos(youtube, channel_id)
    print(f"  → {len(videos)} 件のスケジュール済み動画")

    # フィルタ適用
    if args.shorts_only:
        videos = [v for v in videos if is_short(v["duration_iso"])]
    elif args.longs_only:
        videos = [v for v in videos if not is_short(v["duration_iso"])]

    if not videos:
        print("✅ 対象動画なし")
        return

    print(f"  → フィルタ後: {len(videos)} 件")
    print()

    # 変更プレビュー + 実行
    success = 0
    for v in videos:
        old_dt = datetime.fromisoformat(v["publish_at"].replace("Z", "+00:00")).astimezone(tz)
        new_publish_at = calculate_new_publish_at(v["publish_at"], args.new_time, tz)
        new_dt = datetime.fromisoformat(new_publish_at)

        short_label = "🎬 Short" if is_short(v["duration_iso"]) else "📺 Long"
        print(f"  {short_label} {v['title'][:50]}")
        print(f"    {old_dt.strftime('%Y-%m-%d %H:%M')} → {new_dt.strftime('%Y-%m-%d %H:%M')} JST")

        if reschedule_video(youtube, v["id"], new_publish_at, args.dry_run):
            success += 1
        time.sleep(0.5)

    print()
    action = "確認" if args.dry_run else "変更"
    print(f"✅ {success}/{len(videos)} 件 {action}完了")
    if args.dry_run:
        print("💡 実行するには --dry-run を外してください")


if __name__ == "__main__":
    main()
