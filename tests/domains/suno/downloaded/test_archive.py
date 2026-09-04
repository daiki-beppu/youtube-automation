"""Suno downloaded ZIP archive reconciliation tests."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from youtube_automation.domains.suno.downloaded.archive import extract_and_rename_music
from youtube_automation.domains.suno.downloaded.models import DownloadedArtifactError


def test_extract_reconciles_suno_zip_name_variations(tmp_path: Path) -> None:
    """Given Suno ZIP に実走で観測した4種の表記揺れがある
    When prompts と照合して展開する
    Then 6 clip すべてを対応する entry の a/b variant へ配置する。
    """
    prompts_dir = tmp_path / "20-documentation"
    prompts_dir.mkdir()
    (prompts_dir / "suno-prompts.json").write_text("[]", encoding="utf-8")
    entries = [
        {"name": "反響の花 — Echo—Bloom"},
        {"name": "天空の道 — Full Width Sky"},
        {"name": "静かな光 — Ordinary Light"},
    ]
    archive = tmp_path / "download.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("Echo — Bloom.mp3", b"em-dash-a")
        zipped.writestr("Echo — Bloom (1).mp3", b"em-dash-b")
        zipped.writestr("Full　Width Sky.mp3", b"fullwidth-space-a")
        zipped.writestr("Full　Width Sky_1.mp3", b"underscore-b")
        zipped.writestr("Ordinary Light.mp3", b"plain-a")
        zipped.writestr("Ordinary Light (1).mp3", b"parenthesized-b")

    placed_count = extract_and_rename_music(
        tmp_path,
        str(archive),
        prompt_entries_reader=lambda _collection_dir: entries,
    )

    music_dir = tmp_path / "02-Individual-music"
    assert placed_count == 6
    assert {path.name: path.read_bytes() for path in music_dir.iterdir()} == {
        "01a-Echo — Bloom.mp3": b"em-dash-a",
        "01b-Echo — Bloom.mp3": b"em-dash-b",
        "02a-Full Width Sky.mp3": b"fullwidth-space-a",
        "02b-Full Width Sky.mp3": b"underscore-b",
        "03a-Ordinary Light.mp3": b"plain-a",
        "03b-Ordinary Light.mp3": b"parenthesized-b",
    }


def test_extract_matches_studio_track_number_prefixes(tmp_path: Path) -> None:
    """Given Studio Multitrack ZIP の数字 prefix 付き WAV
    When prompts と照合して展開する
    Then 数字 prefix を除いた曲名で entry へ配置する。
    """
    prompts_dir = tmp_path / "20-documentation"
    prompts_dir.mkdir()
    (prompts_dir / "suno-prompts.json").write_text("[]", encoding="utf-8")
    entries = [
        {"name": "灰色のまま五時"},
        {"name": "朝の目覚め — bgm-wakeup"},
    ]
    archive = tmp_path / "studio.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("0 灰色のまま五時.wav", b"japanese")
        zipped.writestr("1 bgm-wakeup.wav", b"latin")

    placed_count = extract_and_rename_music(
        tmp_path,
        str(archive),
        prompt_entries_reader=lambda _collection_dir: entries,
    )

    music_dir = tmp_path / "02-Individual-music"
    assert placed_count == 2
    assert {path.name: path.read_bytes() for path in music_dir.iterdir()} == {
        "01a-灰色のまま五時.wav": b"japanese",
        "02a-bgm-wakeup.wav": b"latin",
    }


def test_extract_assigns_same_entry_studio_tracks_to_variants_in_order(tmp_path: Path) -> None:
    """Given 同一曲名を持つ Studio の 2 トラック
    When prompts と照合して展開する
    Then トラック順に a / b variant へ配置する。
    """
    prompts_dir = tmp_path / "20-documentation"
    prompts_dir.mkdir()
    (prompts_dir / "suno-prompts.json").write_text("[]", encoding="utf-8")
    entries = [{"name": "灰色のまま五時"}]
    archive = tmp_path / "studio.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("2 灰色のまま五時.wav", b"first-track")
        zipped.writestr("3 灰色のまま五時.wav", b"second-track")

    placed_count = extract_and_rename_music(
        tmp_path,
        str(archive),
        prompt_entries_reader=lambda _collection_dir: entries,
    )

    music_dir = tmp_path / "02-Individual-music"
    assert placed_count == 2
    assert {path.name: path.read_bytes() for path in music_dir.iterdir()} == {
        "01a-灰色のまま五時.wav": b"first-track",
        "01b-灰色のまま五時.wav": b"second-track",
    }


def test_extract_rejects_studio_tracks_exceeding_entry_variants_without_partial_placement(tmp_path: Path) -> None:
    """Given 同一曲名を持つ Studio の 3 トラック
    When prompts と照合して展開する
    Then variant 上限エラーになり music dir を部分更新しない。
    """
    prompts_dir = tmp_path / "20-documentation"
    prompts_dir.mkdir()
    (prompts_dir / "suno-prompts.json").write_text("[]", encoding="utf-8")
    entries = [{"name": "灰色のまま五時"}]
    archive = tmp_path / "studio.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        for track_number in range(3):
            zipped.writestr(f"{track_number} 灰色のまま五時.wav", str(track_number).encode())

    with pytest.raises(DownloadedArtifactError, match=r"more files than variants \(a/b\)"):
        extract_and_rename_music(
            tmp_path,
            str(archive),
            prompt_entries_reader=lambda _collection_dir: entries,
        )

    assert not (tmp_path / "02-Individual-music").exists()


def test_extract_keeps_numeric_leading_titles_matching_their_own_entry(tmp_path: Path) -> None:
    """Given 数字始まりの曲名 entry と、その残りに一致する別 entry がある Download all ZIP
    When prompts と照合して展開する
    Then 数字 prefix を Studio トラック番号と誤認せず、各ファイルを自分の entry へ配置する。
    """
    prompts_dir = tmp_path / "20-documentation"
    prompts_dir.mkdir()
    (prompts_dir / "suno-prompts.json").write_text("[]", encoding="utf-8")
    entries = [{"name": "3 AM"}, {"name": "AM"}]
    archive = tmp_path / "download.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("3 AM.mp3", b"three-am")
        zipped.writestr("AM.mp3", b"am")

    placed_count = extract_and_rename_music(
        tmp_path,
        str(archive),
        prompt_entries_reader=lambda _collection_dir: entries,
    )

    music_dir = tmp_path / "02-Individual-music"
    assert placed_count == 2
    assert {path.name: path.read_bytes() for path in music_dir.iterdir()} == {
        "01a-3 AM.mp3": b"three-am",
        "02a-AM.mp3": b"am",
    }


def test_extract_orders_studio_tracks_by_numeric_track_number(tmp_path: Path) -> None:
    """Given 同一曲名を持つ Studio のトラック 2 と 10
    When prompts と照合して展開する
    Then ファイル名の辞書順ではなくトラック番号の昇順で a / b variant へ配置する。
    """
    prompts_dir = tmp_path / "20-documentation"
    prompts_dir.mkdir()
    (prompts_dir / "suno-prompts.json").write_text("[]", encoding="utf-8")
    entries = [{"name": "灰色のまま五時"}]
    archive = tmp_path / "studio.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("10 灰色のまま五時.wav", b"track-10")
        zipped.writestr("2 灰色のまま五時.wav", b"track-2")

    placed_count = extract_and_rename_music(
        tmp_path,
        str(archive),
        prompt_entries_reader=lambda _collection_dir: entries,
    )

    music_dir = tmp_path / "02-Individual-music"
    assert placed_count == 2
    assert {path.name: path.read_bytes() for path in music_dir.iterdir()} == {
        "01a-灰色のまま五時.wav": b"track-2",
        "01b-灰色のまま五時.wav": b"track-10",
    }
