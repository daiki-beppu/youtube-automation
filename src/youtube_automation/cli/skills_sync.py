"""yt-skills — Claude Code スキルファイルを cwd の .claude/skills/ に同期する。

`uv add git+https://github.com/daiki-beppu/youtube-automation` で本パッケージを
インストールしたあと、`yt-skills sync` を実行することで、パッケージに同梱された
.claude/skills/ 28 個を任意のチャンネルリポジトリに展開できる。

Subcommands:
    list   : 同梱スキル一覧を表示
    sync   : .claude/skills/ にコピー (--symlink でシンボリックリンク, --force で上書き)
    diff   : 同梱版と target の差分を表示
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from importlib.resources import as_file, files
from pathlib import Path
from typing import Iterable


def _skills_root() -> Path:
    """パッケージ同梱のスキルディレクトリを実体パスとして取得する。

    解決順:
        1. インストール済み wheel の `youtube_automation/_skills/` (force-include 同梱)
        2. ソースツリー直下の `.claude/skills/` (editable install / 開発時)
    """
    try:
        resource = files("youtube_automation").joinpath("_skills")
        with as_file(resource) as p:
            path = Path(p)
            if path.exists():
                return path
    except (ModuleNotFoundError, FileNotFoundError):
        pass

    # Fallback: ソースツリー (.../src/youtube_automation/cli/skills_sync.py から 4 階層上)
    src_fallback = Path(__file__).resolve().parents[3] / ".claude" / "skills"
    if src_fallback.exists():
        return src_fallback

    raise FileNotFoundError(
        "youtube_automation の skills データが見つかりません。"
        "wheel が壊れているか editable install のソースツリーから実行してください。"
    )


def _list_skills(root: Path) -> list[str]:
    return sorted(d.name for d in root.iterdir() if d.is_dir())


def _ensure_target_parent(target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)


def _copy_skill(src: Path, dst: Path, force: bool, dry_run: bool) -> str:
    """単一スキルをコピーする。戻り値: 'created' | 'updated' | 'skipped'."""
    if dst.exists():
        if not force:
            return "skipped"
        if not dry_run:
            shutil.rmtree(dst)
    if dry_run:
        return "created" if not dst.exists() else "updated"
    shutil.copytree(src, dst, symlinks=False)
    return "created"


def _symlink_skill(src: Path, dst: Path, force: bool, dry_run: bool) -> str:
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
    dst.symlink_to(src.resolve())
    return "linked"


def cmd_list(args: argparse.Namespace) -> int:
    root = _skills_root()
    skills = _list_skills(root)
    print(f"同梱スキル {len(skills)} 件 (source: {root})")
    for name in skills:
        print(f"  - {name}")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    root = _skills_root()
    target_dir = Path(args.target).resolve()
    _ensure_target_parent(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    skills = _list_skills(root)
    if args.only:
        only = set(args.only)
        skills = [s for s in skills if s in only]
        missing = only - set(skills)
        for m in sorted(missing):
            print(f"  [warn] 同梱スキルに含まれません: {m}", file=sys.stderr)

    op = _symlink_skill if args.symlink else _copy_skill
    counts: dict[str, int] = {"created": 0, "updated": 0, "skipped": 0, "linked": 0}
    for name in skills:
        src = root / name
        dst = target_dir / name
        result = op(src, dst, force=args.force, dry_run=args.dry_run)
        counts[result] = counts.get(result, 0) + 1
        prefix = "[dry-run] " if args.dry_run else ""
        print(f"  {prefix}{result:>8}: {name}")

    print()
    print(f"完了: {sum(counts.values())} 件処理 — {counts}")
    if counts.get("skipped"):
        print("  (skipped されたスキルを上書きするには --force を指定してください)")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    root = _skills_root()
    target_dir = Path(args.target).resolve()
    if not target_dir.exists():
        print(f"target が存在しません: {target_dir}", file=sys.stderr)
        return 1

    bundled = set(_list_skills(root))
    on_disk = set(d.name for d in target_dir.iterdir() if d.is_dir())

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
        cmp = filecmp.dircmp(root / name, target_dir / name)
        if _has_diff(cmp):
            differing.append(name)
    if differing:
        print("内容が異なるスキル:")
        for n in differing:
            print(f"  ~ {n}")
    if not (only_bundled or only_disk or differing):
        print("差分なし。target は同梱版と一致しています。")
    return 0


def _has_diff(cmp: filecmp.dircmp) -> bool:
    if cmp.left_only or cmp.right_only or cmp.diff_files or cmp.funny_files:
        return True
    return any(_has_diff(sub) for sub in cmp.subdirs.values())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-skills",
        description="Claude Code スキルファイルの同期ツール (youtube-channels-automation)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="同梱スキル一覧を表示")
    p_list.set_defaults(func=cmd_list)

    p_sync = sub.add_parser("sync", help="スキルを target に展開")
    p_sync.add_argument(
        "--target",
        default=".claude/skills",
        help="展開先ディレクトリ (default: .claude/skills)",
    )
    p_sync.add_argument(
        "--symlink",
        action="store_true",
        help="コピーではなくシンボリックリンクで展開する (開発者向け)",
    )
    p_sync.add_argument(
        "--force",
        action="store_true",
        help="既存スキルを上書きする",
    )
    p_sync.add_argument(
        "--dry-run",
        action="store_true",
        help="実際には書き込まず処理予定だけ表示する",
    )
    p_sync.add_argument(
        "--only",
        nargs="+",
        metavar="SKILL",
        help="指定したスキルだけ同期 (省略時は全件)",
    )
    p_sync.set_defaults(func=cmd_sync)

    p_diff = sub.add_parser("diff", help="同梱版と target の差分を表示")
    p_diff.add_argument(
        "--target",
        default=".claude/skills",
        help="比較先ディレクトリ (default: .claude/skills)",
    )
    p_diff.set_defaults(func=cmd_diff)

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
