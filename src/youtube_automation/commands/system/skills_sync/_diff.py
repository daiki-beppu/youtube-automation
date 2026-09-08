"""`diff` subcommand — 同梱版と target の差分を表示する。"""

from __future__ import annotations

import argparse
import filecmp
import sys
from pathlib import Path

from youtube_automation.commands.system.skills_sync import (
    _dispatch_asset,
    _distribution_entries,
    _resolve_file_target,
    _run_all_assets,
)
from youtube_automation.commands.system.skills_sync._ops import _has_diff, _prunable_orphan_names


def cmd_diff(args: argparse.Namespace) -> int:
    return _dispatch_asset(
        args,
        all_assets=_diff_all,
        file_asset=lambda spec, root, target: _diff_file_asset(args.asset, spec, root, target),
        settings_asset=_diff_settings_asset,
        directory_asset=_diff_dir_asset,
    )


def _diff_all(args: argparse.Namespace) -> int:
    """全 asset を順次 diff。各 asset の default_target を使う。

    `--target` 指定時は parser 側 (`_resolve_default_target`) で既に error 終了
    しているため、ここでは args.target は必ず None。
    """
    return _run_all_assets("diff", cmd_diff)


def _diff_file_asset(asset: str, spec: dict[str, str], root: Path, target: Path) -> int:
    target = _resolve_file_target(asset, spec, target)
    src = root / spec["source_filename"]
    if not target.exists():
        print(f"target が存在しません: {target}", file=sys.stderr)
        return 1
    if not target.is_file():
        print(f"target がファイルではありません (kind='file' の asset): {target}", file=sys.stderr)
        return 1
    if filecmp.cmp(src, target, shallow=False):
        print("差分なし。target は同梱版と一致しています。")
    else:
        print("内容が異なる:")
        print(f"  ~ {target.name}")
    return 0


def _diff_settings_asset(spec: dict[str, str], root: Path, target: Path) -> int:
    from youtube_automation.commands.system.skills_sync._settings import (
        _report_hook_candidates,
        _settings_changes,
    )

    try:
        changes = _settings_changes(root / spec["source_filename"], target)
    except (OSError, ValueError) as exc:
        print(f"settings の比較に失敗: {exc}", file=sys.stderr)
        return 1
    if not (changes.missing_allow or changes.missing_deny or changes.hooks or changes.removals):
        print("差分なし。必要な settings はすべて存在します。")
        return 0
    for value in changes.missing_allow:
        print(f"  + permissions.allow: {value}")
    for value in changes.missing_deny:
        print(f"  + permissions.deny: {value}")
    _report_hook_candidates(changes)
    return 0


def _print_entry_changes(names: list[str], heading: str, marker: str, *, footer: str | None = None) -> None:
    """Display a nonempty group of distribution differences."""
    if not names:
        return
    print(heading)
    for name in names:
        print(f"  {marker} {name}")
    if footer is not None:
        print(footer)


def _diff_dir_asset(spec: dict[str, str], root: Path, target_dir: Path) -> int:
    if not target_dir.exists():
        print(f"target が存在しません: {target_dir}", file=sys.stderr)
        return 1

    bundled = set(_distribution_entries("skills", root, spec))
    on_disk = set(p.name for p in target_dir.iterdir())

    only_bundled = sorted(bundled - on_disk)
    only_disk = on_disk - bundled
    prunable_orphans = sorted(_prunable_orphan_names(on_disk, bundled))
    protected_local = sorted(only_disk - set(prunable_orphans))
    common = sorted(bundled & on_disk)

    _print_entry_changes(only_bundled, "同梱版にのみ存在 (sync で追加されます):", "+")
    _print_entry_changes(
        prunable_orphans,
        "upstream 管理の既知の旧 skill (prune 候補):",
        "-",
        footer="  (削除するには yt-skills sync --prune --yes を使ってください)",
    )
    _print_entry_changes(
        protected_local, "target にのみ存在 (未知のローカル entry として prune から保護されます):", "-"
    )

    differing = [name for name in common if _entries_differ(root / name, target_dir / name)]
    _print_entry_changes(differing, "内容が異なる entry:", "~")
    if not (only_bundled or only_disk or differing):
        print("差分なし。target は同梱版と一致しています。")
    return 0


def _entries_differ(src: Path, dst: Path) -> bool:
    if src.is_dir() and dst.is_dir():
        return _has_diff(filecmp.dircmp(src, dst))
    if src.is_file() and dst.is_file():
        return not filecmp.cmp(src, dst, shallow=False)
    # A file/directory mismatch is itself a difference.
    return True
