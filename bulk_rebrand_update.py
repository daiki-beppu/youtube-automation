#!/usr/bin/env python3
"""
Bulk Rebrand Update — AEEJ リブランディング一括更新

既存13本の動画のタイトル・概要欄・サムネイル・タグを
CLM → AEEJ ブランドに一括更新する。

Usage:
    # チャンネルディレクトリから実行
    python3 ../../automation/bulk_rebrand_update.py --dry-run
    python3 ../../automation/bulk_rebrand_update.py
    python3 ../../automation/bulk_rebrand_update.py --title-only
    python3 ../../automation/bulk_rebrand_update.py --thumbnail-only
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

import utils._path_setup  # noqa: F401
from utils.channel_config import ChannelConfig  # noqa: E402
from utils.upload_core import YouTubeUploadCore  # noqa: E402
from utils.youtube_service import get_youtube  # noqa: E402

# ── タイトルマッピング（設計書 Section 5） ──────────────────────
# key: コレクションディレクトリ名のキーワード部分
# value: (new_title_theme, activity)
TITLE_MAP = {
    "merlin-study": ("Quiet Study", "Study"),
    "fairy-forest": ("Midnight Wandering", "Deep Focus"),
    "bards-inn": ("Restful Evening", "Relaxation"),
    "healer-cottage": ("Gentle Remedy", "Relaxation"),
    "rain-scriptorium": ("Rainy Scriptorium", "Study"),
    "illuminated-page": ("Ancient Pages", "Reading"),
    "rain-against-glass": ("Rainy Solitude", "Deep Focus"),
    "brigid-hearth": ("Warm Hearth", "Relaxation"),
    "changeling-lullaby": ("Distant Lullaby", "Sleep"),
    "joans-garden-prayer": ("Garden Prayer", "Meditation"),
    "rapunzels-tower": ("Tower Reverie", "Deep Focus"),
    "titanias-midsummer": ("Midsummer Rest", "Relaxation"),
    "penelopes-vigil": ("Seaside Vigil", "Deep Focus"),
}

# ── テキスト置換ルール ──────────────────────────────────────────
TEXT_REPLACEMENTS = [
    ("Celtic Lore Music", "An Eternal Elven Journey"),
    ("celtic lore music", "An Eternal Elven Journey"),
    ("Subscribe for new fantasy celtic music!", "Subscribe for new elven journeys every week!"),
    ("🎵 Subscribe for new fantasy celtic music!", "🎵 Subscribe for new elven journeys every week!"),
]

TAG_REPLACEMENTS = {
    "celtic lore": "elven journey",
}
TAG_ADDITIONS = ["An Eternal Elven Journey"]


def extract_description(descriptions_md: Path) -> str | None:
    """descriptions.md から Complete Collection 概要欄を抽出"""
    if not descriptions_md.exists():
        return None

    text = descriptions_md.read_text(encoding="utf-8")
    # ## Complete Collection 概要欄 の直後のコードフェンス内容
    pattern = r"## Complete Collection 概要欄\s*\n+```\n(.*?)```"
    m = re.search(pattern, text, re.DOTALL)
    return m.group(1).strip() if m else None


def rebrand_description(desc: str) -> str:
    """概要欄テキストの CLM → AEEJ 置換"""
    for old, new in TEXT_REPLACEMENTS:
        desc = desc.replace(old, new)
    return desc


def rebrand_tags(tags: list[str]) -> list[str]:
    """タグの CLM → AEEJ 置換"""
    new_tags = []
    for tag in tags:
        replaced = TAG_REPLACEMENTS.get(tag.lower(), tag)
        new_tags.append(replaced)
    for addition in TAG_ADDITIONS:
        if addition.lower() not in [t.lower() for t in new_tags]:
            new_tags.append(addition)
    return new_tags


def match_collection(dir_name: str) -> tuple[str, str] | None:
    """ディレクトリ名から TITLE_MAP のキーをマッチ"""
    for key, value in TITLE_MAP.items():
        if key in dir_name:
            return value
    return None


def build_new_title(theme: str, activity: str) -> str:
    """新タイトルを構築"""
    return f"The Elf's {theme} | An Eternal Elven Journey for {activity}"


def collect_videos(config: ChannelConfig) -> list[dict]:
    """live コレクションから更新対象を収集"""
    channel_dir = config.channel_dir()
    live_dir = channel_dir / "collections" / "live"

    if not live_dir.exists():
        return []

    videos = []
    for col_dir in sorted(live_dir.iterdir()):
        if not col_dir.is_dir():
            continue

        # video_id を upload_tracking.json から取得
        tracking_path = col_dir / "20-documentation" / "upload_tracking.json"
        if not tracking_path.exists():
            continue

        with open(tracking_path, "r", encoding="utf-8") as f:
            tracking = json.load(f)

        video_id = tracking.get("complete_collection", {}).get("video_id")
        if not video_id:
            continue

        # タイトルマッピング
        title_info = match_collection(col_dir.name)
        if not title_info:
            print(f"⚠️  タイトルマッピングなし: {col_dir.name}")
            continue

        theme, activity = title_info
        new_title = build_new_title(theme, activity)

        # 概要欄
        desc_path = col_dir / "20-documentation" / "descriptions.md"
        description = extract_description(desc_path)

        # サムネイル
        thumbnail_path = col_dir / "10-assets" / "thumbnail.jpg"

        videos.append({
            "video_id": video_id,
            "collection_dir": col_dir,
            "new_title": new_title,
            "description": description,
            "thumbnail_path": thumbnail_path if thumbnail_path.exists() else None,
        })

    return videos


def main():
    parser = argparse.ArgumentParser(description="AEEJ リブランディング一括更新")
    parser.add_argument("--dry-run", action="store_true", help="更新内容をプレビューのみ")
    parser.add_argument("--title-only", action="store_true", help="タイトルのみ更新")
    parser.add_argument("--thumbnail-only", action="store_true", help="サムネイルのみ更新")
    args = parser.parse_args()

    config = ChannelConfig.load()
    print(f"🔄 {config.channel_name} — リブランディング一括更新")
    print("=" * 60)

    videos = collect_videos(config)
    if not videos:
        print("❌ 更新対象の動画が見つかりません")
        sys.exit(1)

    print(f"📋 対象動画: {len(videos)} 本\n")

    # YouTube API 接続
    yt = get_youtube()
    uploader = YouTubeUploadCore()

    # 現在の snippet を取得（更新に必要）
    video_ids = [v["video_id"] for v in videos]
    current_snippets = {}
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i : i + 50]
        response = yt.videos().list(
            id=",".join(batch), part="snippet"
        ).execute()
        for item in response.get("items", []):
            current_snippets[item["id"]] = item["snippet"]

    updated = 0
    for video in videos:
        vid = video["video_id"]
        col_name = video["collection_dir"].name
        new_title = video["new_title"]

        current = current_snippets.get(vid)
        if not current:
            print(f"❌ YouTube 上に見つからない: {vid} ({col_name})")
            continue

        old_title = current.get("title", "")

        print(f"{'─' * 55}")
        print(f"📁 {col_name}")
        print(f"🎬 {vid}")
        print(f"   旧: {old_title}")
        print(f"   新: {new_title}")

        if args.dry_run:
            if video["description"]:
                rebranded_desc = rebrand_description(video["description"])
                # 最初の80文字をプレビュー
                preview = rebranded_desc[:80].replace("\n", " ")
                print(f"   概要欄: {preview}...")
            if video["thumbnail_path"]:
                print(f"   サムネ: {video['thumbnail_path'].name} ✓")
            continue

        # ── 更新実行 ──────────────────────────────────────────

        try:
            if not args.thumbnail_only:
                # snippet 更新（タイトル + 概要欄 + タグ）
                snippet_update = {
                    "title": new_title,
                    "categoryId": current.get("categoryId", "10"),
                }

                if not args.title_only and video["description"]:
                    snippet_update["description"] = rebrand_description(video["description"])

                # タグ更新
                old_tags = current.get("tags", [])
                if old_tags:
                    snippet_update["tags"] = rebrand_tags(old_tags)

                yt.videos().update(
                    part="snippet",
                    body={
                        "id": vid,
                        "snippet": snippet_update,
                    },
                ).execute()
                print(f"   ✅ snippet 更新完了")
                time.sleep(0.5)

            if not args.title_only and video["thumbnail_path"]:
                uploader.set_thumbnail(vid, str(video["thumbnail_path"]))
                print(f"   ✅ サムネイル更新完了")
                time.sleep(0.5)

            updated += 1

        except Exception as e:
            print(f"   ❌ 更新失敗: {e}")

    print(f"\n{'=' * 60}")
    if args.dry_run:
        print(f"🔍 プレビュー完了（{len(videos)} 本）。実行するには --dry-run を外してください。")
    else:
        print(f"✅ {updated}/{len(videos)} 本の動画を更新しました。")


if __name__ == "__main__":
    main()
