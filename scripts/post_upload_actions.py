#!/usr/bin/env python3
"""
Post-Upload Actions — コミュニティ投稿ドラフト生成

Usage:
    python3 automation/post_upload_actions.py community-draft COLLECTION_PATH
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from community_draft import CommunityDraftGenerator  # noqa: E402


def main():
    """CLI エントリーポイント"""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Post-Upload Actions")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_community = subparsers.add_parser("community-draft", help="コミュニティ投稿ドラフト生成")
    p_community.add_argument("collection_path", help="コレクションのパス")

    args = parser.parse_args()

    if args.command == "community-draft":
        generator = CommunityDraftGenerator()
        draft = generator.generate_community_draft(args.collection_path)
        print("\n" + "=" * 60)
        print("コミュニティ投稿ドラフト")
        print("=" * 60)
        print(draft)
        print("=" * 60)
        print("\nYouTube Studio のコミュニティタブに手動で投稿してください")


if __name__ == "__main__":
    main()
