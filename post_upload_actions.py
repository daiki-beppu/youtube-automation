#!/usr/bin/env python3
"""
Post-Upload Actions — 公開後エンゲージメント自動化オーケストレーター

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
import logging

import utils._path_setup  # noqa: F401
from community_draft import CommunityDraftGenerator  # noqa: E402
from cross_link import CrossLinkManager  # noqa: E402
from post_comment import CommentPoster  # noqa: E402
from utils.channel_config import ChannelConfig  # noqa: E402


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

    if args.command == "comment":
        poster = CommentPoster()
        result = poster.post_comment(args.video_id, comment_text=args.text, theme=args.theme)
        print(f"\n✅ コメント投稿完了: {result['comment_id']}")
        print(f"📝 {result['text']}")
        print("\n⚠️  固定は YouTube Studio で:")
        print(f"   https://studio.youtube.com/video/{args.video_id}/comments")

    elif args.command == "cross-link":
        manager = CrossLinkManager()
        updated = manager.add_cross_link(args.video_id, args.title, max_videos=args.max_videos)
        print(f"\n✅ {len(updated)} 本の動画にクロスリンクを追加")

    elif args.command == "cross-link-remove":
        manager = CrossLinkManager()
        video_ids = args.video_ids if args.video_ids else None
        updated = manager.remove_cross_links(video_ids)
        print(f"\n✅ {len(updated)} 本の動画からクロスリンクを削除")

    elif args.command == "community-draft":
        generator = CommunityDraftGenerator()
        draft = generator.generate_community_draft(args.collection_path)
        print("\n" + "=" * 60)
        print("📝 コミュニティ投稿ドラフト")
        print("=" * 60)
        print(draft)
        print("=" * 60)
        print("\n⚠️  YouTube Studio のコミュニティタブに手動で投稿してください")

    elif args.command == "comments":
        poster = CommentPoster()
        comments = poster.list_comments(args.video_id, max_results=args.max)
        for i, c in enumerate(comments, 1):
            print(f"\n{i}. {c['author']} (♥ {c['likes']})")
            print(f"   {c['text'][:100]}")


if __name__ == "__main__":
    main()
