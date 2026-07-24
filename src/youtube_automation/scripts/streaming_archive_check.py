"""1 日のライブ配信アーカイブ件数を確認するコマンド。

24/7 連続配信では日次アーカイブを期待しない。``stream_hours=11`` /
``break_hours=1`` のアーカイブ生成モードで期待件数を明示して使う。
``--expected`` を下回った場合は exit 1 + （--notify-on-shortage 時に）Discord 通知。

ローカル実行を前提とする（OAuth token / Discord webhook を VPS に置かない方針）。
``forMine=True`` で OAuth 主体のチャンネルだけを対象にするため、
チャンネル ID を引数で渡す必要は無い（識別は OAuth credentials で済んでいる）。

Usage:
    yt-stream-archive-check --date 2026-05-01 --expected 2
    yt-stream-archive-check --date 2026-05-01 --expected 2 --notify-on-shortage
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timezone

from youtube_automation.infrastructure.auth.youtube import YouTubeOAuthHandler
from youtube_automation.infrastructure.google.youtube import YouTubeClients
from youtube_automation.infrastructure.secrets import get_secret
from youtube_automation.utils.notification import NotificationError, notify
from youtube_automation.utils.streaming.daily_archive import count_archives_for_date

logger = logging.getLogger(__name__)


def _positive_int(value: str) -> int:
    """argparse type: 正整数（1 以上）のみ受け付ける。"""
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid int value: '{value}'") from None
    if n < 1:
        raise argparse.ArgumentTypeError(f"--expected must be >= 1, got {n}")
    return n


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
        type=_positive_int,
        required=True,
        help="期待件数（1 以上）。11h+1h のアーカイブ生成モードでは 2 を指定する",
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

    clients = YouTubeClients(
        full_handler=YouTubeOAuthHandler(),
        readonly_handler=YouTubeOAuthHandler.create_readonly(),
    )
    youtube = clients.youtube_readonly
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
