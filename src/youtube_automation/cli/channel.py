"""Workspace 内の channel slug を扱う ``yt-channel`` CLI."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterable
from pathlib import Path

from youtube_automation.utils.config import find_workspace_root, workspace_channels

EXIT_OK = 0
EXIT_OUTSIDE_WORKSPACE = 1
EXIT_EMPTY_WORKSPACE = 2
EXIT_UNREADABLE = 3


def _workspace_root(start: Path | None = None) -> Path | None:
    """有効な workspace を探し、空 workspace も ``channels/`` から識別する."""
    current = (start or Path.cwd()).expanduser().resolve()
    detected = find_workspace_root(current)
    if detected is not None:
        return detected

    # find_workspace_root は有効な channel が 1 件以上ある workspace のみ返す。
    # list では空 workspace を workspace 外と区別するため、channels/ も marker として扱う。
    for parent in (current, *current.parents):
        if (parent / "channels").is_dir():
            return parent
    return None


def _assert_channel_directories_readable(workspace_root: Path) -> None:
    """候補ディレクトリを走査できることを確認し、黙って欠落させない."""
    channels_root = workspace_root / "channels"
    with os.scandir(channels_root) as candidates:
        channel_dirs = [Path(candidate.path) for candidate in candidates if candidate.is_dir()]

    for channel_dir in channel_dirs:
        with os.scandir(channel_dir):
            pass
        config_dir = channel_dir / "config"
        if not config_dir.is_dir():
            continue
        with os.scandir(config_dir):
            pass
        channel_config_dir = config_dir / "channel"
        if channel_config_dir.is_dir():
            with os.scandir(channel_config_dir):
                pass


def _list_channels() -> int:
    try:
        workspace_root = _workspace_root()
    except OSError as error:
        print(
            f"[error] workspace の channel directory を読み取れません: {error}. "
            "channels/ 配下の読み取り・実行権限を確認してください。",
            file=sys.stderr,
        )
        return EXIT_UNREADABLE

    if workspace_root is None:
        print(
            "[error] workspace が見つかりません。"
            "channels/<slug>/config/channel/ を持つ workspace 配下で実行してください。",
            file=sys.stderr,
        )
        return EXIT_OUTSIDE_WORKSPACE

    try:
        _assert_channel_directories_readable(workspace_root)
        channels = workspace_channels(workspace_root)
    except OSError as error:
        print(
            f"[error] workspace の channel directory を読み取れません: {error}. "
            "channels/ 配下の読み取り・実行権限を確認してください。",
            file=sys.stderr,
        )
        return EXIT_UNREADABLE

    if not channels:
        print(
            f"[error] workspace に channel がありません: {workspace_root / 'channels'}. "
            "channels/<slug>/config/channel/ を作成してください。",
            file=sys.stderr,
        )
        return EXIT_EMPTY_WORKSPACE

    for slug in channels:
        print(slug)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-channel",
        description="workspace の channel を操作する。workspace は cwd の祖先から探索する。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "list",
        help="利用可能な channel slug を一覧表示する",
        description=(
            "cwd の祖先から workspace を探索し、channels/<slug>/config/channel/ を持つ "
            "channel slug を辞書順で 1 行 1 件出力する。config の選択状態は変更しない。"
        ),
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "list":
        return _list_channels()
    parser.error(f"未対応の command です: {args.command}")
    return EXIT_OUTSIDE_WORKSPACE


if __name__ == "__main__":
    raise SystemExit(main())
