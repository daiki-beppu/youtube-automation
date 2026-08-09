"""multi-channel workspace の書き込み対象をチャンネル境界で検査する。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from youtube_automation.configuration.loader import find_workspace_root, workspace_channels

EXIT_OK = 0
EXIT_BLOCKED = 2

_ROOT_CHANNEL_LAYOUTS = (
    ("collections",),
    ("config", "channel"),
    ("assets",),
    ("data",),
    ("auth",),
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-workspace-guard",
        description="書き込み対象 path が workspace のチャンネル境界内か検査します。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("check", help="1 件以上の path をチャンネル境界に照らして検査します。")
    check.add_argument("paths", nargs="+", metavar="path", help="Write/Edit の対象 path")
    return parser


def _channel_slug(path: Path, channels: dict[str, Path]) -> str | None:
    for slug, channel_dir in channels.items():
        if path == channel_dir.resolve() or channel_dir.resolve() in path.parents:
            return slug
    return None


def _resolve_target(raw_path: str, cwd: Path, workspace_root: Path) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path.resolve()
    if path.parts and path.parts[0] == "channels":
        return (workspace_root / path).resolve()
    return (cwd / path).resolve()


def _is_root_channel_layout(path: Path, workspace_root: Path) -> bool:
    try:
        relative_parts = path.relative_to(workspace_root).parts
    except ValueError:
        return False
    return any(relative_parts[: len(prefix)] == prefix for prefix in _ROOT_CHANNEL_LAYOUTS)


def _blocked_reason(
    target: Path,
    workspace_root: Path,
    current_slug: str | None,
    channels: dict[str, Path],
) -> str | None:
    if _is_root_channel_layout(target, workspace_root):
        return f"workspace root のチャンネル専用レイアウトです (cwd slug={current_slug or '(none)'})"

    target_slug = _channel_slug(target, channels)
    if current_slug is not None and target_slug is not None and target_slug != current_slug:
        return f"cwd slug={current_slug}, target slug={target_slug}"
    return None


def check_paths(raw_paths: list[str], cwd: Path) -> list[tuple[str, str]]:
    """境界外 path と拒否理由を、入力順を保って返す。"""
    resolved_cwd = cwd.expanduser().resolve()
    workspace_root = find_workspace_root(resolved_cwd)
    if workspace_root is None:
        return []

    channels = workspace_channels(workspace_root)
    current_slug = _channel_slug(resolved_cwd, channels)
    blocked: list[tuple[str, str]] = []
    for raw_path in raw_paths:
        target = _resolve_target(raw_path, resolved_cwd, workspace_root)
        reason = _blocked_reason(target, workspace_root, current_slug, channels)
        if reason is not None:
            blocked.append((raw_path, reason))
    return blocked


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command != "check":
        raise AssertionError(f"未対応の command です: {args.command}")

    blocked = check_paths(args.paths, Path.cwd())
    for path, reason in blocked:
        print(f"BLOCK: {path}: {reason}", file=sys.stderr)
    return EXIT_BLOCKED if blocked else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
