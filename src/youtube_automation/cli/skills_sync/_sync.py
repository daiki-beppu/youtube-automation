"""`sync` subcommand — asset を target に展開する。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from youtube_automation.cli.skills_sync import _ASSET_SPECS, _asset_root, _list_entries
from youtube_automation.cli.skills_sync._ops import (
    _copy_entry,
    _ensure_target_parent,
    _prune_orphans,
    _symlink_entry,
)


def cmd_sync(args: argparse.Namespace) -> int:
    if args.asset == "all":
        return _sync_all(args)
    spec = _ASSET_SPECS[args.asset]
    root = _asset_root(args.asset)
    target = Path(args.target).resolve()

    if spec["kind"] == "file":
        return _sync_file_asset(spec, root, target, args)
    return _sync_dir_asset(spec, root, target, args)


def _sync_all(args: argparse.Namespace) -> int:
    """全 asset を順次 sync。各 asset の default_target を使う。"""
    if args.target is not None:
        # all モードでは asset ごとに default_target が違うため --target は無視。
        print(
            "  [warn] --asset all モードでは --target は無視されます (asset ごとの default_target を使用)",
            file=sys.stderr,
        )
    overall_rc = 0
    for i, asset_name in enumerate(sorted(_ASSET_SPECS.keys())):
        if i > 0:
            print()
        print(f"=== [{asset_name}] sync ===")
        # --only / --prune は dir asset (skills) でのみ意味を持つ。
        # それ以外の asset に伝搬すると warning が出るが処理は継続する設計。
        sub_args = argparse.Namespace(
            asset=asset_name,
            target=_ASSET_SPECS[asset_name]["default_target"],
            symlink=args.symlink,
            force=args.force,
            dry_run=args.dry_run,
            only=args.only,
            prune=args.prune,
            yes=args.yes,
        )
        rc = cmd_sync(sub_args)
        if rc != 0:
            overall_rc = rc
    return overall_rc


def _sync_file_asset(
    spec: dict[str, str],
    root: Path,
    target: Path,
    args: argparse.Namespace,
) -> int:
    """単一ファイル asset の sync。target は **ファイルパス** として扱う。"""
    if args.only:
        # file asset は entry が 1 つしかないため --only は意味を成さない。
        # 黙殺せず警告で知らせることで設定ミスに気付けるようにする (sync は継続)。
        print(
            f"  [warn] --only は kind='file' の asset ({args.asset}) では使えません",
            file=sys.stderr,
        )
    if args.prune:
        # prune は target ディレクトリ走査が前提のため kind='file' では適用できない。
        # 黙って無視せず警告で知らせる (sync は継続)。
        print(
            f"  [warn] --prune は kind='file' の asset ({args.asset}) では使えません",
            file=sys.stderr,
        )

    src = root / spec["source_filename"]
    _ensure_target_parent(target)

    op = _symlink_entry if args.symlink else _copy_entry
    result = op(src, target, force=args.force, dry_run=args.dry_run)
    prefix = "[dry-run] " if args.dry_run else ""
    print(f"  {prefix}{result:>8}: {target.name}")

    counts = {result: 1}
    print()
    print(f"完了: {sum(counts.values())} 件処理 — {counts}")
    if result == "skipped":
        print("  (skipped を上書きするには --force を指定してください)")
    return 0


def _sync_dir_asset(
    spec: dict[str, str],
    root: Path,
    target_dir: Path,
    args: argparse.Namespace,
) -> int:
    """ディレクトリ asset の sync。target は **ディレクトリパス** として扱う。"""
    target_dir.mkdir(parents=True, exist_ok=True)

    entries = _list_entries(root, kind=spec["kind"], source_filename=spec.get("source_filename"))
    if args.only:
        only = set(args.only)
        entries = [s for s in entries if s in only]
        missing = only - set(entries)
        for m in sorted(missing):
            print(f"  [warn] 同梱版に含まれません: {m}", file=sys.stderr)

    op = _symlink_entry if args.symlink else _copy_entry
    counts: dict[str, int] = {"created": 0, "updated": 0, "skipped": 0, "linked": 0}
    for name in entries:
        src = root / name
        dst = target_dir / name
        result = op(src, dst, force=args.force, dry_run=args.dry_run)
        counts[result] = counts.get(result, 0) + 1
        prefix = "[dry-run] " if args.dry_run else ""
        print(f"  {prefix}{result:>8}: {name}")

    if args.prune:
        # bundled は **全集合** で判定する (--only でフィルタしない)。
        # `--only` 集合と混同すると bundled の他 entry が誤って prune される。
        bundled = set(_list_entries(root, kind=spec["kind"], source_filename=spec.get("source_filename")))
        do_delete = args.yes and not args.dry_run
        prune_counts = _prune_orphans(target_dir, bundled, do_delete=do_delete)
        for key, val in prune_counts.items():
            counts[key] = counts.get(key, 0) + val

    print()
    print(f"完了: {sum(counts.values())} 件処理 — {counts}")
    if counts.get("skipped"):
        print("  (skipped を上書きするには --force を指定してください)")
    if args.prune and counts.get("would-prune"):
        print("  (実削除には --yes を指定してください)")
    return 0
