"""番号付き重複ファイル (bounced file name) の検知。

macOS の iCloud Drive は同期コンフリクト時に `abc.txt` → `abc 2.txt` の
"bounced file name" (Apple TN2336) を生成する。uv / yt-skills sync は
この「スペース + 連番」形式を生成しないため、`.venv/bin/` や
`.claude/skills/` にこの形式が現れたら同期サービス起因の汚染とみなせる
(原因調査: issue #1409)。本モジュールは検知のみを担い、削除は行わない。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# `yt-analytics 2` / `SKILL 2.md` / `abc.tar 2.gz` にマッチする。
# iCloud の bounce は 2 始まりの連番なので 1 は除外する ("chapter 1.md" 等の
# 正当なファイル名を誤検知しないため)。suffix は最終拡張子のみ (bounce は
# 最終拡張子の直前に連番を挿入する)。
_NUMBERED_NAME_RE = re.compile(r"^(?P<stem>.*\S) (?P<number>[2-9]|[1-9]\d+)(?P<suffix>\.[^ .]+)?$")
_MAX_DISPLAY_NAME_LEN = 120
CLEANUP_GUIDE_URL = (
    "https://github.com/daiki-beppu/youtube-automation/blob/main/docs/migration/numbered-duplicate-files-cleanup.md"
)


@dataclass(frozen=True)
class NumberedDuplicateScanError:
    """番号付き重複検知で走査できなかった場所。"""

    path: Path
    reason: str


@dataclass(frozen=True)
class NumberedDuplicateScan:
    """番号付き重複検知の結果。"""

    duplicates: tuple[Path, ...]
    errors: tuple[NumberedDuplicateScanError, ...]


def numbered_duplicate_base_name(name: str) -> str | None:
    """bounced file name なら bounce 元のファイル名を返す。それ以外は None。"""
    m = _NUMBERED_NAME_RE.match(name)
    if m is None:
        return None
    return m.group("stem") + (m.group("suffix") or "")


def scan_numbered_duplicates(
    root: Path,
    *,
    recursive: bool = False,
    root_boundary: Path | None = None,
) -> NumberedDuplicateScan:
    """番号付き重複を列挙し、走査失敗を `errors` として返す。

    root が存在しない場合は「対象なし」として clean 扱いにする。root 自体が
    symlink の場合は、チャンネルリポジトリ外の巨大ディレクトリ走査やファイル名
    露出を防ぐため走査しない。
    """
    errors: list[NumberedDuplicateScanError] = []
    found: list[Path] = []

    if root.is_symlink():
        return NumberedDuplicateScan(
            duplicates=(),
            errors=(NumberedDuplicateScanError(root, "scan root is a symlink"),),
        )
    if not root.is_dir():
        return NumberedDuplicateScan(duplicates=(), errors=())
    if root_boundary is not None:
        try:
            root.resolve(strict=True).relative_to(root_boundary.resolve(strict=True))
        except (OSError, ValueError) as exc:
            return NumberedDuplicateScan(
                duplicates=(),
                errors=(NumberedDuplicateScanError(root, f"scan root is outside channel_dir: {exc}"),),
            )

    _scan(root, recursive=recursive, found=found, errors=errors)
    return NumberedDuplicateScan(duplicates=tuple(found), errors=tuple(errors))


def format_duplicate_name(path: Path) -> str:
    """CLI 出力用に制御文字を escape した短いファイル名を返す。"""
    name = ascii(path.name)[1:-1]
    return _truncate_display_text(name)


def format_scan_error_reason(reason: str) -> str:
    """CLI 出力用に scan error reason の制御文字を escape する。"""
    return _truncate_display_text(ascii(reason)[1:-1])


def _truncate_display_text(text: str) -> str:
    if len(text) <= _MAX_DISPLAY_NAME_LEN:
        return text
    return text[: _MAX_DISPLAY_NAME_LEN - 3] + "..."


def _scan(
    directory: Path,
    *,
    recursive: bool,
    found: list[Path],
    errors: list[NumberedDuplicateScanError],
) -> None:
    try:
        entries = sorted(directory.iterdir())
    except OSError as exc:
        errors.append(NumberedDuplicateScanError(directory, str(exc)))
        return
    names = {entry.name for entry in entries}
    for entry in entries:
        base_name = numbered_duplicate_base_name(entry.name)
        if base_name is not None and base_name in names:
            found.append(entry)
            continue
        if recursive and _should_descend(entry, errors):
            _scan(entry, recursive=recursive, found=found, errors=errors)


def _should_descend(entry: Path, errors: list[NumberedDuplicateScanError]) -> bool:
    try:
        return entry.is_dir() and not entry.is_symlink()
    except OSError as exc:
        errors.append(NumberedDuplicateScanError(entry, str(exc)))
        return False
