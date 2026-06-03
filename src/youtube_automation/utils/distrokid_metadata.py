"""30-distrokid `metadata.md`（DistroKid Web フォーム転記用テンプレ）の純パーサ（#819）.

`<collection>/30-distrokid/disc{N}-*/metadata.md` を構造化する。アルバム情報表と
トラック表の 2 ブロックから成り、未記入セルは HTML コメント枠 `<!-- ... -->` で表現される。

- `parse_album_metadata(md_path)` … `## アルバム情報` の `| 項目 | 値 |` 表を canonical key へ写像
- `parse_track_table(md_path)` … `| # | タイトル | ファイル | ... |` 表を行レコードへ

HTTP / payload 組立は呼び出し側（`distrokid_release.py`）の責務。ここは I/O とパースのみ。
"""

from __future__ import annotations

import re
from pathlib import Path

from youtube_automation.utils.exceptions import ConfigError

# アルバム情報表の `項目` ラベル → payload canonical key。
_ALBUM_LABEL_MAP = {
    "アルバムタイトル": "album_title",
    "アーティスト名": "artist",
    "言語": "language",
}
# parse_album_metadata が常に返すキー（呼び出し側が subscript できることを保証）。
_ALBUM_CANONICAL_KEYS = ("album_title", "artist", "language")

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_SEPARATOR_CELL = re.compile(r":?-+:?")


def parse_album_metadata(md_path: Path) -> dict:
    """`## アルバム情報` 表を `{album_title, artist, language, ...}` に写像する.

    HTML コメント枠のみ／空セルは None。canonical key は常に存在する。
    md_path 不在時は ConfigError（fail-loud）。
    """
    rows = _read_table_rows(md_path)
    meta: dict[str, str | None] = dict.fromkeys(_ALBUM_CANONICAL_KEYS, None)
    for cells in rows:
        if len(cells) < 2:
            continue
        key = _ALBUM_LABEL_MAP.get(cells[0])
        if key is not None:
            meta[key] = _clean_cell(cells[1])
    return meta


def parse_track_table(md_path: Path) -> list[dict]:
    """`| # | タイトル | ファイル | ... |` 表を行レコード列に変換する.

    `[{number:int, title:str, filename:str, isrc:str|None}]`。ファイル名のバッククォートは
    除去。`#` 列が数値の行のみ採用し、ヘッダ／区切り行はスキップする。
    md_path 不在時は ConfigError（fail-loud）。
    """
    tracks: list[dict] = []
    for cells in _read_table_rows(md_path):
        if len(cells) < 3 or not cells[0].isdigit():
            continue
        tracks.append(
            {
                "number": int(cells[0]),
                "title": cells[1],
                "filename": cells[2].strip("`"),
                "isrc": _clean_cell(cells[4]) if len(cells) > 4 else None,
            }
        )
    return tracks


def _read_table_rows(md_path: Path) -> list[list[str]]:
    """md ファイルから全 markdown テーブル行（区切り行除く）をセル配列で返す."""
    if not Path(md_path).is_file():
        raise ConfigError(f"metadata.md not found: {md_path}")
    text = Path(md_path).read_text(encoding="utf-8")
    rows: list[list[str]] = []
    for line in text.splitlines():
        cells = _split_table_row(line)
        if cells is not None and not _is_separator(cells):
            rows.append(cells)
    return rows


def _split_table_row(line: str) -> list[str] | None:
    """`| a | b |` 行を ['a', 'b'] に。テーブル行でなければ None."""
    stripped = line.strip()
    if not stripped.startswith("|"):
        return None
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def _is_separator(cells: list[str]) -> bool:
    """`|---|---|` 区切り行か（全セルが `-`/`:` のみ）."""
    return bool(cells) and all(_SEPARATOR_CELL.fullmatch(cell) for cell in cells)


def _clean_cell(raw: str) -> str | None:
    """セル値から HTML コメントを除いた実値を返す（実値が無ければ None）."""
    without_comment = _HTML_COMMENT.sub("", raw).strip()
    return without_comment or None
