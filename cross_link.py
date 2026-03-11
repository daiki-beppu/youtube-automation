#!/usr/bin/env python3
"""クロスリンク管理

過去動画の概要欄に新作リンクを追加・削除する。

Usage:
    python3 automation/cross_link.py add VIDEO_ID --title "New Collection" [--max-videos N]
    python3 automation/cross_link.py remove [VIDEO_IDS...]
"""

import argparse
import logging

import utils._path_setup  # noqa: F401
from utils.channel_config import ChannelConfig  # noqa: E402
from utils.youtube_service import get_youtube  # noqa: E402

logger = logging.getLogger(__name__)

CROSS_LINK_MARKER_START = "\n\n━━━ 🆕 New Release ━━━"
CROSS_LINK_MARKER_END = "━━━━━━━━━━━━━━━━━━━━━"


class CrossLinkManager:
    """クロスリンク管理クラス"""

    def __init__(self):
        self.config = ChannelConfig.load()
        self._youtube = None

    def _get_youtube(self):
        if self._youtube is None:
            self._youtube = get_youtube()
        return self._youtube

    def add_cross_link(self, new_video_id: str, new_title: str, max_videos: int = None) -> list[str]:
        """過去の人気動画の概要欄に新作リンクを追加

        Args:
            new_video_id: 新作の動画 ID
            new_title: 新作のタイトル
            max_videos: 更新する動画数（デフォルト: config の cross_link_max_videos）

        Returns:
            list[str]: 更新した動画 ID のリスト
        """
        youtube = self._get_youtube()

        if max_videos is None:
            max_videos = self.config.raw.get("post_upload", {}).get("cross_link_max_videos", 3)

        # チャンネルの動画を再生回数順で取得
        top_videos = self._get_top_videos(exclude_id=new_video_id, limit=max_videos)
        if not top_videos:
            logger.warning("⚠️  クロスリンク対象の動画が見つかりません")
            return []

        new_video_url = f"https://www.youtube.com/watch?v={new_video_id}"
        cross_link_block = (
            f"{CROSS_LINK_MARKER_START}\n"
            f"▶ {new_title}\n"
            f"   {new_video_url}\n"
            f"{CROSS_LINK_MARKER_END}"
        )

        updated_ids = []
        for video in top_videos:
            vid = video["id"]
            current_desc = video["snippet"]["description"]

            # 既存のクロスリンクを削除してから追加
            clean_desc = self._remove_cross_link_block(current_desc)
            new_desc = clean_desc + cross_link_block

            if len(new_desc) > 5000:
                logger.warning(f"⚠️  概要欄が長すぎるためスキップ: {vid}")
                continue

            youtube.videos().update(
                part="snippet",
                body={
                    "id": vid,
                    "snippet": {
                        "title": video["snippet"]["title"],
                        "description": new_desc,
                        "categoryId": video["snippet"].get("categoryId", "10"),
                    }
                }
            ).execute()

            logger.info(f"✅ クロスリンク追加: {vid} ({video['snippet']['title'][:40]}...)")
            updated_ids.append(vid)

        logger.info(f"📊 合計 {len(updated_ids)} 本の動画を更新")
        return updated_ids

    def remove_cross_links(self, video_ids: list[str] = None) -> list[str]:
        """過去動画からクロスリンクブロックを削除

        Args:
            video_ids: 対象動画 ID リスト。None の場合は全動画を対象

        Returns:
            list[str]: 更新した動画 ID のリスト
        """
        youtube = self._get_youtube()

        if video_ids is None:
            videos = self._get_top_videos(limit=50)
        else:
            response = youtube.videos().list(
                id=",".join(video_ids),
                part="snippet"
            ).execute()
            videos = response.get("items", [])

        updated_ids = []
        for video in videos:
            vid = video["id"]
            current_desc = video["snippet"]["description"]

            if CROSS_LINK_MARKER_START not in current_desc:
                continue

            clean_desc = self._remove_cross_link_block(current_desc)

            youtube.videos().update(
                part="snippet",
                body={
                    "id": vid,
                    "snippet": {
                        "title": video["snippet"]["title"],
                        "description": clean_desc,
                        "categoryId": video["snippet"].get("categoryId", "10"),
                    }
                }
            ).execute()

            logger.info(f"✅ クロスリンク削除: {vid}")
            updated_ids.append(vid)

        return updated_ids

    def _get_top_videos(self, exclude_id: str = None, limit: int = 3) -> list[dict]:
        """再生回数の多い動画を取得"""
        youtube = self._get_youtube()
        channel_id = self.config.raw["channel"]["channel_id"]

        # チャンネルの動画を検索
        search_response = youtube.search().list(
            channelId=channel_id,
            type="video",
            order="viewCount",
            maxResults=limit + 5,  # 除外分の余裕
            part="id"
        ).execute()

        video_ids = [
            item["id"]["videoId"]
            for item in search_response.get("items", [])
            if item["id"]["videoId"] != exclude_id
        ][:limit]

        if not video_ids:
            return []

        # 詳細情報を取得
        videos_response = youtube.videos().list(
            id=",".join(video_ids),
            part="snippet,statistics"
        ).execute()

        return videos_response.get("items", [])

    def _remove_cross_link_block(self, description: str) -> str:
        """概要欄からクロスリンクブロックを削除"""
        start_idx = description.find(CROSS_LINK_MARKER_START)
        if start_idx == -1:
            return description

        end_idx = description.find(CROSS_LINK_MARKER_END, start_idx)
        if end_idx == -1:
            return description[:start_idx].rstrip()

        return description[:start_idx].rstrip() + description[end_idx + len(CROSS_LINK_MARKER_END):]


def main():
    """CLI エントリーポイント"""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="YouTube クロスリンク管理")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # add コマンド
    p_add = subparsers.add_parser("add", help="過去動画にクロスリンク追加")
    p_add.add_argument("video_id", help="新作の動画 ID")
    p_add.add_argument("--title", required=True, help="新作のタイトル")
    p_add.add_argument("--max-videos", type=int, default=None, help="更新する動画数")

    # remove コマンド
    p_remove = subparsers.add_parser("remove", help="クロスリンクを削除")
    p_remove.add_argument("video_ids", nargs="*", help="対象動画 ID（省略で全動画）")

    args = parser.parse_args()

    manager = CrossLinkManager()

    if args.command == "add":
        updated = manager.add_cross_link(args.video_id, args.title, max_videos=args.max_videos)
        print(f"\n✅ {len(updated)} 本の動画にクロスリンクを追加")

    elif args.command == "remove":
        video_ids = args.video_ids if args.video_ids else None
        updated = manager.remove_cross_links(video_ids)
        print(f"\n✅ {len(updated)} 本の動画からクロスリンクを削除")


if __name__ == "__main__":
    main()
