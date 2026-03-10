#!/usr/bin/env python3
"""
Post-Upload Actions — 公開後エンゲージメント自動化

YouTube 動画公開後のアクションを実行:
- コメント投稿（固定は YouTube Studio で手動）
- 過去動画の概要欄にクロスリンク追加
- コミュニティ投稿ドラフト生成

Usage:
    python3 automation/post_upload_actions.py comment VIDEO_ID --theme study
    python3 automation/post_upload_actions.py cross-link VIDEO_ID --title "New Collection"
    python3 automation/post_upload_actions.py cross-link-remove VIDEO_ID
    python3 automation/post_upload_actions.py community-draft COLLECTION_PATH
"""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

from auth.oauth_handler import YouTubeOAuthHandler  # noqa: E402
from utils.channel_config import ChannelConfig  # noqa: E402

logger = logging.getLogger(__name__)

CROSS_LINK_MARKER_START = "\n\n━━━ 🆕 New Release ━━━"
CROSS_LINK_MARKER_END = "━━━━━━━━━━━━━━━━━━━━━"


class PostUploadActions:
    """公開後アクション実行クラス"""

    def __init__(self):
        self.config = ChannelConfig.load()
        self._youtube = None

    def _get_youtube(self):
        if self._youtube is None:
            handler = YouTubeOAuthHandler()
            self._youtube = handler.get_youtube_service()
        return self._youtube

    # ─── コメント投稿 ─────────────────────────────────

    def post_comment(self, video_id: str, comment_text: str = None, theme: str = None) -> dict:
        """動画にコメントを投稿（固定は YouTube Studio で手動）

        Args:
            video_id: YouTube 動画 ID
            comment_text: 投稿するコメントテキスト（推奨: 固有のコメントを毎回作成）
            theme: テーマキーワード（comment_text 省略時のフォールバック用）

        Returns:
            dict: {"comment_id": str, "text": str}
        """
        youtube = self._get_youtube()

        if not comment_text:
            comment_text = "What scene do you see while listening? Share your vision below"

        logger.info(f"💬 コメント投稿: {video_id}")
        logger.info(f"📝 テキスト: {comment_text}")

        body = {
            "snippet": {
                "videoId": video_id,
                "topLevelComment": {
                    "snippet": {
                        "textOriginal": comment_text
                    }
                }
            }
        }

        response = youtube.commentThreads().insert(
            part="snippet",
            body=body
        ).execute()

        comment_id = response["snippet"]["topLevelComment"]["id"]
        logger.info(f"✅ コメント投稿完了: {comment_id}")
        logger.info("⚠️  固定は YouTube Studio で手動で行ってください:")
        logger.info(f"   https://studio.youtube.com/video/{video_id}/comments")

        return {"comment_id": comment_id, "text": comment_text}

    # ─── クロスリンク ─────────────────────────────────

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

    # ─── コミュニティ投稿ドラフト ────────────────────────

    def generate_community_draft(self, collection_path: str) -> str:
        """コミュニティ投稿のドラフトテキストを生成

        Args:
            collection_path: コレクションのパス

        Returns:
            str: コミュニティ投稿テキスト
        """
        col_path = Path(collection_path)

        # workflow-state.json からテーマ情報を取得
        ws_path = col_path / "workflow-state.json"
        collection_name = col_path.name
        if ws_path.exists():
            with open(ws_path, "r", encoding="utf-8") as f:
                ws = json.load(f)
            collection_name = ws.get("collection_name", collection_name)

        # upload_tracking.json から動画 URL を取得
        tracking_path = col_path / "20-documentation" / "upload_tracking.json"
        video_url = ""
        if tracking_path.exists():
            with open(tracking_path, "r", encoding="utf-8") as f:
                tracking = json.load(f)
            cc = tracking.get("complete_collection", {})
            video_url = cc.get("video_url", "")

        # ドラフト生成
        tagline = self.config.raw.get("channel", {}).get("tagline", "")
        hashtags = " ".join(self.config.raw.get("descriptions", {}).get("hashtags", []))

        draft = f"""🎵 New Release: {collection_name}

{tagline}

This collection draws from the rich tapestry of Celtic mythology and folklore. \
Let the music transport you to ancient lands where legends come alive.

▶ Listen now: {video_url}

What scene does this music paint in your mind? Tell us below!

{hashtags} #NewRelease"""

        logger.info("📝 コミュニティ投稿ドラフト生成完了")
        logger.info("⚠️  YouTube Studio のコミュニティタブに手動で投稿してください:")
        logger.info("   https://studio.youtube.com/channel/community")

        return draft

    # ─── コメント一覧取得 ─────────────────────────────

    def list_comments(self, video_id: str, max_results: int = 20) -> list[dict]:
        """動画のコメントを取得

        Args:
            video_id: 動画 ID
            max_results: 取得件数

        Returns:
            list[dict]: コメントリスト [{author, text, likes, published_at}]
        """
        youtube = self._get_youtube()

        response = youtube.commentThreads().list(
            videoId=video_id,
            part="snippet",
            order="relevance",
            maxResults=max_results
        ).execute()

        comments = []
        for item in response.get("items", []):
            snippet = item["snippet"]["topLevelComment"]["snippet"]
            comments.append({
                "author": snippet["authorDisplayName"],
                "text": snippet["textOriginal"],
                "likes": snippet["likeCount"],
                "published_at": snippet["publishedAt"],
                "comment_id": item["snippet"]["topLevelComment"]["id"],
            })

        return comments


