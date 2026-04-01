#!/usr/bin/env python3
"""コミュニティ投稿ドラフト生成

コレクション情報からコミュニティ投稿のドラフトテキストを生成する。

Usage:
    python3 automation/community_draft.py COLLECTION_PATH
"""

import argparse
import json
import logging
from pathlib import Path

import utils._path_setup  # noqa: F401
from utils.channel_config import ChannelConfig  # noqa: E402

logger = logging.getLogger(__name__)


class CommunityDraftGenerator:
    """コミュニティ投稿ドラフト生成クラス"""

    def __init__(self):
        self.config = ChannelConfig.load()

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


def main():
    """CLI エントリーポイント"""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="コミュニティ投稿ドラフト生成")
    parser.add_argument("collection_path", help="コレクションのパス")

    args = parser.parse_args()

    generator = CommunityDraftGenerator()
    draft = generator.generate_community_draft(args.collection_path)

    print("\n" + "=" * 60)
    print("📝 コミュニティ投稿ドラフト")
    print("=" * 60)
    print(draft)
    print("=" * 60)
    print("\n⚠️  YouTube Studio のコミュニティタブに手動で投稿してください")


if __name__ == "__main__":
    main()
