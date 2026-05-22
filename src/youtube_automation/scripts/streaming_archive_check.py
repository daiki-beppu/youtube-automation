"""1 日のライブ配信アーカイブ件数を確認するコマンド。

11h+1h 配信サイクルでは 1 日 2 本のアーカイブが残るのが期待値。
``--expected`` を下回った場合は exit 1 + （--notify-on-shortage 時に）Discord 通知。

ローカル実行を前提とする（OAuth token / Discord webhook を VPS に置かない方針）。
``forMine=True`` で OAuth 主体のチャンネルだけを対象にするため、
チャンネル ID を引数で渡す必要は無い（識別は OAuth credentials で済んでいる）。

Usage:
    yt-stream-archive-check --date 2026-05-01 --expected 2
    yt-stream-archive-check --date 2026-05-01 --notify-on-shortage
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timezone

from youtube_automation.utils.notification import NotificationError, notify
from youtube_automation.utils.secrets import get_secret
from youtube_automation.utils.streaming.daily_archive import count_archives_for_date

# テスト側 patch.object("build_youtube_service") との契約を保つため別名で取り込む
from youtube_automation.utils.youtube_service import get_youtube as build_youtube_service

logger = logging.getLogger(__name__)

# 11h 配信 + 1h 休止 = 1 サイクル 12h、1 日 2 サイクル → 2 本/日
_DEFAULT_EXPECTED = 2


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ライブ配信アーカイブ件数を確認する")
    parser.add_argument(
        "--date",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        default=None,
        help="対象日 (YYYY-MM-DD, UTC)。省略時は今日 (UTC)",
    )
    parser.add_argument(
        "--expected",
        type=int,
        default=_DEFAULT_EXPECTED,
        help=f"期待件数 (default: {_DEFAULT_EXPECTED} = 11h+1h サイクル × 2 本/日)",
    )
    parser.add_argument(
        "--notify-on-shortage",
        action="store_true",
        help="件数不足時に Discord Webhook へ通知する",
    )
    return parser.parse_args(argv)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    args = _parse_args(sys.argv[1:])

    target: date = args.date or datetime.now(tz=timezone.utc).date()

    youtube = build_youtube_service()
    count = count_archives_for_date(youtube, target)

    logger.info("アーカイブ件数: %d (期待: %d, 対象日: %s UTC)", count, args.expected, target.isoformat())

    if count >= args.expected:
        return 0

    message = (
        f"[youtube-stream] アーカイブ不足: {target.isoformat()} に {count}/{args.expected} 本のみ。"
        " 配信が停止していないか確認してください。"
    )
    logger.warning(message)
    if args.notify_on_shortage:
        try:
            notify(content=message, webhook_url=get_secret("DISCORD_WEBHOOK_URL"))
        except NotificationError as e:
            # cron から件数不足 (exit 1) と通知失敗 (exit 2) を判別するため別コードを返す
            logger.error("Discord 通知失敗: %s", e)
            return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
