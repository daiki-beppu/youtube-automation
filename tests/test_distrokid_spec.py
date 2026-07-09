"""utils/distrokid_spec.py のユニットテスト（#941）.

read_collection_spec / find_disc_entry / title_map_from_entry /
write_collection_spec の各関数を独立して検証する。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.utils.distrokid_spec import (
    SPEC_FILENAME,
    find_disc_entry,
    read_collection_spec,
    title_map_from_entry,
    write_collection_spec,
)
from youtube_automation.utils.exceptions import ConfigError

# ---------------------------------------------------------------------------
# テスト用ヘルパー
# ---------------------------------------------------------------------------


def _minimal_spec(*, discs: list[dict] | None = None) -> dict:
    """最小構成の有効な spec dict を返す."""
    return {
        "version": 1,
        "artist": "Test Artist",
        "language": "English",
        "genre_primary": "Electronic",
        "genre_secondary": None,
        "label": None,
        "discs": discs
        or [
            {
                "slug": "disc1-coding-focus-vol1",
                "album_title": "Coding Focus Vol.1",
                "tracks": [
                    {"filename": "01-x.mp3", "title": "X"},
                    {"filename": "02-y.mp3", "title": "Y"},
                ],
            }
        ],
    }


def _write_spec(distrokid_dir: Path, data: object) -> Path:
    """任意のデータを spec.json として書き込み、パスを返す."""
    spec_path = distrokid_dir / SPEC_FILENAME
    distrokid_dir.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(json.dumps(data), encoding="utf-8")
    return spec_path


# ---------------------------------------------------------------------------
# read_collection_spec: ファイル不在
# ---------------------------------------------------------------------------


def test_read_collection_spec_returns_none_when_absent(tmp_path):
    """Given spec.json が存在しない distrokid_dir
    When read_collection_spec を呼ぶ
    Then None を返す（後方互換フォールバック用）。
    """
    distrokid_dir = tmp_path / "30-distrokid"
    distrokid_dir.mkdir()

    result = read_collection_spec(distrokid_dir)

    assert result is None


# ---------------------------------------------------------------------------
# read_collection_spec: 正常読み取り
# ---------------------------------------------------------------------------


def test_read_collection_spec_returns_dict_when_valid(tmp_path):
    """Given 有効な spec.json
    When read_collection_spec を呼ぶ
    Then spec dict を返す。
    """
    distrokid_dir = tmp_path / "30-distrokid"
    spec = _minimal_spec()
    _write_spec(distrokid_dir, spec)

    result = read_collection_spec(distrokid_dir)

    assert result is not None
    assert result["artist"] == "Test Artist"
    assert len(result["discs"]) == 1


def test_read_collection_spec_contains_expected_fields(tmp_path):
    """Given フル構成の spec.json
    When read_collection_spec を呼ぶ
    Then version / discs / artist / language 各フィールドが読み取れる。
    """
    distrokid_dir = tmp_path / "30-distrokid"
    spec = _minimal_spec()
    _write_spec(distrokid_dir, spec)

    result = read_collection_spec(distrokid_dir)

    assert result["version"] == 1
    assert result["language"] == "English"
    assert isinstance(result["discs"], list)


# ---------------------------------------------------------------------------
# read_collection_spec: 不正 JSON → ConfigError（fail-loud）
# ---------------------------------------------------------------------------


def test_read_collection_spec_raises_on_invalid_json(tmp_path):
    """Given 不正 JSON の spec.json
    When read_collection_spec を呼ぶ
    Then ConfigError を raise する（破損 = バグ、黙った md フォールバック禁止）。
    """
    distrokid_dir = tmp_path / "30-distrokid"
    distrokid_dir.mkdir()
    (distrokid_dir / SPEC_FILENAME).write_text("{ not valid json }", encoding="utf-8")

    with pytest.raises(ConfigError, match="不正な JSON"):
        read_collection_spec(distrokid_dir)


def test_read_collection_spec_raises_on_non_dict_toplevel(tmp_path):
    """Given トップレベルが配列の spec.json
    When read_collection_spec を呼ぶ
    Then ConfigError を raise する（spec のトップレベルは object 契約）。
    """
    distrokid_dir = tmp_path / "30-distrokid"
    _write_spec(distrokid_dir, ["not", "a", "dict"])

    with pytest.raises(ConfigError, match="object ではありません"):
        read_collection_spec(distrokid_dir)


def test_read_collection_spec_raises_on_null_toplevel(tmp_path):
    """Given トップレベルが null の spec.json
    When read_collection_spec を呼ぶ
    Then ConfigError を raise する。
    """
    distrokid_dir = tmp_path / "30-distrokid"
    _write_spec(distrokid_dir, None)

    with pytest.raises(ConfigError):
        read_collection_spec(distrokid_dir)


# ---------------------------------------------------------------------------
# find_disc_entry: slug 一致・不一致
# ---------------------------------------------------------------------------


def test_find_disc_entry_returns_entry_on_slug_match(tmp_path):
    """Given spec に slug が一致するエントリ
    When find_disc_entry を呼ぶ
    Then そのエントリ dict を返す。
    """
    spec = _minimal_spec()
    target_slug = "disc1-coding-focus-vol1"

    entry = find_disc_entry(spec, target_slug)

    assert entry is not None
    assert entry["slug"] == target_slug
    assert entry["album_title"] == "Coding Focus Vol.1"


def test_find_disc_entry_returns_none_when_no_match(tmp_path):
    """Given spec に slug が一致しないエントリしかない
    When find_disc_entry を呼ぶ
    Then None を返す。
    """
    spec = _minimal_spec()

    entry = find_disc_entry(spec, "disc99-nonexistent")

    assert entry is None


def test_find_disc_entry_returns_none_when_discs_absent(tmp_path):
    """Given discs キーが無い spec
    When find_disc_entry を呼ぶ
    Then None を返す（防御的）。
    """
    spec = {"version": 1, "artist": "Test"}

    entry = find_disc_entry(spec, "disc1-x")

    assert entry is None


def test_find_disc_entry_returns_none_when_discs_not_list(tmp_path):
    """Given discs が非 list の spec（破損）
    When find_disc_entry を呼ぶ
    Then None を返す（防御的・ConfigError しない）。
    """
    spec = {"version": 1, "artist": "Test", "discs": "not-a-list"}

    entry = find_disc_entry(spec, "disc1-x")

    assert entry is None


def test_find_disc_entry_returns_correct_entry_from_multi_disc(tmp_path):
    """Given 複数 disc を持つ spec
    When 2 番目の disc の slug で find_disc_entry を呼ぶ
    Then 2 番目のエントリを返す。
    """
    spec = _minimal_spec(
        discs=[
            {"slug": "disc1-alpha-vol1", "album_title": "Alpha Vol.1", "tracks": []},
            {"slug": "disc2-beta-vol2", "album_title": "Beta Vol.2", "tracks": []},
        ]
    )

    entry = find_disc_entry(spec, "disc2-beta-vol2")

    assert entry is not None
    assert entry["album_title"] == "Beta Vol.2"


# ---------------------------------------------------------------------------
# title_map_from_entry: tracks → {filename: title}
# ---------------------------------------------------------------------------


def test_title_map_from_entry_returns_correct_mapping(tmp_path):
    """Given tracks に filename / title がある entry
    When title_map_from_entry を呼ぶ
    Then {filename: title} を返す。
    """
    entry = {
        "slug": "disc1-x",
        "album_title": "X Vol.1",
        "tracks": [
            {"filename": "01-foo.mp3", "title": "Foo"},
            {"filename": "02-bar.mp3", "title": "Bar"},
        ],
    }

    result = title_map_from_entry(entry)

    assert result == {"01-foo.mp3": "Foo", "02-bar.mp3": "Bar"}


def test_title_map_from_entry_skips_missing_filename(tmp_path):
    """Given filename が欠けている track
    When title_map_from_entry を呼ぶ
    Then その行をスキップする。
    """
    entry = {
        "tracks": [
            {"title": "Foo"},  # filename 欠け
            {"filename": "02-bar.mp3", "title": "Bar"},
        ]
    }

    result = title_map_from_entry(entry)

    assert result == {"02-bar.mp3": "Bar"}


def test_title_map_from_entry_skips_missing_title(tmp_path):
    """Given title が欠けている track
    When title_map_from_entry を呼ぶ
    Then その行をスキップする。
    """
    entry = {
        "tracks": [
            {"filename": "01-foo.mp3"},  # title 欠け
            {"filename": "02-bar.mp3", "title": "Bar"},
        ]
    }

    result = title_map_from_entry(entry)

    assert result == {"02-bar.mp3": "Bar"}


def test_title_map_from_entry_returns_empty_when_no_tracks(tmp_path):
    """Given tracks が空 / 不在の entry
    When title_map_from_entry を呼ぶ
    Then 空 dict を返す。
    """
    assert title_map_from_entry({"tracks": []}) == {}
    assert title_map_from_entry({}) == {}
    assert title_map_from_entry({"tracks": "not-a-list"}) == {}


def test_title_map_from_entry_skips_non_dict_track(tmp_path):
    """Given tracks に dict でない要素が混在
    When title_map_from_entry を呼ぶ
    Then 非 dict はスキップし有効行のみ返す。
    """
    entry = {
        "tracks": [
            "not-a-dict",
            {"filename": "01-foo.mp3", "title": "Foo"},
        ]
    }

    result = title_map_from_entry(entry)

    assert result == {"01-foo.mp3": "Foo"}


# ---------------------------------------------------------------------------
# write_collection_spec: atomic 書き込み
# ---------------------------------------------------------------------------


def test_write_collection_spec_creates_file(tmp_path):
    """Given 存在しない distrokid_dir
    When write_collection_spec を呼ぶ
    Then ディレクトリを作成し spec.json を書き込む。
    """
    distrokid_dir = tmp_path / "30-distrokid"
    spec = _minimal_spec()

    write_collection_spec(distrokid_dir, spec)

    spec_path = distrokid_dir / SPEC_FILENAME
    assert spec_path.is_file()
    data = json.loads(spec_path.read_text(encoding="utf-8"))
    assert data["artist"] == "Test Artist"


def test_write_collection_spec_overwrites_existing(tmp_path):
    """Given 既存の spec.json
    When write_collection_spec を呼ぶ
    Then 上書き（冪等）される。
    """
    distrokid_dir = tmp_path / "30-distrokid"
    distrokid_dir.mkdir()
    (distrokid_dir / SPEC_FILENAME).write_text('{"old": true}', encoding="utf-8")

    spec = _minimal_spec()
    write_collection_spec(distrokid_dir, spec)

    data = json.loads((distrokid_dir / SPEC_FILENAME).read_text(encoding="utf-8"))
    assert data["artist"] == "Test Artist"
    assert "old" not in data


def test_write_collection_spec_leaves_no_temp_file(tmp_path):
    """Given write_collection_spec の atomic write
    When 書き込み後に distrokid_dir を列挙する
    Then 中間 temp ファイルが残らず spec.json のみが存在する。
    """
    distrokid_dir = tmp_path / "30-distrokid"
    spec = _minimal_spec()

    write_collection_spec(distrokid_dir, spec)

    files = sorted(p.name for p in distrokid_dir.iterdir())
    assert files == [SPEC_FILENAME]


def test_write_and_read_roundtrip(tmp_path):
    """Given write_collection_spec で書いた spec
    When read_collection_spec で読み直す
    Then 元の spec と等しい。
    """
    distrokid_dir = tmp_path / "30-distrokid"
    spec = _minimal_spec()

    write_collection_spec(distrokid_dir, spec)
    result = read_collection_spec(distrokid_dir)

    assert result == spec
