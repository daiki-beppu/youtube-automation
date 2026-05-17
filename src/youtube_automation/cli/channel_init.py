"""yt-channel-init — 正準ディレクトリ構造 + 最小 config/channel/*.json を一括生成する CLI.

設計原則:
    parse → plan → apply の 3 段で副作用を分離する。
    `_plan_actions` は純粋関数（存在判定の read 以外に副作用なし）、`_apply` のみが書き込み I/O を持つ。
    既存ファイルは `--force` がない限り上書きしない（差分は stderr に unified diff として表示）。
    ディレクトリ・`.gitkeep` は冪等に配置する（両方欠落・`.gitkeep` のみ欠落の両ケースを吸収）。
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from youtube_automation.utils.exceptions import ConfigError

# ----------------------- 契約定数（一箇所定義） -----------------------

CONFIG_SUBDIR = Path("config") / "channel"
GITKEEP_NAME = ".gitkeep"
PLACEHOLDER_DEFAULT = "TBD"

# 正準ディレクトリ構造（`.gitkeep` 配置先）。
DIRECTORIES: tuple[str, ...] = (
    "auth",
    "collections",
    "data",
    "docs/benchmarks",
    "research",
)


# ----------------------- Context / Plan / Action ---------------------


@dataclass(frozen=True)
class Context:
    """argparse から正規化したスキャフォールド入力."""

    short: str
    name: str
    genre: str
    style: str
    context: str


class ActionKind(Enum):
    """ファイル / ディレクトリ操作種別。文字列値はそのまま stdout サマリーに使う."""

    CREATED = "created"
    SKIPPED = "skipped"
    OVERWRITTEN = "overwritten"


@dataclass(frozen=True)
class FileAction:
    path: Path
    rel: str
    kind: ActionKind
    new_text: str = ""
    diff: str = ""


@dataclass(frozen=True)
class DirAction:
    path: Path
    rel: str
    kind: ActionKind


@dataclass(frozen=True)
class Plan:
    files: list[FileAction] = field(default_factory=list)
    directories: list[DirAction] = field(default_factory=list)


# ----------------------- テンプレ render -----------------------


def _render_meta(ctx: Context) -> dict:
    return {
        "channel": {
            "name": ctx.name,
            "short": ctx.short,
            "youtube_handle": "",
            "url": "",
        }
    }


def _render_content(ctx: Context) -> dict:
    return {
        "genre": {"primary": ctx.genre, "style": ctx.style, "context": ctx.context},
        "tags": {"base": [], "themes": {}},
        "descriptions": {"opening": "", "perfect_for": [], "hashtags": []},
        "title": {"template": ""},
    }


def _render_youtube(_ctx: Context) -> dict:
    return {
        "youtube": {
            "category_id": "10",
            "privacy_status": "public",
            "language": "en",
        }
    }


def _render_analytics(_ctx: Context) -> dict:
    return {
        "benchmark": {
            "channels": [],
            "scan_recent": 50,
            "min_views": 10000,
            "freshness_days": 3,
            "analyze_thumbnails": True,
        }
    }


def _render_empty(_ctx: Context) -> dict:
    return {}


# ファイル名 → render 関数（1 箇所集約）。
_TEMPLATES: dict[str, Callable[[Context], dict]] = {
    "meta.json": _render_meta,
    "content.json": _render_content,
    "youtube.json": _render_youtube,
    "analytics.json": _render_analytics,
    "playlists.json": _render_empty,
    "workflow.json": _render_empty,
    "audio.json": _render_empty,
}


def _serialize(data: dict) -> str:
    """`indent=2`, `ensure_ascii=False`, 末尾改行付きで JSON 化（`_write_json` 規約と等価）."""
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


# ----------------------- target 解決 -----------------------


def _resolve_target_dir(target: str | None) -> Path:
    """対象ディレクトリを解決する.

    優先順: `--target` → `CHANNEL_DIR` 環境変数 → CWD.
    `--target` / `CHANNEL_DIR` で指定された場合、存在しないなら `ConfigError`.
    CWD フォールバックは常に存在するため検証不要.
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


# ----------------------- plan (純粋) -----------------------


