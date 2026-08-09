"""Idempotently restore a YouTube live broadcast around an active ingest."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime

from googleapiclient.discovery import build

from youtube_automation.configuration import channel_dir
from youtube_automation.core.errors import AutomationError
from youtube_automation.domains.youtube.broadcast_recovery import RecoveryRequest, recover_broadcast
from youtube_automation.infrastructure.auth.redaction import redact_sensitive_data
from youtube_automation.infrastructure.auth.youtube import YouTubeOAuthHandler
from youtube_automation.infrastructure.youtube.streaming.broadcast_recovery import (
    YouTubeBroadcastRecoveryGateway,
)

_STREAMING_SCOPE = "https://www.googleapis.com/auth/youtube"
_STREAMING_TOKEN_FILENAME = "token_streaming.json"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-stream-broadcast-recover",
        description="active ingest の配信枠を再利用または作成し、bind 後に live へ遷移する",
    )
    parser.add_argument("--stream-id", required=True, help="既存 persistent live stream の ID")
    parser.add_argument(
        "--title",
        required=True,
        help="新規枠の title。未 bind の upcoming 枠を再利用する冪等キーにも使う",
    )
    parser.add_argument(
        "--privacy-status",
        choices=("private", "unlisted", "public"),
        default="public",
        help="新規枠の公開範囲 (default: public)",
    )
    parser.add_argument("--dry-run", action="store_true", help="API write を行わず予定 action を JSON 出力する")
    parser.add_argument("--force-reauth", action="store_true", help="streaming 用 OAuth token を再認証する")
    return parser


def _create_gateway(force_reauth: bool) -> YouTubeBroadcastRecoveryGateway:
    token_path = channel_dir() / "auth" / _STREAMING_TOKEN_FILENAME
    credentials = YouTubeOAuthHandler(scopes=[_STREAMING_SCOPE], token_path=token_path).authenticate(
        force_reauth=force_reauth
    )
    return YouTubeBroadcastRecoveryGateway(build("youtube", "v3", credentials=credentials))


def _scheduled_start_time() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    request = RecoveryRequest(
        stream_id=args.stream_id,
        title=args.title,
        scheduled_start_time=_scheduled_start_time(),
        privacy_status=args.privacy_status,
        dry_run=args.dry_run,
    )
    try:
        result = recover_broadcast(_create_gateway(args.force_reauth), request)
    except AutomationError as error:
        print(
            json.dumps(
                {"status": "error", "error": redact_sensitive_data(str(error))},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result.to_dict(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
