"""``yt-vote-log`` — ``data/community/weekly-vote-log.json`` の読み書き CLI.

YouTube Studio の投票結果を ``yt-vote-log append`` で週次記録し、
``/collection-ideate`` の theme weight hook が直近 N 週分を参照する。

Subcommands:

- ``append``: 1 週分の投票結果を append (axes 各軸の key/label/votes を入力)
- ``show``: 直近 N 件のエントリを表示
- ``weights``: ``compute_vote_log_weights`` の結果 (weights / forced_axis) を表示
- ``validate``: ファイルが現行 schema に従うか検証

Examples::

    yt-vote-log append --week-start 2026-05-04 \\
        --axis rain_window:Rain Window:124 \\
        --axis midnight_drive:Midnight Drive:98

    yt-vote-log show --recent 4
    yt-vote-log weights --recent 4 --decay 0.7
    yt-vote-log validate
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from youtube_automation.configuration import channel_dir as _channel_dir
from youtube_automation.utils.exceptions import AutomationError, ValidationError
from youtube_automation.utils.weekly_vote_log import (
    AxisVote,
    append_weekly_vote_entry,
    compute_vote_log_weights,
    load_weekly_vote_log,
)

logger = logging.getLogger(__name__)


def _parse_axis_arg(value: str) -> AxisVote:
    """``key:label:votes`` 形式を ``AxisVote`` へパースする.

    ``key`` と ``label`` には ``:`` を含めない前提 (label に空白は許可)。
    """
    parts = value.split(":")
    if len(parts) < 3:
        raise argparse.ArgumentTypeError(f"--axis '{value}' は 'key:label:votes' 形式である必要があります")
    # label に ':' を含めたい場合は最後を votes、最初を key として残りを label に
    key = parts[0].strip()
    votes_str = parts[-1].strip()
    label = ":".join(parts[1:-1]).strip()
    if not key:
        raise argparse.ArgumentTypeError(f"--axis '{value}' の key が空です")
    if not label:
        raise argparse.ArgumentTypeError(f"--axis '{value}' の label が空です")
    try:
        votes = int(votes_str)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"--axis '{value}' の votes が整数ではありません ({votes_str})") from exc
    if votes < 0:
        raise argparse.ArgumentTypeError(f"--axis '{value}' の votes は 0 以上 (got {votes})")
    return AxisVote(key=key, label=label, votes=votes)


def _cmd_append(args: argparse.Namespace) -> int:
    log = append_weekly_vote_entry(
        channel_dir=_channel_dir(),
        week_start=args.week_start,
        axes=args.axes,
        notes=args.notes or "",
        path=args.path,
        replace=args.replace,
    )
    latest = next(
        (entry for entry in log.entries if entry.week_start == args.week_start),
        None,
    )
    if latest is None:  # pragma: no cover — append直後に必ず存在する
        print("[WARN] append 後に対象エントリが見つかりません", file=sys.stderr)
        return 1
    print(
        f"[OK] {latest.week_start}: top_axis={latest.top_axis} "
        f"(total_votes={latest.total_votes}, axes={len(latest.axes)})"
    )
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    log = load_weekly_vote_log(channel_dir=_channel_dir(), path=args.path)
    entries = log.recent(args.recent) if args.recent else tuple(log.entries)
    payload = [entry.to_dict() for entry in entries]
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _cmd_weights(args: argparse.Namespace) -> int:
    log = load_weekly_vote_log(channel_dir=_channel_dir(), path=args.path)
    result = compute_vote_log_weights(
        log,
        recent_weeks=args.recent,
        forced_streak_threshold=args.forced_threshold,
        decay=args.decay,
    )
    payload = {
        "weights": result.weights,
        "forced_axis": result.forced_axis,
        "forced_streak": result.forced_streak,
        "considered_weeks": result.considered_weeks,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    log = load_weekly_vote_log(channel_dir=_channel_dir(), path=args.path, missing_ok=False)
    print(f"[OK] schema_version={log.schema_version}, entries={len(log.entries)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-vote-log",
        description="weekly-vote-log.json の append / show / weights / validate (#509)",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help="ログファイルパス (省略時は data/community/weekly-vote-log.json)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_append = sub.add_parser("append", help="1 週分の投票結果を append する")
    p_append.add_argument("--week-start", required=True, help="投票週開始日 (YYYY-MM-DD)")
    p_append.add_argument(
        "--axis",
        dest="axes",
        action="append",
        type=_parse_axis_arg,
        required=True,
        help="key:label:votes 形式。複数指定可",
    )
    p_append.add_argument("--notes", default=None, help="フリーテキスト")
    p_append.add_argument(
        "--replace",
        action="store_true",
        help="同 week_start が既存なら置換する (デフォルトは衝突エラー)",
    )
    p_append.set_defaults(func=_cmd_append)

    p_show = sub.add_parser("show", help="エントリを JSON で表示")
    p_show.add_argument("--recent", type=int, default=0, help="直近 N 件のみ (0=全件)")
    p_show.set_defaults(func=_cmd_show)

    p_weights = sub.add_parser("weights", help="compute_vote_log_weights の結果を表示")
    p_weights.add_argument("--recent", type=int, default=4, help="計算対象の週数 (default 4)")
    p_weights.add_argument(
        "--forced-threshold",
        type=int,
        default=2,
        help="連続 1 位で強制採用とみなす週数 (default 2)",
    )
    p_weights.add_argument(
        "--decay",
        type=float,
        default=0.7,
        help="1 週古くなるごとの減衰率 (default 0.7)",
    )
    p_weights.set_defaults(func=_cmd_weights)

    p_validate = sub.add_parser("validate", help="schema 検証 (ファイル必須)")
    p_validate.set_defaults(func=_cmd_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except (AutomationError, ValidationError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
