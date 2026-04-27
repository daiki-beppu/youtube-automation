"""yt-skills — Claude Code スキルを downstream リポに同期する。

`uv add git+https://github.com/daiki-beppu/youtube-automation` で本パッケージを
インストールしたあと、`yt-skills sync` を実行することで、wheel に同梱された
配布物 (Claude Code スキル) を任意のチャンネルリポジトリへ展開できる。

Subcommands:
    list   : 同梱アセット一覧を表示
    sync   : --target に展開 (--symlink でシンボリックリンク, --force で上書き)
    diff   : 同梱版と target の差分を表示

Asset 種別 (`--asset`):
    skills : Claude Code スキル (`.claude/skills/`、ディレクトリ単位で 1 entry)

将来別種類の配布物を追加する場合は `_ASSET_SPECS` に entry を追加するだけで
list/sync/diff の各 subcommand が自動的にサポートする。
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from importlib.resources import as_file, files
from pathlib import Path
from typing import Iterable

# asset ごとの wheel resource 名・開発時 fallback・デフォルト target を集約。
# (pyproject.toml の force-include で source_subdir が resource_name/ に同梱される)
_ASSET_SPECS: dict[str, dict[str, str]] = {
    "skills": {
        "resource_name": "_skills",
        "source_subdir": ".claude/skills",
        "default_target": ".claude/skills",
        "label": "スキル",
    },
}


def _editable_root() -> Path:
    """開発時の repo root を返す。テストでは monkeypatch で差し替える。"""
    return Path(__file__).resolve().parents[3]


def _asset_root(asset: str) -> Path:
    """指定 asset の同梱ディレクトリを実体パスとして取得する。

    解決順:
        1. インストール済み wheel の `youtube_automation/<resource_name>/`
        2. リポジトリルート直下の `<source_subdir>/` (editable / 開発時)
    """
    spec = _ASSET_SPECS[asset]  # KeyError on unknown asset

    try:
        resource = files("youtube_automation").joinpath(spec["resource_name"])
        with as_file(resource) as p:
            path = Path(p)
            if path.exists():
                return path
    except (ModuleNotFoundError, FileNotFoundError):
        pass

    src_fallback = _editable_root() / spec["source_subdir"]
    if src_fallback.exists():
        return src_fallback

    raise FileNotFoundError(
        f"youtube_automation の {asset} データが見つかりません "
        f"(wheel 同梱: {spec['resource_name']}, ソース: {spec['source_subdir']})。"
    )


def _list_entries(root: Path) -> list[str]:
    """root 直下の全エントリ (dir / file) を名前ソートで返す。"""
    return sorted(p.name for p in root.iterdir())


def _ensure_target_parent(target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)


def _copy_entry(src: Path, dst: Path, force: bool, dry_run: bool) -> str:
    """単一 entry (ディレクトリ or ファイル) をコピーする。

    戻り値: 'created' | 'skipped'.
    """
    if dst.exists() and not force:
        return "skipped"
    if dry_run:
        return "created"
    if dst.exists():
        if dst.is_dir() and not dst.is_symlink():
            shutil.rmtree(dst)
        else:
            dst.unlink()
    if src.is_dir():
        shutil.copytree(src, dst, symlinks=False)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return "created"


def _symlink_entry(src: Path, dst: Path, force: bool, dry_run: bool) -> str:
    if dst.exists() or dst.is_symlink():
        if not force:
            return "skipped"
        if not dry_run:
            if dst.is_symlink() or dst.is_file():
                dst.unlink()
            else:
                shutil.rmtree(dst)
    if dry_run:
        return "linked"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.symlink_to(src.resolve())
    return "linked"


def cmd_list(args: argparse.Namespace) -> int:
    spec = _ASSET_SPECS[args.asset]
    root = _asset_root(args.asset)
    entries = _list_entries(root)
    print(f"同梱{spec['label']} {len(entries)} 件 (source: {root})")
    for name in entries:
        print(f"  - {name}")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    root = _asset_root(args.asset)
    target_dir = Path(args.target).resolve()
    _ensure_target_parent(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    entries = _list_entries(root)
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

    print()
    print(f"完了: {sum(counts.values())} 件処理 — {counts}")
    if counts.get("skipped"):
        print("  (skipped を上書きするには --force を指定してください)")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    root = _asset_root(args.asset)
    target_dir = Path(args.target).resolve()
    if not target_dir.exists():
        print(f"target が存在しません: {target_dir}", file=sys.stderr)
        return 1

    bundled = set(_list_entries(root))
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


def _has_diff(cmp: filecmp.dircmp) -> bool:
    if cmp.left_only or cmp.right_only or cmp.diff_files or cmp.funny_files:
        return True
    return any(_has_diff(sub) for sub in cmp.subdirs.values())


def _add_asset_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--asset",
        choices=sorted(_ASSET_SPECS.keys()),
        default="skills",
        help="配布対象 (default: skills)",
    )


def _resolve_default_target(args: argparse.Namespace) -> None:
    """`--target` 未指定 (None) 時に `--asset` 別のデフォルトを埋める。"""
    if getattr(args, "target", None) is None:
        args.target = _ASSET_SPECS[args.asset]["default_target"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-skills",
        description=("Claude Code スキル の同期ツール (youtube-channels-automation)"),
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
        help=("展開先ディレクトリ (default: --asset の default_target に従う)"),
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
        help="指定した entry だけ同期 (省略時は全件)",
    )
    p_sync.set_defaults(func=cmd_sync)

    p_diff = sub.add_parser("diff", help="同梱版と target の差分を表示")
    _add_asset_argument(p_diff)
    p_diff.add_argument(
        "--target",
        default=None,
        help=("比較先ディレクトリ (default: --asset の default_target に従う)"),
    )
    p_diff.set_defaults(func=cmd_diff)

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    _resolve_default_target(args)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
