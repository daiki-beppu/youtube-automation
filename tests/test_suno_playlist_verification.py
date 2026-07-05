"""Playlist × suno-prompts.json 突合ゲートのテスト."""

from __future__ import annotations

import json
import sys
from io import StringIO

import pytest

from youtube_automation.scripts import suno_verify_playlist
from youtube_automation.utils.exceptions import ValidationError
from youtube_automation.utils.suno_playlist_verification import (
    format_verification_report,
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


def test_exact_duplicate_entry_names_fail_loud():
    """Given 完全に同じ entry name が重複する
    When 突合する
    Then dict 集約で潰さず ValidationError で停止する。
    """
    with pytest.raises(ValidationError):
        verify_playlist_titles(["Song A", "Song A"], ["Song A", "Song A"])


def test_extended_suffix_is_not_stripped_by_normalization():
    """Given [Extended] suffix 付きの別タイトル
    When 正規化する
    Then suffix を暗黙削除せず別タイトルとして扱う。
    """
    assert normalize_title("Song A [Extended]") != normalize_title("Song A")
    result = verify_playlist_titles(["Song A"], ["Song A [Extended]"])
    assert not result.ok
    assert result.unknown_titles == ("Song A [Extended]",)


def test_human_report_escapes_control_characters():
    """Given 制御文字を含む外部由来 title/name
    When human report を整形する
    Then 改行や ANSI escape を追加行・制御列として出力しない。
    """
    result = verify_playlist_titles(["Song\nA"], ["Song\nA", "Bad\x1b[31mTitle"])
    report = format_verification_report(result)

    assert "Song\\nA" in report
    assert "Bad\\x1b[31mTitle" in report
    assert "\x1b" not in report
    assert "Song\nA" not in report


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


def _write_prompts_json(collection_dir, names=ENTRIES):
    doc = collection_dir / "20-documentation"
    doc.mkdir()
    (doc / "suno-prompts.json").write_text(
        json.dumps([{"name": n, "style": "s", "lyrics": "l"} for n in names], ensure_ascii=False),
        encoding="utf-8",
    )


def _run_cli(monkeypatch, capsys, argv, stdin=""):
    monkeypatch.setattr(sys, "argv", ["yt-suno-verify-playlist", *argv])
    monkeypatch.setattr(sys, "stdin", StringIO(stdin))
    code = suno_verify_playlist.main()
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_cli_accepts_titles_argument(tmp_path, monkeypatch, capsys):
    """Given --titles で playlist title を渡す
    When CLI main を実行する
    Then human report を出して exit 0。
    """
    _write_prompts_json(tmp_path, [ENTRIES[0]])
    code, out, err = _run_cli(monkeypatch, capsys, [str(tmp_path), "--titles", ENTRIES[0], ENTRIES[0]])

    assert code == 0
    assert "→ OK" in out
    assert err == ""


def test_cli_accepts_text_titles_file(tmp_path, monkeypatch, capsys):
    """Given 1行1曲の --titles-file
    When CLI main を実行する
    Then playlist title を読み込む。
    """
    _write_prompts_json(tmp_path, [ENTRIES[0]])
    titles_file = tmp_path / "titles.txt"
    titles_file.write_text(f"{ENTRIES[0]}\n{ENTRIES[0]}\n", encoding="utf-8")

    code, out, err = _run_cli(monkeypatch, capsys, [str(tmp_path), "--titles-file", str(titles_file)])

    assert code == 0
    assert "2 clip(s)" in out
    assert err == ""


def test_cli_accepts_json_titles_file_and_json_output(tmp_path, monkeypatch, capsys):
    """Given JSON 配列の --titles-file と --json
    When CLI main を実行する
    Then machine-readable result を出力する。
    """
    _write_prompts_json(tmp_path, [ENTRIES[0]])
    titles_file = tmp_path / "titles.json"
    titles_file.write_text(json.dumps([ENTRIES[0], ENTRIES[0]], ensure_ascii=False), encoding="utf-8")

    code, out, err = _run_cli(
        monkeypatch,
        capsys,
        [str(tmp_path), "--titles-file", str(titles_file), "--json"],
    )

    assert code == 0
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["matched"] == {ENTRIES[0]: 2}
    assert err == ""


def test_cli_accepts_stdin_titles(tmp_path, monkeypatch, capsys):
    """Given stdin の playlist title
    When 明示入力なしで CLI main を実行する
    Then stdin を入力源として使う。
    """
    _write_prompts_json(tmp_path, [ENTRIES[0]])
    code, out, err = _run_cli(monkeypatch, capsys, [str(tmp_path)], stdin=f"{ENTRIES[0]}\n{ENTRIES[0]}\n")

    assert code == 0
    assert "→ OK" in out
    assert err == ""


def test_cli_returns_one_for_ng_result(tmp_path, monkeypatch, capsys):
    """Given unknown title を含む playlist
    When CLI main を実行する
    Then NG report を stdout に出して exit 1。
    """
    _write_prompts_json(tmp_path, [ENTRIES[0]])
    code, out, err = _run_cli(monkeypatch, capsys, [str(tmp_path), "--titles", "foreign song"])

    assert code == 1
    assert "→ NG" in out
    assert "foreign song" in out
    assert err == ""


def test_cli_rejects_multiple_explicit_input_sources(tmp_path, monkeypatch, capsys):
    """Given --titles と --titles-file を同時指定
    When CLI main を実行する
    Then stderr に契約違反を出して exit 1。
    """
    _write_prompts_json(tmp_path, [ENTRIES[0]])
    titles_file = tmp_path / "titles.txt"
    titles_file.write_text(ENTRIES[0], encoding="utf-8")

    code, out, err = _run_cli(
        monkeypatch,
        capsys,
        [str(tmp_path), "--titles", ENTRIES[0], "--titles-file", str(titles_file)],
    )

    assert code == 1
    assert out == ""
    assert "入力元" in err


def test_cli_rejects_negative_expected_clip_count(tmp_path, monkeypatch, capsys):
    """Given 負の expected clip 数
    When CLI main を実行する
    Then 境界値エラーとして exit 1。
    """
    _write_prompts_json(tmp_path, [ENTRIES[0]])

    code, out, err = _run_cli(
        monkeypatch,
        capsys,
        [str(tmp_path), "--titles", ENTRIES[0], "--expected-clips-per-entry", "-1"],
    )

    assert code == 1
    assert out == ""
    assert "0 以上" in err
