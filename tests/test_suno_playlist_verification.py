"""Playlist × suno-prompts.json 突合ゲートのテスト."""

from __future__ import annotations

import json

import pytest

from youtube_automation.utils.exceptions import ValidationError
from youtube_automation.utils.suno_playlist_verification import (
    load_entry_names,
    normalize_title,
    verify_playlist_titles,
)

ENTRIES = [
    "灯りを落として — Dim the Lights",
    "深呼吸ひとつ — One Deep Breath",
    "休んでいい — You're Allowed to Rest",
]


def test_all_matched_two_clips_each_is_ok():
    """Given 全 entry が 2 clip ずつ playlist に存在する
    When 突合する
    Then ok=True で unknown / missing / underfilled が空。
    """
    titles = [name for name in ENTRIES for _ in range(2)]
    result = verify_playlist_titles(ENTRIES, titles)
    assert result.ok
    assert dict(result.matched) == {name: 2 for name in ENTRIES}
    assert result.unknown_titles == ()
    assert result.missing_entries == ()
    assert result.underfilled_entries == ()


def test_foreign_title_is_reported_as_unknown():
    """Given 前コレクション由来の曲名が混入した playlist
    When 突合する
    Then 混入曲が unknown_titles に載り ok=False。
    """
    titles = [name for name in ENTRIES for _ in range(2)]
    titles.append("ゆるやかな午後 — Slow Afternoon")
    result = verify_playlist_titles(ENTRIES, titles)
    assert not result.ok
    assert result.unknown_titles == ("ゆるやかな午後 — Slow Afternoon",)
    assert result.missing_entries == ()


def test_absent_entry_is_reported_as_missing():
    """Given 未生成 entry が 1 件ある playlist
    When 突合する
    Then その entry が missing_entries に載り ok=False。
    """
    titles = [name for name in ENTRIES[:2] for _ in range(2)]
    result = verify_playlist_titles(ENTRIES, titles)
    assert not result.ok
    assert result.missing_entries == (ENTRIES[2],)


def test_single_clip_entry_is_reported_as_underfilled():
    """Given ある entry の clip が 1 つしか無い
    When expected_clips_per_entry=2 で突合する
    Then underfilled_entries に載り ok=False。
    """
    titles = [name for name in ENTRIES for _ in range(2)]
    titles.remove(ENTRIES[0])
    result = verify_playlist_titles(ENTRIES, titles)
    assert not result.ok
    assert result.underfilled_entries == (ENTRIES[0],)


def test_expected_clips_zero_disables_underfilled_check():
    """Given expected_clips_per_entry=0
    When 各 entry 1 clip の playlist を突合する
    Then 不足チェックが無効化され ok=True。
    """
    result = verify_playlist_titles(ENTRIES, list(ENTRIES), expected_clips_per_entry=0)
    assert result.ok


def test_normalization_absorbs_whitespace_case_and_nfkc():
    """Given 空白ゆれ・大文字小文字・全角ゆれのあるタイトル
    When 突合する
    Then 同一 entry として一致する。
    """
    assert normalize_title("  灯りを落として   —  DIM THE LIGHTS ") == normalize_title(
        "灯りを落として — Dim the Lights"
    )
    titles = ["灯りを落として  —  DIM THE LIGHTS"] * 2
    result = verify_playlist_titles(ENTRIES[:1], titles)
    assert result.ok


def test_colliding_entry_names_after_normalization_fail_loud():
    """Given 正規化後に衝突する 2 つの entry name
    When 突合する
    Then ValidationError で停止する。
    """
    with pytest.raises(ValidationError):
        verify_playlist_titles(["Song  A", "song a"], ["Song A"])


def test_load_entry_names_reads_prompts_json(tmp_path):
    """Given 正常な suno-prompts.json
    When load_entry_names する
    Then entry name の一覧が返る。
    """
    doc = tmp_path / "20-documentation"
    doc.mkdir()
    (doc / "suno-prompts.json").write_text(
        json.dumps([{"name": n, "style": "s", "lyrics": "l"} for n in ENTRIES], ensure_ascii=False),
        encoding="utf-8",
    )
    assert load_entry_names(tmp_path) == ENTRIES


def test_load_entry_names_fails_on_missing_name(tmp_path):
    """Given name 欠落 entry を含む suno-prompts.json
    When load_entry_names する
    Then ValidationError で停止する。
    """
    doc = tmp_path / "20-documentation"
    doc.mkdir()
    (doc / "suno-prompts.json").write_text(json.dumps([{"style": "s"}]), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_entry_names(tmp_path)
