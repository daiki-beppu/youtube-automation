"""``yt-oauth`` の CLI adapter。OAuth token を発行し接続テストまで行う。"""

from __future__ import annotations

import argparse
import logging
import sys

from youtube_automation.core.errors import AuthError, ConfigError, ValidationError, YouTubeAPIError
from youtube_automation.infrastructure.auth.redaction import redact_sensitive_data
from youtube_automation.infrastructure.auth.youtube import YouTubeOAuthHandler

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> None:
    """``yt-oauth`` 本体。

    Args:
        argv: CLI 引数。None なら ``sys.argv[1:]``。
            テストから直接呼ぶ場合は ``main([])`` のように明示する
    """
    parser = argparse.ArgumentParser(
        prog="yt-oauth",
        description="YouTube OAuth 2.0 認証（token 発行・接続テスト）",
    )
    parser.add_argument(
        "--readonly",
        action="store_true",
        help="read-only スコープの token.readonly.json を発行する（write scope を含まない。#1699）",
    )
    parser.add_argument(
        "--refresh-only",
        action="store_true",
        help="既存 refresh token で非対話更新する（ブラウザ認証・API 接続テストは行わない）",
    )
    args = parser.parse_args(argv)

    mode_label = "read-only" if args.readonly else "full access"
    print(f"🎵 YouTube OAuth 2.0 認証テスト（{mode_label}）")
    print("=" * 60)

    auth_handler = None
    try:
        # OAuth ハンドラー初期化
        if args.readonly:
            auth_handler = (
                YouTubeOAuthHandler.create_readonly(interactive=False)
                if args.refresh_only
                else YouTubeOAuthHandler.create_readonly()
            )
        else:
            auth_handler = YouTubeOAuthHandler(interactive=False) if args.refresh_only else YouTubeOAuthHandler()

        if args.refresh_only:
            auth_handler.refresh_existing_credentials()
            print("\n✅ OAuth token の非対話更新が完了しました。")
            return

        # 認証実行
        auth_handler.authenticate()

        # 接続テスト
        if auth_handler.test_connection():
            print("\n🎉 認証・接続テスト完了！YouTube自動アップロードの準備ができました。")
        else:
            print("\n❌ 接続テストに失敗しました。設定を確認してください。")

    except KeyboardInterrupt:
        # Ctrl-C: UNIX 慣例 (128 + SIGINT=2 → 130)
        print("\n🛑 処理が中断されました")
        sys.exit(130)
    except (AuthError, ConfigError, ValidationError, YouTubeAPIError, OSError) as e:
        paths = []
        if auth_handler is not None:
            paths.extend([auth_handler.client_secrets_file, auth_handler.token_file])
        message = redact_sensitive_data(str(e), *paths)
        if args.refresh_only:
            logger.error(
                "CLI 実行失敗: %s。対話可能なターミナルで `uv run yt-oauth` を実行して再認証してください",
                message,
            )
        else:
            logger.error("CLI 実行失敗: %s", message)
        sys.exit(1)


if __name__ == "__main__":
    main()
