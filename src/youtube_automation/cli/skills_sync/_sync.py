"""`sync` subcommand — asset を target に展開する。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from youtube_automation.cli.skills_sync import (
    _ASSET_SPECS,
    _asset_root,
    _guard_target_with_all,
    _list_entries,
)
from youtube_automation.cli.skills_sync._ops import (
    _copy_entry,
    _ensure_agents_skills_symlink,
    _ensure_target_parent,
    _prune_orphans,
    _symlink_entry,
)
from youtube_automation.utils.numbered_duplicates import (
    CLEANUP_GUIDE_URL,
    format_duplicate_name,
    format_scan_error_reason,
    scan_numbered_duplicates,
)


def _warn_numbered_duplicates(target_dir: Path) -> bool:
    """sync 先に混入した番号付き重複 (iCloud bounce) を警告する。削除はしない。

    sync は既存 entry を skip / --force で上書きするだけで重複を生成も除去も
    しないため、混入に気づく機会をここで提供する (#1409 / #1410)。
    """
    result = scan_numbered_duplicates(target_dir, recursive=True)
    warned = False
    if result.duplicates:
        sample = ", ".join(format_duplicate_name(path) for path in result.duplicates[:5])
        print(
            f"  [warn] sync 先に番号付き重複ファイルを検出: {len(result.duplicates)} 件 (例: {sample})\n"
            "         iCloud Drive 等のクラウド同期コンフリクトで生成された可能性があります。\n"
            f"         対処手順: {CLEANUP_GUIDE_URL} (yt-doctor でも検知できます)",
            file=sys.stderr,
        )
        warned = True
    for error in result.errors:
        print(
            "  [warn] sync 先の番号付き重複ファイル検査に失敗: "
            f"{format_duplicate_name(error.path)} ({format_scan_error_reason(error.reason)})",
            file=sys.stderr,
        )
        warned = True
    return warned


def cmd_sync(args: argparse.Namespace) -> int:
    # CLI 以外 (テスト / 公開 API 直呼び) から呼ばれても silent な誤動作にならないよう
    # 入口でガードする (asset=all + target 指定なら ValueError)。CLI 経由では
    # _resolve_default_target が先に ValueError を catch して exit 2 するため、
    # 通常はここまで到達しない。直呼び caller は ValueError を try/except で扱える。
    _guard_target_with_all(args)
    if args.asset == "all":
        return _sync_all(args)
    spec = _ASSET_SPECS[args.asset]
    root = _asset_root(args.asset)
    target = Path(args.target).resolve()

    if spec["kind"] == "file":
        return _sync_file_asset(spec, root, target, args)
    return _sync_dir_asset(spec, root, target, args)


def _sync_all(args: argparse.Namespace) -> int:
    """全 asset を順次 sync。各 asset の default_target を使う。

    `--target` 指定時は parser 側 (`_resolve_default_target`) で既に error 終了
    しているため、ここでは args.target は必ず None。
    """
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
    warned_numbered_duplicates = _warn_numbered_duplicates(target_dir)

    all_entries = _list_entries(root, kind=spec["kind"], source_filename=spec.get("source_filename"))
    entries = list(all_entries)
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
        bundled = set(all_entries)
        do_delete = args.yes and not args.dry_run
        prune_counts = _prune_orphans(target_dir, bundled, do_delete=do_delete)
        for key, val in prune_counts.items():
            counts[key] = counts.get(key, 0) + val

    # skills 配布時は Codex CLI の探索パス `.agents/skills` も併設する。
    # 標準レイアウト (`.claude/skills`) でないときは対象外 (None) でスキップ。
    rc = 0
    if args.asset == "skills":
        mirror = _ensure_agents_skills_symlink(target_dir, force=args.force, dry_run=args.dry_run)
        prefix = "[dry-run] " if args.dry_run else ""
        if mirror == "unsupported":
            # symlink 機能自体がない環境 (Windows 非特権ユーザー等)。警告のみで継続。
            print(
                "  [warn] .agents/skills の symlink を作成できませんでした (symlink 非対応環境)",
                file=sys.stderr,
            )
        elif mirror == "permission-denied":
            # 権限エラーは silent 化せず非ゼロ rc で明示的に失敗させる。
            # ユーザーが手動で復旧できる情報 (link コマンド) を案内する。
            link_path = target_dir.parent.parent / ".agents" / "skills"
            print(
                "  [error] .agents/skills の symlink 作成が権限エラーで失敗しました\n"
                f"          link 先: {link_path}\n"
                "          Codex CLI のスキル探索パス (.agents/skills) が無いため、\n"
                "          このまま放置すると Codex から同期済みスキルが見えません。\n"
                "          手動で復旧する場合は以下を実行してください:\n"
                f"            mkdir -p {link_path.parent}\n"
                f"            ln -s ../.claude/skills {link_path}\n"
                "          または sudo / 適切な権限で `yt-skills sync --asset skills --force` を再実行してください。",
                file=sys.stderr,
            )
            counts["error"] = counts.get("error", 0) + 1
            rc = 1
        elif mirror is not None:
            print(f"  {prefix}{mirror:>8}: .agents/skills -> ../.claude/skills")
            counts[mirror] = counts.get(mirror, 0) + 1

    if not warned_numbered_duplicates:
        _warn_numbered_duplicates(target_dir)

    print()
    print(f"完了: {sum(counts.values())} 件処理 — {counts}")
    if counts.get("skipped"):
        print("  (skipped を上書きするには --force を指定してください)")
    if args.prune and counts.get("would-prune"):
        print("  (実削除には --yes を指定してください)")
    return rc
