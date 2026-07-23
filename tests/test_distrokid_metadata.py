"""`domains.distrokid.metadata` パーサのユニットテスト（#819）.

30-distrokid 構造の `metadata.md`（DistroKid Web フォーム転記用テンプレ）を
構造化する純パーサの契約を pin する。下流リポ（soulful-grooves）の実フォーマットに
基づくが、フィクスチャは tmp_path で自己完結させる（本リポに下流データは無い）。

契約（draft が実装すべき public API）:
- `parse_album_metadata(md_path: Path) -> dict`
    `## アルバム情報` の `| 項目 | 値 |` 表を canonical key へ写像。
    HTML コメント枠 `<!-- ... -->` のみ／空セルは None。
    キー `album_title` / `artist` / `language` は常に存在する。
- `parse_track_table(md_path: Path) -> list[dict]`
    `| # | タイトル | ファイル | ... |` 表を
    `[{number:int, title:str, filename:str, isrc:str|None}]` に。
    ファイル名セルのバッククォートは除去。区切り行（`|---|`）はスキップ。
- md_path 不在時は ConfigError（fail-loud）。
"""

from __future__ import annotations

import pytest

from youtube_automation.domains.distrokid.metadata import (
    parse_album_metadata,
    parse_track_table,
)
from youtube_automation.utils.exceptions import ConfigError

# 下流 disc1-coding-focus-vol1/metadata.md のトラック表に対応する代表サンプル。
# (number, title, filename, duration) ／ ISRC・作詞・作曲は空欄運用。
_SAMPLE_TRACKS = [
    (1, "Slip Right Through", "01-slip-right-through.mp3", "3:18"),
    (2, "Easy Release", "02-easy-release.mp3", "3:14"),
    (3, "Easy Release — Reprise", "03-easy-release.mp3", "2:59"),
    (4, "Slip Right Through — Reprise", "04-slip-right-through.mp3", "3:33"),
]


def _album_value(value: str | None) -> str:
    """アルバム情報セルの値。None なら HTML コメント枠（実テンプレの未記入状態）。"""
    return "<!-- 例: 記入例 -->" if value is None else value


def _track_row(number: int, title: str, filename: str, duration: str, isrc: str = "") -> str:
    """トラック表の 1 行（ファイル名はバッククォート囲み・実フォーマット準拠）。"""
    return f"| {number} | {title} | `{filename}` | {duration} | {isrc} |  |  |"


