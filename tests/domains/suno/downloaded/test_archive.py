"""Suno downloaded ZIP archive reconciliation tests."""

from __future__ import annotations

import zipfile
from pathlib import Path

from youtube_automation.domains.suno.downloaded.archive import extract_and_rename_music


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