def _plan_actions(target: Path, ctx: Context, *, force: bool) -> Plan:
    """副作用なしで `Plan` を組み立てる（既存ファイルの read のみ実施）."""
    files: list[FileAction] = []
    config_dir = target / CONFIG_SUBDIR
    for name, render in _TEMPLATES.items():
        path = config_dir / name
        rel = (CONFIG_SUBDIR / name).as_posix()
        new_text = _serialize(render(ctx))
        files.append(_plan_file(path, rel, new_text, force=force))

    directories: list[DirAction] = []
    for rel in DIRECTORIES:
        path = target / rel
        directories.append(_plan_directory(path, rel))

    return Plan(files=files, directories=directories)


def _plan_file(path: Path, rel: str, new_text: str, *, force: bool) -> FileAction:
    if not path.exists():
        return FileAction(path=path, rel=rel, kind=ActionKind.CREATED, new_text=new_text)

    current = path.read_text(encoding="utf-8")
    if current == new_text:
        return FileAction(path=path, rel=rel, kind=ActionKind.SKIPPED, new_text=new_text)
    if force:
        return FileAction(path=path, rel=rel, kind=ActionKind.OVERWRITTEN, new_text=new_text)

    diff = "".join(
        difflib.unified_diff(
            current.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=f"{rel} (existing)",
            tofile=f"{rel} (template)",
        )
    )
    return FileAction(path=path, rel=rel, kind=ActionKind.SKIPPED, new_text=new_text, diff=diff)


def _plan_directory(path: Path, rel: str) -> DirAction:
    gitkeep = path / GITKEEP_NAME
    if path.is_dir() and gitkeep.is_file():
        return DirAction(path=path, rel=rel, kind=ActionKind.SKIPPED)
    return DirAction(path=path, rel=rel, kind=ActionKind.CREATED)


# ----------------------- apply (I/O) -----------------------


def _apply(plan: Plan) -> None:
    for action in plan.files:
        if action.kind in (ActionKind.CREATED, ActionKind.OVERWRITTEN):
            action.path.parent.mkdir(parents=True, exist_ok=True)
            action.path.write_text(action.new_text, encoding="utf-8")
    for action in plan.directories:
        if action.kind == ActionKind.CREATED:
            action.path.mkdir(parents=True, exist_ok=True)
            (action.path / GITKEEP_NAME).touch()


# ----------------------- summary / diff -----------------------


def _format_summary(plan: Plan) -> str:
    lines: list[str] = []
    for action in plan.files:
        lines.append(f"  {action.kind.value:<11} {action.rel}")
    for action in plan.directories:
        lines.append(f"  {action.kind.value:<11} {action.rel}/")
    return "\n".join(lines)


def _collect_diffs(plan: Plan) -> str:
    return "".join(action.diff for action in plan.files if action.diff)


# ----------------------- CLI entry -----------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-channel-init",
        description=(
            "正準ディレクトリ構造 + 最小 config/channel/*.json を一括生成する。"
            "既存ファイルは --force がない限り上書きしない。"
        ),
    )
    parser.add_argument(
        "--target",
        default=None,
        help="ターゲットチャンネルディレクトリ (default: CHANNEL_DIR → CWD)",
    )
    parser.add_argument("--short", required=True, help="仮チャンネルの短縮シンボル (例: BGM01)")
    parser.add_argument("--name", required=True, help="仮チャンネル名")
    parser.add_argument(
        "--genre",
        default=PLACEHOLDER_DEFAULT,
        help=f'ジャンル placeholder (default: "{PLACEHOLDER_DEFAULT}")',
    )
    parser.add_argument(
        "--style",
        default=PLACEHOLDER_DEFAULT,
        help=f'スタイル placeholder (default: "{PLACEHOLDER_DEFAULT}")',
    )
    parser.add_argument(
        "--context",
        default=PLACEHOLDER_DEFAULT,
        help=f'利用コンテキスト placeholder (default: "{PLACEHOLDER_DEFAULT}")',
    )
    parser.add_argument("--force", action="store_true", help="既存ファイルを上書きする")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        target = _resolve_target_dir(args.target)
    except ConfigError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1

    ctx = Context(
        short=args.short,
        name=args.name,
        genre=args.genre,
        style=args.style,
        context=args.context,
    )

    plan = _plan_actions(target, ctx, force=args.force)

    diffs = _collect_diffs(plan)
    if diffs:
        sys.stderr.write(diffs)

    _apply(plan)
    print(_format_summary(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
