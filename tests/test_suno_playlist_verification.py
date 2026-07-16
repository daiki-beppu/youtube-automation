"""Playlist × suno-prompts.json 突合ゲートのテスト."""

from __future__ import annotations

import json
import sys
import zipfile
from io import StringIO
from pathlib import Path

import pytest

from youtube_automation.scripts import suno_verify_playlist
from youtube_automation.utils.exceptions import ValidationError
from youtube_automation.utils.suno_downloaded_archive import extract_and_rename_music
from youtube_automation.utils.suno_playlist_verification import (
    format_display_text,
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


def test_human_report_keeps_printable_japanese_titles():
    """Given 日本語を含む title/name
    When human report を整形する
    Then ユーザーが読める文字は Unicode escape 化しない。
    """
    result = verify_playlist_titles([ENTRIES[0]], [ENTRIES[0]])
    report = format_verification_report(result)

    assert ENTRIES[0] in report
    assert "\\u706f" not in report


def test_display_text_escapes_only_control_characters():
    """Given printable Unicode と制御文字の混在
    When stdout 表示用に sanitize する
    Then 通常文字は保持し制御文字だけ escape する。
    """
    assert format_display_text("灯り\t\x1b[31m") == "灯り\\t\\x1b[31m"


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


def test_load_entry_names_prefers_title_when_present(tmp_path):
    """Given entry.title がある suno-prompts.json
    When load_entry_names する
    Then suno-helper と同じ entry.title ?? entry.name 契約で title を使う。
    """
    doc = tmp_path / "20-documentation"
    doc.mkdir()
    (doc / "suno-prompts.json").write_text(
        json.dumps(
            [
                {
                    "name": "internal-slug",
                    "title": ENTRIES[0],
                    "style": "s",
                    "lyrics": "l",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert load_entry_names(tmp_path) == [ENTRIES[0]]
    assert verify_playlist_titles(load_entry_names(tmp_path), [ENTRIES[0], ENTRIES[0]]).ok


def test_load_entry_names_rejects_non_string_title(tmp_path):
    """Given entry.title が非文字列
    When load_entry_names する
    Then Song Title 契約違反として fail-loud する。
    """
    doc = tmp_path / "20-documentation"
    doc.mkdir()
    (doc / "suno-prompts.json").write_text(
        json.dumps([{"name": "Song A", "title": ["Song A"], "style": "s"}]),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="title must be a string"):
        load_entry_names(tmp_path)


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


def _write_prompt_entries(collection_dir, entries):
    doc = collection_dir / "20-documentation"
    doc.mkdir()
    (doc / "suno-prompts.json").write_text(
        json.dumps(entries, ensure_ascii=False),
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


def test_cli_titles_keeps_legacy_prompt_names_that_are_not_valid_zip_stems(tmp_path, monkeypatch, capsys):
    """Legacy title sources do not depend on ZIP output-stem aliases."""
    _write_prompts_json(tmp_path, ["."])

    code, out, err = _run_cli(monkeypatch, capsys, [str(tmp_path), "--titles", ".", "."])

    assert code == 0
    assert ".: 2 clip(s)" in out
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


def test_cli_accepts_music_directory_titles(tmp_path, monkeypatch, capsys):
    """Given ZIP 展開規約の a/b 音声ファイルがある music directory
    When --music-dir で CLI main を実行する
    Then suffix の title を突合し、entry ごとに 2 clip として exit 0。
    """
    _write_prompts_json(tmp_path, [ENTRIES[0]])
    music_dir = tmp_path / "02-Individual-music"
    music_dir.mkdir()
    (music_dir / f"01a-{ENTRIES[0]}.mp3").touch()
    (music_dir / f"01b-{ENTRIES[0]}.m4a").touch()

    code, out, err = _run_cli(monkeypatch, capsys, [str(tmp_path), "--music-dir", str(music_dir)])

    assert code == 0
    assert f"{ENTRIES[0]}: 2 clip(s)" in out
    assert "→ OK" in out
    assert err == ""


def test_cli_music_directory_reports_invalid_zip_stem_as_validation_error(tmp_path, monkeypatch, capsys):
    """Prompt aliases that cannot become ZIP stems fail through the CLI error contract."""
    _write_prompts_json(tmp_path, ["."])
    music_dir = tmp_path / "02-Individual-music"
    music_dir.mkdir()
    (music_dir / "01a-..mp3").touch()

    code, out, err = _run_cli(monkeypatch, capsys, [str(tmp_path), "--music-dir", str(music_dir)])

    assert code == 1
    assert out == ""
    assert "ZIP extraction output name is empty after sanitization" in err


def test_cli_resolves_relative_music_directory_from_collection(tmp_path, monkeypatch, capsys):
    """Given collection path と collection 相対の --music-dir
    When リポジトリルート相当の別 CWD から公開 CLI を実行する
    Then music directory を collection 基準で解決して exit 0。
    """
    collection_dir = tmp_path / "collections" / "planning" / "night"
    collection_dir.mkdir(parents=True)
    _write_prompts_json(collection_dir, [ENTRIES[0]])
    music_dir = collection_dir / "02-Individual-music"
    music_dir.mkdir()
    (music_dir / f"01a-{ENTRIES[0]}.mp3").touch()
    (music_dir / f"01b-{ENTRIES[0]}.mp3").touch()
    monkeypatch.chdir(tmp_path)

    code, out, err = _run_cli(
        monkeypatch,
        capsys,
        [str(collection_dir), "--music-dir", "02-Individual-music"],
    )

    assert code == 0
    assert f"{ENTRIES[0]}: 2 clip(s)" in out
    assert err == ""


def test_cli_accepts_bilingual_names_emitted_by_zip_extraction(tmp_path, monkeypatch, capsys):
    """Given ZIP extraction が bilingual entry の英語候補で出力した音声ファイル
    When public CLI を --music-dir で実行する
    Then ZIP 出力名を canonical entry に戻して 2 clip として検証する。
    """
    _write_prompts_json(tmp_path, [ENTRIES[0]])
    archive = tmp_path / "download.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("Dim the Lights.mp3", b"a")
        zipped.writestr("Dim the Lights_1.mp3", b"b")
    extract_and_rename_music(tmp_path, str(archive))
    music_dir = tmp_path / "02-Individual-music"

    code, out, err = _run_cli(monkeypatch, capsys, [str(tmp_path), "--music-dir", str(music_dir)])

    assert sorted(path.name for path in music_dir.iterdir()) == [
        "01a-Dim the Lights.mp3",
        "01b-Dim the Lights.mp3",
    ]
    assert code == 0
    assert f"{ENTRIES[0]}: 2 clip(s)" in out
    assert "→ OK" in out
    assert err == ""


def test_cli_prefers_exact_zip_stems_before_normalized_aliases(tmp_path, monkeypatch, capsys):
    """ZIP stems distinguish exact aliases even when normalization merges them."""
    entries = [
        {"name": "甲 — ①", "style": "s", "lyrics": "l"},
        {"name": "乙 — 1", "style": "s", "lyrics": "l"},
    ]
    _write_prompt_entries(tmp_path, entries)
    archive = tmp_path / "download.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("①.mp3", b"a")
        zipped.writestr("①_1.mp3", b"b")
        zipped.writestr("1.mp3", b"a")
        zipped.writestr("1_1.mp3", b"b")
    extract_and_rename_music(tmp_path, str(archive))
    music_dir = tmp_path / "02-Individual-music"

    code, out, err = _run_cli(monkeypatch, capsys, [str(tmp_path), "--music-dir", str(music_dir)])

    assert sorted(path.name for path in music_dir.iterdir()) == [
        "01a-①.mp3",
        "01b-①.mp3",
        "02a-1.mp3",
        "02b-1.mp3",
    ]
    assert code == 0
    assert "甲 — ①: 2 clip(s)" in out
    assert "乙 — 1: 2 clip(s)" in out
    assert "→ OK" in out
    assert err == ""


def test_cli_accepts_apostrophe_removed_names_emitted_by_zip_extraction(tmp_path, monkeypatch, capsys):
    """Given Suno ZIP が apostrophe を除去した音声ファイル
    When ZIP 展開後の music directory を公開 CLI で検証する
    Then canonical entry に戻して 2 clip として exit 0。
    """
    canonical_title = "Greed's Rhythm"
    _write_prompts_json(tmp_path, [canonical_title])
    archive = tmp_path / "download.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("Greeds Rhythm.m4a", b"a")
        zipped.writestr("Greeds Rhythm_1.m4a", b"b")
    extract_and_rename_music(tmp_path, str(archive))
    music_dir = tmp_path / "02-Individual-music"

    code, out, err = _run_cli(monkeypatch, capsys, [str(tmp_path), "--music-dir", str(music_dir)])

    assert sorted(path.name for path in music_dir.iterdir()) == [
        "01a-Greeds Rhythm.m4a",
        "01b-Greeds Rhythm.m4a",
    ]
    assert code == 0
    assert f"{canonical_title}: 2 clip(s)" in out
    assert err == ""


def test_cli_accepts_name_alias_when_entry_title_differs(tmp_path, monkeypatch, capsys):
    """Given title と name が異なり ZIP が name の英語 alias を出力する entry
    When ZIP 展開後の music directory を公開 CLI で検証する
    Then title を canonical entry として 2 clip に集約する。
    """
    canonical_title = "Display Title"
    _write_prompt_entries(
        tmp_path,
        [{"name": "内部名 — Internal Name", "title": canonical_title, "style": "s", "lyrics": "l"}],
    )
    archive = tmp_path / "download.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("Internal Name.mp3", b"a")
        zipped.writestr("Internal Name_1.mp3", b"b")
    extract_and_rename_music(tmp_path, str(archive))
    music_dir = tmp_path / "02-Individual-music"

    code, out, err = _run_cli(monkeypatch, capsys, [str(tmp_path), "--music-dir", str(music_dir)])

    assert sorted(path.name for path in music_dir.iterdir()) == [
        "01a-Internal Name.mp3",
        "01b-Internal Name.mp3",
    ]
    assert code == 0
    assert f"{canonical_title}: 2 clip(s)" in out
    assert err == ""


def test_cli_accepts_unique_full_names_when_entries_share_an_unused_alias(tmp_path, monkeypatch, capsys):
    """Unused aliases shared by entries do not reject unambiguous full filenames."""
    entries = [
        {"name": "Alpha — Shared", "style": "s", "lyrics": "l"},
        {"name": "Beta — Shared", "style": "s", "lyrics": "l"},
    ]
    _write_prompt_entries(tmp_path, entries)
    music_dir = tmp_path / "02-Individual-music"
    music_dir.mkdir()
    for index, entry in enumerate(entries, 1):
        for variant in ("a", "b"):
            (music_dir / f"{index:02d}{variant}-{entry['name']}.mp3").touch()

    code, out, err = _run_cli(monkeypatch, capsys, [str(tmp_path), "--music-dir", str(music_dir)])

    assert code == 0
    assert "Alpha — Shared: 2 clip(s)" in out
    assert "Beta — Shared: 2 clip(s)" in out
    assert "→ OK" in out
    assert err == ""


def test_cli_uses_extracted_entry_index_to_resolve_shared_alias(tmp_path, monkeypatch, capsys):
    """The producer's numeric prefix disambiguates a ZIP alias shared by entries."""
    entries = [
        {"name": "Alpha — Shared", "style": "s", "lyrics": "l"},
        {"name": "Beta — Shared", "style": "s", "lyrics": "l"},
    ]
    _write_prompt_entries(tmp_path, entries)
    archive = tmp_path / "download.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("Alpha — Shared.mp3", b"a")
        zipped.writestr("Alpha — Shared_1.mp3", b"b")
        zipped.writestr("Shared.mp3", b"a")
        zipped.writestr("Shared_1.mp3", b"b")
    extract_and_rename_music(tmp_path, str(archive))
    music_dir = tmp_path / "02-Individual-music"

    code, out, err = _run_cli(monkeypatch, capsys, [str(tmp_path), "--music-dir", str(music_dir)])

    assert sorted(path.name for path in music_dir.iterdir()) == [
        "01a-Alpha — Shared.mp3",
        "01b-Alpha — Shared.mp3",
        "02a-Shared.mp3",
        "02b-Shared.mp3",
    ]
    assert code == 0
    assert "Alpha — Shared: 2 clip(s)" in out
    assert "Beta — Shared: 2 clip(s)" in out
    assert "→ OK" in out
    assert err == ""


def test_cli_accepts_three_digit_entry_index_emitted_by_zip_extraction(tmp_path, monkeypatch, capsys):
    """The producer and public CLI preserve the 100th entry's three-digit prefix."""
    entries = [{"name": f"Track {index}", "style": "s", "lyrics": "l"} for index in range(1, 101)]
    _write_prompt_entries(tmp_path, entries)
    archive = tmp_path / "download.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        for index in range(1, 101):
            zipped.writestr(f"Track {index}.mp3", b"a")
            zipped.writestr(f"Track {index}_1.mp3", b"b")
    extract_and_rename_music(tmp_path, str(archive))
    music_dir = tmp_path / "02-Individual-music"

    code, out, err = _run_cli(monkeypatch, capsys, [str(tmp_path), "--music-dir", str(music_dir)])

    assert (music_dir / "100a-Track 100.mp3").is_file()
    assert (music_dir / "100b-Track 100.mp3").is_file()
    assert code == 0
    assert "Track 100: 2 clip(s)" in out
    assert "→ OK" in out
    assert err == ""


def test_cli_deduplicates_same_variant_across_canonical_aliases(tmp_path, monkeypatch, capsys):
    """Given 同一 entry の full name と英語 alias が同じ a variant として ZIP に共存
    When ZIP 展開後の music directory を公開 CLI で検証する
    Then canonical entry + variant で重複排除し b 欠落を underfilled として報告する。
    """
    canonical_title = "灯りを落として — Dim the Lights"
    _write_prompts_json(tmp_path, [canonical_title])
    archive = tmp_path / "download.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr(f"{canonical_title}.mp3", b"full")
        zipped.writestr("Dim the Lights.mp3", b"english")
    extract_and_rename_music(tmp_path, str(archive))
    music_dir = tmp_path / "02-Individual-music"

    code, out, err = _run_cli(monkeypatch, capsys, [str(tmp_path), "--music-dir", str(music_dir)])

    assert sorted(path.name for path in music_dir.iterdir()) == [
        "01a-Dim the Lights.mp3",
        f"01a-{canonical_title}.mp3",
    ]
    assert code == 1
    assert f"{canonical_title}: 1 clip(s)" in out
    assert "clip 不足" in out
    assert err == ""


def test_cli_music_directory_reports_unknown_and_missing(tmp_path, monkeypatch, capsys):
    """Given 期待 entry の代わりに別 title の a/b 音声ファイルがある
    When --music-dir で CLI main を実行する
    Then unknown と missing をレポートし exit 1。
    """
    _write_prompts_json(tmp_path, [ENTRIES[0]])
    music_dir = tmp_path / "02-Individual-music"
    music_dir.mkdir()
    (music_dir / "01a-Foreign Song.mp3").touch()
    (music_dir / "01b-Foreign Song.wav").touch()

    code, out, err = _run_cli(monkeypatch, capsys, [str(tmp_path), "--music-dir", str(music_dir)])

    assert code == 1
    assert "Foreign Song" in out
    assert ENTRIES[0] in out
    assert "→ NG" in out
    assert err == ""


def test_cli_music_directory_reports_single_variant_as_underfilled(tmp_path, monkeypatch, capsys):
    """Given entry の a variant だけがある music directory
    When expected clip 数の既定値で CLI main を実行する
    Then underfilled をレポートし exit 1。
    """
    _write_prompts_json(tmp_path, [ENTRIES[0]])
    music_dir = tmp_path / "02-Individual-music"
    music_dir.mkdir()
    (music_dir / f"01a-{ENTRIES[0]}.mp3").touch()

    code, out, err = _run_cli(monkeypatch, capsys, [str(tmp_path), "--music-dir", str(music_dir)])

    assert code == 1
    assert "clip 不足" in out
    assert ENTRIES[0] in out
    assert "→ NG" in out
    assert err == ""


def test_cli_music_directory_does_not_count_normalized_duplicate_a_files_as_two_variants(tmp_path, monkeypatch, capsys):
    """Given 正規化後に同じ entry となる a variant が異なる拡張子で 2 ファイルあり b がない
    When --music-dir で CLI main を実行する
    Then ファイル総数ではなく variant 出現数を数え underfilled として exit 1。
    """
    _write_prompts_json(tmp_path, [ENTRIES[0]])
    music_dir = tmp_path / "02-Individual-music"
    music_dir.mkdir()
    (music_dir / "01a-Dim the Lights.mp3").touch()
    (music_dir / "01a-DIM THE LIGHTS.wav").touch()

    code, out, err = _run_cli(monkeypatch, capsys, [str(tmp_path), "--music-dir", str(music_dir)])

    assert code == 1
    assert "clip 不足" in out
    assert "1 clip(s)" in out
    assert err == ""


def test_cli_music_directory_reports_unprefixed_audio_filename_as_unknown(tmp_path, monkeypatch, capsys):
    """Given 2桁以上の数値{a|b}- prefix に合致しない音声ファイルが混入している
    When --music-dir で CLI main を実行する
    Then silent skip せず拡張子込みのファイル名を unknown として報告する。
    """
    _write_prompts_json(tmp_path, [ENTRIES[0]])
    music_dir = tmp_path / "02-Individual-music"
    music_dir.mkdir()
    (music_dir / f"01a-{ENTRIES[0]}.mp3").touch()
    (music_dir / f"01b-{ENTRIES[0]}.mp3").touch()
    (music_dir / "manual-track.mp3").touch()

    code, out, err = _run_cli(monkeypatch, capsys, [str(tmp_path), "--music-dir", str(music_dir)])

    assert code == 1
    assert "manual-track.mp3" in out
    assert "→ NG" in out
    assert err == ""


@pytest.mark.parametrize("explicit_source", ["titles", "titles-file"])
def test_cli_rejects_music_directory_with_explicit_title_source(tmp_path, monkeypatch, capsys, explicit_source):
    """Given --music-dir と既存の明示 title 入力を同時指定
    When CLI main を実行する
    Then 複数入力元として拒否し exit 1。
    """
    _write_prompts_json(tmp_path, [ENTRIES[0]])
    music_dir = tmp_path / "02-Individual-music"
    music_dir.mkdir()
    (music_dir / f"01a-{ENTRIES[0]}.mp3").touch()
    titles_file = tmp_path / "titles.txt"
    titles_file.write_text(ENTRIES[0], encoding="utf-8")
    title_args = ["--titles", ENTRIES[0]] if explicit_source == "titles" else ["--titles-file", str(titles_file)]

    code, out, err = _run_cli(
        monkeypatch,
        capsys,
        [str(tmp_path), "--music-dir", str(music_dir), *title_args],
    )

    assert code == 1
    assert out == ""
    assert "入力元" in err


def test_cli_rejects_music_directory_with_empty_titles_option(tmp_path, monkeypatch, capsys):
    """Given 値なしの --titles と --music-dir を同時指定
    When CLI main を実行する
    Then --titles の指定自体を入力元として扱い競合を報告する。
    """
    _write_prompts_json(tmp_path, [ENTRIES[0]])
    music_dir = tmp_path / "02-Individual-music"
    music_dir.mkdir()
    (music_dir / f"01a-{ENTRIES[0]}.mp3").touch()

    code, out, err = _run_cli(
        monkeypatch,
        capsys,
        [str(tmp_path), "--music-dir", str(music_dir), "--titles"],
    )

    assert code == 1
    assert out == ""
    assert "入力元" in err


def test_cli_rejects_music_directory_with_stdin(tmp_path, monkeypatch, capsys):
    """Given --music-dir と stdin title を同時指定
    When CLI main を実行する
    Then 複数入力元として拒否し exit 1。
    """
    _write_prompts_json(tmp_path, [ENTRIES[0]])
    music_dir = tmp_path / "02-Individual-music"
    music_dir.mkdir()
    (music_dir / f"01a-{ENTRIES[0]}.mp3").touch()
    (music_dir / f"01b-{ENTRIES[0]}.mp3").touch()

    code, out, err = _run_cli(
        monkeypatch,
        capsys,
        [str(tmp_path), "--music-dir", str(music_dir)],
        stdin=f"{ENTRIES[0]}\n",
    )

    assert code == 1
    assert out == ""
    assert "入力元" in err


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


def test_cli_passes_expected_clip_count_to_verifier(tmp_path, monkeypatch, capsys):
    """Given 1 clip だけの playlist
    When expected clip 数を CLI option で変更する
    Then 既定値は NG、1 または 0 指定は OK になる。
    """
    _write_prompts_json(tmp_path, [ENTRIES[0]])

    default_code, default_out, default_err = _run_cli(
        monkeypatch,
        capsys,
        [str(tmp_path), "--titles", ENTRIES[0]],
    )
    one_code, one_out, one_err = _run_cli(
        monkeypatch,
        capsys,
        [str(tmp_path), "--titles", ENTRIES[0], "--expected-clips-per-entry", "1"],
    )
    disabled_code, disabled_out, disabled_err = _run_cli(
        monkeypatch,
        capsys,
        [str(tmp_path), "--titles", ENTRIES[0], "--expected-clips-per-entry", "0"],
    )

    assert default_code == 1
    assert "clip 不足" in default_out
    assert default_err == ""
    assert one_code == 0
    assert "→ OK" in one_out
    assert one_err == ""
    assert disabled_code == 0
    assert "→ OK" in disabled_out
    assert disabled_err == ""


@pytest.mark.parametrize("payload", [{}, None, [ENTRIES[0], 123]])
def test_cli_rejects_json_titles_file_with_invalid_shape(tmp_path, monkeypatch, capsys, payload):
    """Given JSON titles-file が文字列配列ではない
    When CLI main を実行する
    Then playlist title 入力契約違反として exit 1。
    """
    _write_prompts_json(tmp_path, [ENTRIES[0]])
    titles_file = tmp_path / "titles.json"
    titles_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    code, out, err = _run_cli(monkeypatch, capsys, [str(tmp_path), "--titles-file", str(titles_file)])

    assert code == 1
    assert out == ""
    assert "文字列の配列" in err


def test_masterup_primary_verification_uses_music_directory_without_playlist_resolution():
    """Given masterup の Step 1.6
    When primary path の title 解決手順を読む
    Then music directory が第一手段で URL WebFetch・title list 確認を要求しない。
    """
    skill = Path(".claude/skills/masterup/SKILL.md").read_text(encoding="utf-8")
    step = skill.split("### Step 1.6:", 1)[1].split("### Step 2:", 1)[0]
    primary = step.split("primary path では", 1)[1].split("fallback path", 1)[0]

    assert "uv run yt-suno-verify-playlist <collection-path> --music-dir 02-Individual-music" in primary
    assert "第一手段" in primary
    assert "WebFetch" not in primary
    assert "title list を提示" not in primary
    assert "fallback path" in step
