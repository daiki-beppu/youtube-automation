"""yt-setup-dirs - setup が必要とする最小ディレクトリを作成する CLI."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from youtube_automation.cli.setup_directory_contract import (
    GITKEEP_NAME,
    SETUP_DIRECTORIES,
    validate_setup_directory_target,
)
from youtube_automation.utils.exceptions import ConfigError


class ActionKind(Enum):
    """ディレクトリ操作種別。文字列値は stdout サマリーに使う."""

    CREATED = "created"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class DirAction:
    path: Path
    rel: str
    kind: ActionKind


def _resolve_target_dir(target: str | None) -> Path:
    """対象ディレクトリを解決する.

    優先順: `--target` -> `CHANNEL_DIR` 環境変数 -> CWD.
    明示指定されたディレクトリが存在しない場合は ConfigError。
    """
    if target:
        path = Path(target).resolve()
        if not path.is_dir():
            raise ConfigError(f"--target で指定されたディレクトリが存在しません: {path}")
        return path

    env = os.environ.get("CHANNEL_DIR")
    if env:
        path = Path(env).resolve()
        if not path.is_dir():
            raise ConfigError(f"CHANNEL_DIR で指定されたディレクトリが存在しません: {path}")
        return path

    return Path.cwd().resolve()


def plan_setup_directories(target: Path) -> tuple[DirAction, ...]:
    """setup 用ディレクトリ作成 plan を副作用なしで組み立てる."""
    actions: list[DirAction] = []
    for rel in SETUP_DIRECTORIES:
        path = target / rel
        validate_setup_directory_target(target, rel)
        gitkeep = path / GITKEEP_NAME
        kind = ActionKind.SKIPPED if path.is_dir() and gitkeep.is_file() else ActionKind.CREATED
        actions.append(DirAction(path=path, rel=rel, kind=kind))
    return tuple(actions)


def apply_setup_directories(actions: Iterable[DirAction]) -> None:
    """plan された setup 用ディレクトリと .gitkeep を作成する."""
    for action in actions:
        if action.kind == ActionKind.CREATED:
            action.path.mkdir(parents=True, exist_ok=True)
            (action.path / GITKEEP_NAME).touch()


def _format_summary(actions: Iterable[DirAction]) -> str:
    return "\n".join(f"  {action.kind.value:<11} {action.rel}/" for action in actions)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-setup-dirs",
        description="setup に必要な最小ディレクトリ構造を冪等に作成する。config は生成しない。",
    )
    parser.add_argument(
        "--target",
        default=None,
        help="ターゲットチャンネルディレクトリ (default: CHANNEL_DIR -> CWD)",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        target = _resolve_target_dir(args.target)
        actions = plan_setup_directories(target)
        apply_setup_directories(actions)
    except ConfigError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1

    print(_format_summary(actions))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
