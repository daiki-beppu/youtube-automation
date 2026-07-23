"""`diff` subcommand — 同梱版と target の差分を表示する。"""

from __future__ import annotations

import argparse
import filecmp
import sys
from pathlib import Path

from youtube_automation.cli.skills_sync import (
    _ASSET_SPECS,
    _asset_root,
    _distribution_entries,
    _guard_target_with_all,
)
from youtube_automation.cli.skills_sync._ops import _has_diff, _prunable_orphan_names


def cmd_diff(args: argparse.Namespace) -> int:
    # CLI 以外 (テスト / 公開 API 直呼び) からの呼び出しに対しても silent な誤動作を防ぐ
    # (asset=all + target 指定なら ValueError)。CLI 経由では _resolve_default_target が
    # 先に catch して exit 2 するため、通常はここまで到達しない。
    _guard_target_with_all(args)
    if args.asset == "all":
        return _diff_all(args)
    spec = _ASSET_SPECS[args.asset]
    root = _asset_root(args.asset)
    target = Path(args.target).resolve()

    if spec["kind"] == "file":
        return _diff_file_asset(spec, root, target)
    if spec["kind"] == "json-merge":
        return _diff_settings_asset(spec, root, target)
    return _diff_dir_asset(spec, root, target)


def _diff_all(args: argparse.Namespace) -> int:
    """全 asset を順次 diff。各 asset の default_target を使う。

    `--target` 指定時は parser 側 (`_resolve_default_target`) で既に error 終了
    しているため、ここでは args.target は必ず None。
    """
    overall_rc = 0
    for i, asset_name in enumerate(sorted(_ASSET_SPECS.keys())):
        if i > 0:
            print()
        print(f"=== [{asset_name}] diff ===")
        sub_args = argparse.Namespace(
            asset=asset_name,
            target=_ASSET_SPECS[asset_name]["default_target"],
        )
        rc = cmd_diff(sub_args)
        if rc != 0:
            overall_rc = rc
    return overall_rc


def _diff_file_asset(spec: dict[str, str], root: Path, target: Path) -> int:
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
    from youtube_automation.cli.skills_sync._settings import merge_unique_strings, missing_hooks, read_json_object

    try:
        template = read_json_object(root / spec["source_filename"])
        current = read_json_object(target, missing_ok=True)
        missing_allow = merge_unique_strings(current, template, "allow")
        missing_deny = merge_unique_strings(current, template, "deny")
        hook_additions = missing_hooks(current, template)
    except (OSError, ValueError) as exc:
        print(f"settings の比較に失敗: {exc}", file=sys.stderr)
        return 1
    if not (missing_allow or missing_deny or hook_additions):
        print("差分なし。必要な settings はすべて存在します。")
        return 0
    for value in missing_allow:
        print(f"  + permissions.allow: {value}")
    for value in missing_deny:
        print(f"  + permissions.deny: {value}")
    for event, group in hook_additions:
        for hook in group["hooks"]:
            print(f"  + hooks.{event}: {group.get('matcher')} / {hook.get('type')} / {hook.get('command')}")
    return 0


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

    if only_bundled:
        print("同梱版にのみ存在 (sync で追加されます):")
        for n in only_bundled:
            print(f"  + {n}")
    if prunable_orphans:
        print("upstream 管理の既知の旧 skill (prune 候補):")
        for n in prunable_orphans:
            print(f"  - {n}")
        print("  (削除するには yt-skills sync --prune --yes を使ってください)")
    if protected_local:
        print("target にのみ存在 (未知のローカル entry として prune から保護されます):")
        for n in protected_local:
            print(f"  - {n}")

    differing: list[str] = []
    for name in common:
        src = root / name
        dst = target_dir / name
        if src.is_dir() and dst.is_dir():
            cmp = filecmp.dircmp(src, dst)
            if _has_diff(cmp):
                differing.append(name)
        elif src.is_file() and dst.is_file():
            if not filecmp.cmp(src, dst, shallow=False):
                differing.append(name)
        else:
            # 種別不一致 (片方が dir、もう片方が file 等) も差分扱い
            differing.append(name)
    if differing:
        print("内容が異なる entry:")
        for n in differing:
            print(f"  ~ {n}")
    if not (only_bundled or only_disk or differing):
        print("差分なし。target は同梱版と一致しています。")
    return 0
