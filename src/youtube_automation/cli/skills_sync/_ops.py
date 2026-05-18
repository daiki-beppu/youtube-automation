"""FS プリミティブ — `cmd_sync` と `cmd_diff` で共用される低レイヤ操作。

`pathlib` / `shutil` / `filecmp` のラッパー責務に閉じる。
- `_ensure_target_parent`: 親ディレクトリの作成
- `_copy_entry` / `_symlink_entry`: 単一 entry の配置
- `_prune_orphans`: 同梱外 entry の列挙・削除
- `_has_diff`: `filecmp.dircmp` の再帰的差分検出
"""

from __future__ import annotations

import filecmp
import shutil
from pathlib import Path


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


def _prune_orphans(
    target_dir: Path,
    bundled: set[str],
    *,
    do_delete: bool,
) -> dict[str, int]:
    """target_dir 直下で bundled に含まれない entry を列挙し、do_delete=True なら削除する。

    戻り値: {"pruned": N} (実削除時) または {"would-prune": N} (列挙のみ)。
    `iterdir()` は broken symlink も列挙するため、symlink → dir → file の順で判定する。
    """
    label = "pruned" if do_delete else "would-prune"
    count = 0
    for entry in sorted(target_dir.iterdir(), key=lambda p: p.name):
        if entry.name in bundled:
            continue
        count += 1
        print(f"  {label:>8}: {entry.name}")
        if do_delete:
            if entry.is_symlink():
                entry.unlink()
            elif entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
    return {label: count} if count else {}


def _has_diff(cmp: filecmp.dircmp) -> bool:
    if cmp.left_only or cmp.right_only or cmp.diff_files or cmp.funny_files:
        return True
    return any(_has_diff(sub) for sub in cmp.subdirs.values())
