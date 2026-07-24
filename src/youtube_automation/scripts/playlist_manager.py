"""CLI adapter for the uploads-domain playlist manager."""

import argparse
import logging

from youtube_automation.configuration import load_config
from youtube_automation.domains.uploads.playlists import PlaylistManager
from youtube_automation.infrastructure.auth.youtube import YouTubeOAuthHandler
from youtube_automation.infrastructure.google.youtube import YouTubeClients


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    config = load_config()
    parser = argparse.ArgumentParser(description=f"{config.meta.channel_short} Playlist Manager")
    parser.add_argument("--init", action="store_true", help="プレイリスト作成 + 全動画割り当て")
    parser.add_argument("--status", action="store_true", help="現在の状態表示")
    parser.add_argument("--assign", metavar="VIDEO_ID", help="単一動画をプレイリストに追加")
    parser.add_argument("--theme", help="--assign 用のテーマ名")
    parser.add_argument(
        "--clean-deleted", action="store_true", help="全プレイリストから削除済み/非公開動画のエントリを除去"
    )
    parser.add_argument("--dry-run", action="store_true", help="ドライラン（実行せず計画のみ表示）")
    args = parser.parse_args()
    manager = PlaylistManager(clients=YouTubeClients(full_handler=YouTubeOAuthHandler()))

    if args.init:
        manager.init(dry_run=args.dry_run)
    elif args.status:
        from youtube_automation.scripts.playlist_status import PlaylistStatusViewer

        PlaylistStatusViewer().show_status()
    elif args.clean_deleted:
        results = manager.clean_deleted_entries(dry_run=args.dry_run)
        print(f"完了: {sum(results.values())} 件除去")
    elif args.assign:
        if not args.theme:
            parser.error("--assign には --theme が必要です")
        print(f"割り当て: {manager.assign_video(args.assign, args.theme, dry_run=args.dry_run)}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
