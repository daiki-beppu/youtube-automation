"""番号付き重複ファイル (bounced file name) の検知。

macOS の iCloud Drive は同期コンフリクト時に `abc.txt` → `abc 2.txt` の
"bounced file name" (Apple TN2336) を生成する。uv / yt-skills sync は
この「スペース + 連番」形式を生成しないため、`.venv/bin/` や
`.claude/skills/` にこの形式が現れたら同期サービス起因の汚染とみなせる
(原因調査: issue #1409)。本モジュールは検知のみを担い、削除は行わない。
"""

from __future__ import annotations

import re
from pathlib import Path

# `yt-analytics 2` / `SKILL 2.md` / `abc.tar 2.gz` にマッチする。
# iCloud の bounce は 2 始まりの連番なので 1 は除外する ("chapter 1.md" 等の
# 正当なファイル名を誤検知しないため)。suffix は最終拡張子のみ (bounce は
# 最終拡張子の直前に連番を挿入する)。
_NUMBERED_NAME_RE = re.compile(r"^(?P<stem>.*\S) (?P<number>[2-9]|[1-9]\d+)(?P<suffix>\.[^ .]+)?$")


def numbered_duplicate_base_name(name: str) -> str | None:
    """bounced file name なら bounce 元のファイル名を返す。それ以外は None。"""
    m = _NUMBERED_NAME_RE.match(name)
    if m is None:
        return None
    return m.group("stem") + (m.group("suffix") or "")


def find_numbered_duplicates(root: Path, *, recursive: bool = False) -> list[Path]:
    """root 配下の番号付き重複エントリ (ファイル / ディレクトリ) を列挙する。

    bounce 元 (連番を除いた名前) が同じディレクトリに実在するものだけを
    重複と判定し、命名がたまたま似ている正当なファイルの誤検知を防ぐ。
    bounce されたディレクトリは 1 エントリとして数え、その配下には降りない。
    """
    if not root.is_dir():
        return []
    found: list[Path] = []
    _scan(root, recursive=recursive, found=found)
    return found


def _scan(directory: Path, *, recursive: bool, found: list[Path]) -> None:
    try:
        entries = sorted(directory.iterdir())
    except OSError:
        return
    names = {entry.name for entry in entries}
    for entry in entries:
        base_name = numbered_duplicate_base_name(entry.name)
        if base_name is not None and base_name in names:
            found.append(entry)
            continue
        if recursive and entry.is_dir() and not entry.is_symlink():
            _scan(entry, recursive=recursive, found=found)
