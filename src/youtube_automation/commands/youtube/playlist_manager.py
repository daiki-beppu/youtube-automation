"""CLI adapter for the uploads-domain playlist manager."""

import argparse
import logging
import sys
from pathlib import Path

from youtube_automation.core.errors import AutomationError
from youtube_automation.domains.uploads.playlists import PlaylistManager
from youtube_automation.infrastructure.auth.youtube import YouTubeOAuthHandler
from youtube_automation.infrastructure.google.youtube import YouTubeClients


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="YouTube プレイリストの作成・割り当て・整理を行う")
    parser.add_argument("--init", action="store_true", help="プレイリスト作成 + 全動画割り当て")
    parser.add_argument("--status", action="store_true", help="現在の状態表示")
    parser.add_argument("--assign", metavar="VIDEO_ID", help="単一動画をプレイリストに追加")
    parser.add_argument("--theme", help="--assign 用のテーマ名")
    parser.add_argument("--collection", type=Path, help="--assign 対象の collection path")
    parser.add_argument(
        "--clean-deleted", action="store_true", help="全プレイリストから削除済み/非公開動画のエントリを除去"
    )
    parser.add_argument("--dry-run", action="store_true", help="ドライラン（実行せず計画のみ表示）")
    args = parser.parse_args(argv)
    try:
        if args.status:
            from youtube_automation.commands.youtube.playlist_status import PlaylistStatusViewer

            PlaylistStatusViewer().show_status()
            return 0
        if args.assign and not args.theme:
            parser.error("--assign には --theme が必要です")
        if not (args.init or args.clean_deleted or args.assign):
            parser.print_help()
            return 0

        manager = PlaylistManager(clients=YouTubeClients(full_handler=YouTubeOAuthHandler()))
        if args.init:
            manager.init(dry_run=args.dry_run)
        elif args.clean_deleted:
            results = manager.clean_deleted_entries(dry_run=args.dry_run)
            print(f"完了: {sum(results.values())} 件除去")
        else:
            assignments = manager.assign_video(
                args.assign,
                args.theme,
                dry_run=args.dry_run,
                collection_path=args.collection,
            )
            print(f"割り当て: {assignments}")
        return 0
    except AutomationError as error:
        print(f"エラー: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    main()
