import json
from pathlib import Path

import pytest

from youtube_automation.commands.suno.content_id_evidence import main, record, record_downloaded_evidence, render_draft
from youtube_automation.core.errors import ValidationError


def test_record_and_render_dispute_draft(tmp_path: Path) -> None:
    record(
        tmp_path,
        track="Quiet Rain",
        url="https://suno.com/song/clip-1",
        generated_at="2026-09-15T12:00:00Z",
        model="v5",
        plan="Premier",
        start_time="00:00",
    )

    draft = render_draft(tmp_path, "Quiet Rain")

    assert "https://suno.com/song/clip-1" in draft
    assert "2026-09-15T12:00:00Z" in draft
    assert "Premier" in draft
    assert "再審査請求" in draft


def test_download_placement_records_urls_and_cumulative_start_times(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    music_dir = tmp_path / "02-Individual-music"
    music_dir.mkdir()
    docs_dir = tmp_path / "20-documentation"
    docs_dir.mkdir()
    (docs_dir / "suno-prompts.json").write_text('{"model": "V5.5"}', encoding="utf-8")
    (music_dir / "01a-Rain.wav").touch()
    (music_dir / "02a-Wind.wav").touch()
    monkeypatch.setattr(
        "youtube_automation.commands.suno.content_id_evidence.probe_duration",
        lambda _path: 75.0,
    )

    path = record_downloaded_evidence(
        tmp_path,
        clip_ids=("clip-1", "clip-2"),
        studio_ordered_tracks=("02a-Wind.wav", "01a-Rain.wav"),
        generated_at="2026-09-15T21:00:00+09:00",
    )

    entries = {entry["track"]: entry for entry in json.loads(path.read_text(encoding="utf-8"))}
    assert entries["02a-Wind.wav"]["clip_url"] == "https://suno.com/song/clip-1"
    assert entries["01a-Rain.wav"]["clip_url"] == "https://suno.com/song/clip-2"
    assert entries["01a-Rain.wav"]["generated_at"] == "2026-09-15T12:00:00Z"
    assert entries["02a-Wind.wav"]["start_time"] == "01:15"


def test_mismatched_download_does_not_guess_clip_to_track_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    music_dir = tmp_path / "02-Individual-music"
    music_dir.mkdir()
    docs_dir = tmp_path / "20-documentation"
    docs_dir.mkdir()
    (docs_dir / "suno-prompts.json").write_text('{"model": "V5.5"}', encoding="utf-8")
    (music_dir / "01a-Rain.wav").touch()
    monkeypatch.setattr(
        "youtube_automation.commands.suno.content_id_evidence.probe_duration",
        lambda _path: 60.0,
    )

    with pytest.raises(ValidationError, match="clip 数と配置済み音源数"):
        record_downloaded_evidence(
            tmp_path,
            clip_ids=("clip-1", "clip-not-placed"),
            studio_ordered_tracks=("01a-Rain.wav",),
            generated_at="2026-09-15T12:00:00Z",
        )

    assert not (docs_dir / "suno-content-id-evidence.json").exists()


@pytest.mark.parametrize(
    "url",
    ["http://suno.com/song/clip-1", "https://example.com/song/clip-1", "https://suno.com/clip-1"],
)
def test_record_rejects_invalid_clip_url(tmp_path: Path, url: str) -> None:
    with pytest.raises(ValidationError, match="clip URL"):
        record(tmp_path, track="track", url=url, generated_at="2026-09-15T12:00:00Z", model="v5", plan="Premier")


def test_record_rejects_invalid_generated_at(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="ISO 8601"):
        record(
            tmp_path,
            track="track",
            url="https://suno.com/song/clip-1",
            generated_at="not-a-date",
            model="v5",
            plan="Premier",
        )


def test_render_draft_rejects_unknown_track(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="生成記録がありません"):
        render_draft(tmp_path, "unknown")


def test_record_writes_into_the_collection_documentation_dir(tmp_path: Path) -> None:
    path = record(
        tmp_path,
        track="track",
        url="https://suno.com/song/clip-1",
        generated_at="2026-09-15T12:00:00Z",
        model="v5",
        plan="Premier",
        start_time="00:00",
    )

    assert path == tmp_path.resolve() / "20-documentation" / "suno-content-id-evidence.json"


def test_record_rejects_a_missing_collection_without_creating_it(tmp_path: Path) -> None:
    missing = tmp_path / "missing"

    with pytest.raises(ValidationError, match="コレクションディレクトリが見つかりません"):
        record(
            missing,
            track="track",
            url="https://suno.com/song/clip-1",
            generated_at="2026-09-15T12:00:00Z",
            model="v5",
            plan="Premier",
        )

    assert not missing.exists()


def test_render_draft_rejects_a_missing_collection(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="コレクションディレクトリが見つかりません"):
        render_draft(tmp_path / "missing", "track")


def test_render_draft_rejects_non_object_evidence_entries(tmp_path: Path) -> None:
    path = tmp_path / "20-documentation" / "suno-content-id-evidence.json"
    path.parent.mkdir(parents=True)
    path.write_text('["Quiet Rain"]', encoding="utf-8")

    with pytest.raises(ValidationError, match="JSON オブジェクト"):
        render_draft(tmp_path, "Quiet Rain")


def test_cli_reports_a_missing_collection_without_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(tmp_path / "missing"), "draft", "--track", "track"]) == 1
    assert "コレクションディレクトリが見つかりません" in capsys.readouterr().err
