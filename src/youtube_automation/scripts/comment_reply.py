"""yt-comments-reply — YouTube コメント自動返信 CLI.

Examples:
    # 対象コメントを JSON で export（CLI 内部では返信文を生成しない）
    yt-comments-reply --dry-run --export-candidates --json --limit 5 > /tmp/comment-candidates.json

    # Agent が生成した返信 JSON を使って dry-run 監査
    yt-comments-reply --dry-run --agent-replies-file /tmp/comment-replies.json --limit 5

    # 監査済み返信を実際に投稿（--apply は必須）
    yt-comments-reply --apply --agent-replies-file /tmp/comment-replies.json --video-id abc123

設計方針:
    dry-run がデフォルトではなく、--dry-run / --apply のどちらか明示を要求する。
    この非破壊コマンドを「何となく実行した」ときに YouTube 側に書き込まれないようにするため。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import replace
from datetime import datetime
from typing import Iterable

from youtube_automation.utils.comments import CommentReplier
from youtube_automation.utils.config import channel_dir as _channel_dir
from youtube_automation.utils.config import load_config
from youtube_automation.utils.exceptions import AutomationError, ConfigError
from youtube_automation.utils.youtube_service import get_youtube

logger = logging.getLogger(__name__)


def _parse_since(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as e:
        raise SystemExit(f"[error] --since は ISO8601 形式で指定してください: {e}") from e


def _load_agent_replies(path: str | None) -> dict[str, str] | None:
    if path is None:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except OSError as e:
        raise AutomationError(f"agent replies JSON を読めません: {path}: {e}") from e
    except json.JSONDecodeError as e:
        raise AutomationError(f"agent replies JSON のパースに失敗しました: {path}: {e}") from e

    if not (isinstance(payload, dict) and isinstance(payload.get("replies"), list)):
        raise AutomationError('agent replies JSON は {"replies": [...]} の object で指定してください')

    rows = payload["replies"]
    replies: dict[str, str] = {}
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise AutomationError(f"agent replies JSON replies[{i}] は object でなければなりません")
        comment_id = row.get("comment_id")
        reply_text = row.get("reply_text")
        if not isinstance(comment_id, str) or not comment_id.strip():
            raise AutomationError(f"agent replies JSON replies[{i}].comment_id が必須です")
        if not isinstance(reply_text, str) or not reply_text.strip():
            raise AutomationError(f"agent replies JSON replies[{i}].reply_text が必須です")
        comment_key = comment_id.strip()
        if comment_key in replies:
            raise AutomationError(f"agent replies JSON comment_id が重複しています: {comment_key}")
        replies[comment_key] = reply_text.strip()
    return replies


def _print_summary(plan, *, dry_run: bool, as_json: bool) -> None:
    if as_json:
        payload = {
            "dry_run": dry_run,
            "planned": plan.planned,
            "replied": plan.replied,
            "skipped": plan.skipped,
            "errors": plan.errors,
        }
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return

    header = "[dry-run] " if dry_run else ""
    print(f"{header}返信候補: {len(plan.planned)}件")
    print(f"{header}実返信  : {len(plan.replied)}件")
    print(f"{header}スキップ: {len(plan.skipped)}件")
    print(f"{header}エラー  : {len(plan.errors)}件")
    print()

    for row in plan.planned:
        print(
            f"  [planned] video={row['video_id']} comment_id={row['comment_id']} "
            f"policy={row.get('reply_policy')} provider={row.get('provider')} lang={row.get('language')}"
        )
        print(f"    author: {row.get('comment_author')}")
        print(f"    text  : {row.get('comment_text', '')[:80]}")
        print(f"    reply : {row.get('reply_text', '')[:120]}")
    for row in plan.replied:
        print(
            f"  [replied] video={row['video_id']} comment_id={row['comment_id']} "
            f"policy={row.get('reply_policy')} provider={row.get('provider')} lang={row.get('language')}"
        )
        print(f"    reply : {row.get('reply_text', '')[:120]}")
    for row in plan.skipped:
        print(f"  [skipped] video={row['video_id']} comment_id={row['comment_id']} reason={row.get('reason')}")
    for row in plan.errors:
        print(f"  [error] video={row['video_id']} comment_id={row['comment_id']} {row.get('error')}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-comments-reply",
        description="基本フィルタ通過後の YouTube コメントを返信候補化し、LLM または agent 返信で処理する",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="API 送信せず計画のみ出力")
    mode.add_argument("--apply", action="store_true", help="実際に YouTube へ返信を送信する")

    parser.add_argument(
        "--video-id",
        dest="video_ids",
        action="append",
        default=None,
        help="対象動画 ID（複数指定可、省略時は自チャンネルの全動画）",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="1 実行での返信件数上限（省略時は comments.max_replies_per_run）",
    )
    parser.add_argument(
        "--per-video-limit",
        type=int,
        default=100,
        help="動画あたりのコメント取得件数上限（default: 100）",
    )
    parser.add_argument("--since", default=None, help="ISO8601 形式。これより新しいコメントのみ対象")
    parser.add_argument("--json", action="store_true", help="結果を JSON で出力")
    parser.add_argument(
        "--export-candidates",
        action="store_true",
        help="返信対象コメントを JSON 出力する（LLM 生成なし、--dry-run と併用）",
    )
    parser.add_argument(
        "--agent-replies-file",
        default=None,
        help="Claude Code Agent が生成した返信 JSON を使用する（CLI 内部では返信文を生成しない）",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        config = load_config()
    except AutomationError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1

    if not config.comments.enabled:
        print(
            "[error] comments.enabled=false です。config/channel/comments.json を編集して true にしてください",
            file=sys.stderr,
        )
        return 1

    effective_config = config.comments
    if args.limit is not None:
        effective_config = replace(effective_config, max_replies_per_run=args.limit)

    since = _parse_since(args.since)

    try:
        if args.export_candidates and not args.json:
            raise ConfigError("--export-candidates は --json と併用してください")
        if args.export_candidates and not args.dry_run:
            raise ConfigError("--export-candidates は --dry-run でのみ使用できます")
        if args.export_candidates and args.agent_replies_file:
            raise ConfigError("--export-candidates と --agent-replies-file は同時指定できません")
        agent_replies = _load_agent_replies(args.agent_replies_file)
        youtube = get_youtube()
        replier = CommentReplier(
            youtube,
            config=effective_config,
            channel_dir=_channel_dir(),
            default_language=config.youtube.api.language,
            agent_replies=agent_replies,
        )
        plan = replier.run(
            dry_run=args.dry_run,
            video_ids=args.video_ids,
            per_video_limit=args.per_video_limit,
            since=since,
            export_candidates=args.export_candidates,
        )
    except AutomationError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1

    _print_summary(plan, dry_run=args.dry_run, as_json=args.json)
    return 0 if not plan.errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
