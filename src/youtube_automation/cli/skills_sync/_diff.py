"""`diff` subcommand — 同梱版と target の差分を表示する。"""

from __future__ import annotations

import argparse
import filecmp
import sys
from pathlib import Path

from youtube_automation.cli.skills_sync import _ASSET_SPECS, _asset_root, _list_entries
from youtube_automation.cli.skills_sync._ops import _has_diff


def cmd_diff(args: argparse.Namespace) -> int:
    if args.asset == "all":
        return _diff_all(args)
    spec = _ASSET_SPECS[args.asset]
    root = _asset_root(args.asset)
    target = Path(args.target).resolve()

    if spec["kind"] == "file":
        return _diff_file_asset(spec, root, target)
    return _diff_dir_asset(spec, root, target)


def _diff_all(args: argparse.Namespace) -> int:
    """全 asset を順次 diff。各 asset の default_target を使う。"""
    if args.target is not None:
        print(
            "  [warn] --asset all モードでは --target は無視されます",
            file=sys.stderr,
        )
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


def _diff_dir_asset(spec: dict[str, str], root: Path, target_dir: Path) -> int:
    if not target_dir.exists():
        print(f"target が存在しません: {target_dir}", file=sys.stderr)
        return 1

    bundled = set(_list_entries(root, kind=spec["kind"], source_filename=spec.get("source_filename")))
    on_disk = set(p.name for p in target_dir.iterdir())

    only_bundled = sorted(bundled - on_disk)
    only_disk = sorted(on_disk - bundled)
    common = sorted(bundled & on_disk)

    if only_bundled:
        print("同梱版にのみ存在 (sync で追加されます):")
        for n in only_bundled:
            print(f"  + {n}")
    if only_disk:
        print("target にのみ存在 (sync では削除されません):")
        for n in only_disk:
            print(f"  - {n}")
        print("  (削除するには yt-skills sync --prune --yes を使ってください)")

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
