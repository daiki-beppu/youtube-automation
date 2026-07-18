"""argparse スキーマ — `yt-skills` の subcommand / flag 構築。"""

from __future__ import annotations

import argparse
import sys

from youtube_automation.cli.skills_sync import _ASSET_SPECS, _guard_target_with_all, cmd_list
from youtube_automation.cli.skills_sync._diff import cmd_diff
from youtube_automation.cli.skills_sync._lint import cmd_lint
from youtube_automation.cli.skills_sync._sync import cmd_sync


def _add_asset_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--asset",
        choices=sorted([*_ASSET_SPECS.keys(), "all"]),
        default="all",
        help="配布対象 (default: all = 全 asset を一括処理)",
    )


def _resolve_default_target(args: argparse.Namespace) -> None:
    """`--target` 未指定 (None) 時に `--asset` 別のデフォルトを埋める。

    `--asset all` のときは個別 asset の default_target を使うため埋めない
    (cmd_* 側で each asset を巡回するときに per-asset の default_target を resolve する)。

    `--asset all` + `--target X` の組み合わせは曖昧なため `_guard_target_with_all`
    が `ValueError` を raise する。CLI 経由ではここで catch して stderr + `sys.exit(2)`
    に変換し、ユーザーには誘導付きエラーメッセージを表示する。ライブラリ呼び出し元
    (`cmd_sync` / `cmd_diff` を import して使う caller) は `ValueError` をそのまま受け取る。
    """
    try:
        _guard_target_with_all(args)
    except ValueError as exc:
        sys.stderr.write(f"error: {exc}\n")
        sys.exit(2)
    if args.asset == "all":
        return
    if getattr(args, "target", None) is None:
        args.target = _ASSET_SPECS[args.asset]["default_target"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-skills",
        description=("Claude Code 配布物の同期ツール (youtube-channels-automation)"),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="同梱 asset 一覧を表示")
    _add_asset_argument(p_list)
    p_list.set_defaults(func=cmd_list)

    p_sync = sub.add_parser("sync", help="asset を target に展開")
    _add_asset_argument(p_sync)
    p_sync.add_argument(
        "--target",
        default=None,
        help=("展開先パス (default: --asset の default_target に従う、kind='file' の場合はファイルパス)"),
    )
    p_sync.add_argument(
        "--symlink",
        action="store_true",
        help="コピーではなくシンボリックリンクで展開する (開発者向け)",
    )
    p_sync.add_argument(
        "--force",
        action="store_true",
        help="既存を上書きする",
    )
    p_sync.add_argument(
        "--dry-run",
        action="store_true",
        help="実際には書き込まず処理予定だけ表示する",
    )
    p_sync.add_argument(
        "--only",
        nargs="+",
        metavar="ENTRY",
        help="指定した entry だけ同期 (省略時は全件、kind='file' では無効)",
    )
    p_sync.add_argument(
        "--prune",
        action="store_true",
        help=(
            "upstream 管理の既知の旧 skill を削除候補として列挙する "
            "(skills asset のみ、未知のローカル skill は対象外、実削除には --yes も必要)"
        ),
    )
    p_sync.add_argument(
        "--yes",
        action="store_true",
        help="--prune と併用したとき、列挙のみではなく実際に削除する",
    )
    p_sync.set_defaults(func=cmd_sync)

    p_diff = sub.add_parser("diff", help="同梱版と target の差分を表示")
    _add_asset_argument(p_diff)
    p_diff.add_argument(
        "--target",
        default=None,
        help=("比較先パス (default: --asset の default_target に従う、kind='file' の場合はファイルパス)"),
    )
    p_diff.set_defaults(func=cmd_diff)

    p_lint = sub.add_parser(
        "lint",
        help="SKILL.md frontmatter を検証 (strict YAML / name・description 非空 / double-quote)",
    )
    p_lint.add_argument(
        "skills",
        nargs="*",
        metavar="SKILL",
        help="検証する skill 名 (省略時は全 skill)",
    )
    # lint は skills asset 固定 (--asset/--target は取らない)。
    # _resolve_default_target が args.asset を参照するため default を埋めておく。
    p_lint.set_defaults(func=cmd_lint, asset="skills")

    return parser