def main():
    """CLI エントリーポイント"""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    config = ChannelConfig.load()
    parser = argparse.ArgumentParser(description=f"{config.channel_short} Post-Upload Actions")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # comment コマンド
    p_comment = subparsers.add_parser("comment", help="動画にコメントを投稿")
    p_comment.add_argument("video_id", help="YouTube 動画 ID")
    p_comment.add_argument("--text", default=None, help="コメントテキスト（固有のコメントを推奨）")
    p_comment.add_argument("--theme", default=None, help="テーマキーワード（フォールバック用）")

    # cross-link コマンド
    p_cross = subparsers.add_parser("cross-link", help="過去動画にクロスリンク追加")
    p_cross.add_argument("video_id", help="新作の動画 ID")
    p_cross.add_argument("--title", required=True, help="新作のタイトル")
    p_cross.add_argument("--max-videos", type=int, default=None, help="更新する動画数")

    # cross-link-remove コマンド
    p_remove = subparsers.add_parser("cross-link-remove", help="クロスリンクを削除")
    p_remove.add_argument("video_ids", nargs="*", help="対象動画 ID（省略で全動画）")

    # community-draft コマンド
    p_community = subparsers.add_parser("community-draft", help="コミュニティ投稿ドラフト生成")
    p_community.add_argument("collection_path", help="コレクションのパス")

    # comments コマンド
    p_list = subparsers.add_parser("comments", help="コメント一覧取得")
    p_list.add_argument("video_id", help="YouTube 動画 ID")
    p_list.add_argument("--max", type=int, default=20, help="取得件数")

    args = parser.parse_args()

    actions = PostUploadActions()

    if args.command == "comment":
        result = actions.post_comment(args.video_id, comment_text=args.text, theme=args.theme)
        print(f"\n✅ コメント投稿完了: {result['comment_id']}")
        print(f"📝 {result['text']}")
        print("\n⚠️  固定は YouTube Studio で:")
        print(f"   https://studio.youtube.com/video/{args.video_id}/comments")

    elif args.command == "cross-link":
        updated = actions.add_cross_link(args.video_id, args.title, max_videos=args.max_videos)
        print(f"\n✅ {len(updated)} 本の動画にクロスリンクを追加")

    elif args.command == "cross-link-remove":
        video_ids = args.video_ids if args.video_ids else None
        updated = actions.remove_cross_links(video_ids)
        print(f"\n✅ {len(updated)} 本の動画からクロスリンクを削除")

    elif args.command == "community-draft":
        draft = actions.generate_community_draft(args.collection_path)
        print("\n" + "=" * 60)
        print("📝 コミュニティ投稿ドラフト")
        print("=" * 60)
        print(draft)
        print("=" * 60)
        print("\n⚠️  YouTube Studio のコミュニティタブに手動で投稿してください")

    elif args.command == "comments":
        comments = actions.list_comments(args.video_id, max_results=args.max)
        for i, c in enumerate(comments, 1):
            print(f"\n{i}. {c['author']} (♥ {c['likes']})")
            print(f"   {c['text'][:100]}")


if __name__ == "__main__":
    main()