def _write_metadata(
    md_path,
    *,
    album_title: str | None = None,
    artist: str | None = None,
    language: str | None = "Instrumental",
    tracks=_SAMPLE_TRACKS,
):
    """実フォーマット（アルバム情報表 + トラック表）の metadata.md を tmp に書く。"""
    lines = [
        "# DistroKid 入力メタデータ — サンプル",
        "",
        "> 転記用テンプレ。`<!-- ... -->` を実値に書き換える。",
        "",
        "## アルバム情報",
        "",
        "| 項目 | 値 |",
        "|------|-----|",
        f"| アルバムタイトル | {_album_value(album_title)} |",
        f"| アーティスト名 | {_album_value(artist)} |",
        f"| 言語 | {_album_value(language)} |",
        "| Explicit | No |",
        "| カバーアート | `../cover_art_3000.jpg` (3000×3000 JPEG) |",
        "",
        f"## トラックリスト (1-{len(tracks)}, 全 {len(tracks)} 曲)",
        "",
        "| # | タイトル | ファイル | 尺 | ISRC (任意) | 作詞 | 作曲 |",
        "|---|---------|---------|----|------------|------|------|",
        *[_track_row(*t) for t in tracks],
        "",
        "### 補足",
        "- ISRC は空欄なら DistroKid が自動発行する",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


# ---------------------------------------------------------------------------
# parse_album_metadata
# ---------------------------------------------------------------------------


def test_parse_album_metadata_html_comment_cells_are_none(tmp_path):
    """Given アルバムタイトル／アーティスト名が HTML コメント枠のみ
    When parse_album_metadata
    Then それぞれ None（未記入扱い）。
    """
    md = _write_metadata(tmp_path / "metadata.md", album_title=None, artist=None)

    meta = parse_album_metadata(md)

    assert meta["album_title"] is None
    assert meta["artist"] is None


def test_parse_album_metadata_extracts_real_language(tmp_path):
    """Given 言語セルに実値 `Instrumental`
    When parse_album_metadata
    Then language は `Instrumental`（HTML コメントでない実値は素通し）。
    """
    md = _write_metadata(tmp_path / "metadata.md", language="Instrumental")

    assert parse_album_metadata(md)["language"] == "Instrumental"


def test_parse_album_metadata_extracts_filled_album_title(tmp_path):
    """Given アルバムタイトルが実値で埋まっている
    When parse_album_metadata
    Then その値を返す。
    """
    md = _write_metadata(tmp_path / "metadata.md", album_title="Coding Focus Vol.1")

    assert parse_album_metadata(md)["album_title"] == "Coding Focus Vol.1"


def test_parse_album_metadata_always_includes_canonical_keys(tmp_path):
    """Given 標準テンプレ
    When parse_album_metadata
    Then album_title / artist / language キーが常に存在する（subscript 前提）。
    """
    md = _write_metadata(tmp_path / "metadata.md")

    meta = parse_album_metadata(md)

    assert {"album_title", "artist", "language"} <= set(meta)


def test_parse_album_metadata_missing_file_raises_config_error(tmp_path):
    """Given 不在の metadata.md
    When parse_album_metadata
    Then ConfigError（silent に進めず fail-loud）。
    """
    with pytest.raises(ConfigError):
        parse_album_metadata(tmp_path / "does-not-exist.md")


# ---------------------------------------------------------------------------
# parse_track_table
# ---------------------------------------------------------------------------


def test_parse_track_table_returns_row_per_track(tmp_path):
    """Given 4 行のトラック表
    When parse_track_table
    Then 行数分のレコードを返し、区切り行（|---|）は含めない。
    """
    md = _write_metadata(tmp_path / "metadata.md")

    rows = parse_track_table(md)

    assert len(rows) == len(_SAMPLE_TRACKS)


def test_parse_track_table_strips_backticks_from_filename(tmp_path):
    """Given ファイル名がバッククォート囲み
    When parse_track_table
    Then filename はバッククォートを除いた裸のファイル名。
    """
    md = _write_metadata(tmp_path / "metadata.md")

    first = parse_track_table(md)[0]

    assert first["filename"] == "01-slip-right-through.mp3"


def test_parse_track_table_preserves_title_case_and_em_dash(tmp_path):
    """Given em-dash バリエーション付きタイトル
    When parse_track_table
    Then Title Case と em-dash をそのまま保持する。
    """
    md = _write_metadata(tmp_path / "metadata.md")

    rows = parse_track_table(md)

    assert rows[0]["title"] == "Slip Right Through"
    assert rows[3]["title"] == "Slip Right Through — Reprise"


def test_parse_track_table_number_is_int(tmp_path):
    """Given `#` 列に数値
    When parse_track_table
    Then number は int 型。
    """
    md = _write_metadata(tmp_path / "metadata.md")

    assert parse_track_table(md)[0]["number"] == 1
    assert isinstance(parse_track_table(md)[0]["number"], int)


def test_parse_track_table_empty_isrc_is_none(tmp_path):
    """Given ISRC 列が空欄
    When parse_track_table
    Then isrc は None。
    """
    md = _write_metadata(tmp_path / "metadata.md")

    assert parse_track_table(md)[0]["isrc"] is None


def test_parse_track_table_extracts_filled_isrc(tmp_path):
    """Given ISRC 列に実値
    When parse_track_table
    Then その値を返す（空欄のみ None 扱い）。
    """
    md = _write_metadata(
        tmp_path / "metadata.md",
        tracks=[(1, "Slip Right Through", "01-slip-right-through.mp3", "3:18", "USABC1234567")],
    )

    assert parse_track_table(md)[0]["isrc"] == "USABC1234567"


def test_parse_track_table_missing_file_raises_config_error(tmp_path):
    """Given 不在の metadata.md
    When parse_track_table
    Then ConfigError（fail-loud）。
    """
    with pytest.raises(ConfigError):
        parse_track_table(tmp_path / "does-not-exist.md")
