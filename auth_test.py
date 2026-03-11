#!/usr/bin/env python3
"""YouTube API 認証テスト

認証の動作確認と接続テストを実行する単独スクリプト。
"""

import argparse
import logging
import sys

import utils._path_setup  # noqa: F401
from auth.oauth_handler import YouTubeOAuthHandler  # noqa: E402
from utils.channel_config import ChannelConfig  # noqa: E402

logger = logging.getLogger(__name__)


def run_auth_test(force_reauth=False):
    """
    YouTube API 認証テストを実行する。

    Args:
        force_reauth (bool): 強制再認証フラグ

    Returns:
        bool: 認証成功なら True
    """
    config = ChannelConfig.load()
    logger.info(f"🔐 {config.channel_name} - YouTube API 認証テスト")

    try:
        handler = YouTubeOAuthHandler()
        handler.authenticate(force_reauth=force_reauth)

        if handler.test_connection():
            logger.info("✅ 認証完了 - 接続テスト成功")
            return True
        else:
            logger.error("❌ 認証失敗 - 接続テストに失敗")
            return False

    except Exception as e:
        logger.error(f"❌ 認証エラー: {e}")
        return False


def main():
    """CLI エントリーポイント"""
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    config = ChannelConfig.load()
    parser = argparse.ArgumentParser(description=f'{config.channel_short} 認証テスト')
    parser.add_argument('--force-reauth', action='store_true', help='強制再認証')

    args = parser.parse_args()

    if run_auth_test(force_reauth=args.force_reauth):
        print("✅ 認証テスト成功")
        sys.exit(0)
    else:
        print("❌ 認証テスト失敗")
        sys.exit(1)


if __name__ == "__main__":
    main()
