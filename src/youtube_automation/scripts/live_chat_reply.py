"""yt-live-chat-reply — YouTube ライブチャット自動返信 CLI."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Iterable

from youtube_automation.configuration import channel_dir, load_config
from youtube_automation.utils.exceptions import AutomationError
from youtube_automation.utils.live_chat import LiveChatReplier
from youtube_automation.utils.youtube_service import ServiceRegistry


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="yt-live-chat-reply",
        description="アクティブ配信のチャットを監視し、Codex が選別したメッセージに返信する",
    )


def main(argv: Iterable[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        config = load_config()
        if not config.comments.live_chat.enabled:
            print(
                "[error] comments.live_chat.enabled=false です。config/channel/comments.json で有効化してください",
                file=sys.stderr,
            )
            return 1
        youtube = ServiceRegistry().youtube
        LiveChatReplier(
            youtube,
            config=config.comments.live_chat,
            channel_dir=channel_dir(),
        ).run_forever()
    except KeyboardInterrupt:
        logging.info("ライブチャット監視を終了します")
    except AutomationError as error:
        print(f"[error] {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
