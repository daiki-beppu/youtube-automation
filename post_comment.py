#!/usr/bin/env python3
"""コメント投稿・一覧取得

YouTube 動画へのコメント投稿と既存コメントの一覧取得を行う。

Usage:
    python3 automation/post_comment.py VIDEO_ID [--text TEXT] [--theme THEME]
    python3 automation/post_comment.py list VIDEO_ID [--max N]
"""

import argparse
import logging

import utils._path_setup  # noqa: F401
from utils.youtube_service import get_youtube  # noqa: E402

logger = logging.getLogger(__name__)


class CommentPoster:
    """コメント投稿・一覧取得クラス"""

    def __init__(self):
        self._youtube = None

    def _get_youtube(self):
        if self._youtube is None:
            self._youtube = get_youtube()
        return self._youtube

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

    def list_comments(self, video_id: str, max_results: int = 20) -> list[dict]:
        """動画のコメントを取得

        Args:
            video_id: 動画 ID
            max_results: 取得件数

        Returns:
            list[dict]: コメントリスト [{author, text, likes, published_at, comment_id}]
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

    parser = argparse.ArgumentParser(description="YouTube コメント投稿・一覧取得")
    subparsers = parser.add_subparsers(dest="command")

    # post コマンド（デフォルト）
    p_post = subparsers.add_parser("post", help="動画にコメントを投稿")
    p_post.add_argument("video_id", help="YouTube 動画 ID")
    p_post.add_argument("--text", default=None, help="コメントテキスト（固有のコメントを推奨）")
    p_post.add_argument("--theme", default=None, help="テーマキーワード（フォールバック用）")

    # list コマンド
    p_list = subparsers.add_parser("list", help="コメント一覧取得")
    p_list.add_argument("video_id", help="YouTube 動画 ID")
    p_list.add_argument("--max", type=int, default=20, help="取得件数")

    args = parser.parse_args()

    # サブコマンド未指定の場合は引数を直接パース（後方互換）
    if args.command is None:
        parser.add_argument("video_id", help="YouTube 動画 ID")
        parser.add_argument("--text", default=None, help="コメントテキスト")
        parser.add_argument("--theme", default=None, help="テーマキーワード")
        args = parser.parse_args()
        args.command = "post"

    poster = CommentPoster()

    if args.command == "post":
        result = poster.post_comment(args.video_id, comment_text=args.text, theme=args.theme)
        print(f"\n✅ コメント投稿完了: {result['comment_id']}")
        print(f"📝 {result['text']}")
        print("\n⚠️  固定は YouTube Studio で:")
        print(f"   https://studio.youtube.com/video/{args.video_id}/comments")

    elif args.command == "list":
        comments = poster.list_comments(args.video_id, max_results=args.max)
        for i, c in enumerate(comments, 1):
            print(f"\n{i}. {c['author']} (♥ {c['likes']})")
            print(f"   {c['text'][:100]}")


if __name__ == "__main__":
    main()
