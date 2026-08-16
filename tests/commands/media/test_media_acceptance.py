from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.helpers.music_prompt import write_suno_prompt_pair
from youtube_automation.commands.media import media_acceptance
from youtube_automation.domains.media.acceptance import AudioMeasurement
from youtube_automation.domains.notifications import NotificationEvent, NotificationEventKind


class FixtureInspector:
    def inspect(self, path: Path) -> AudioMeasurement:
        return AudioMeasurement(path, 180.0, -14.0)


def _collection(tmp_path: Path, *, actual_count: int = 2) -> Path:
    collection = tmp_path / "20260816-clm-rain-collection"
    music = collection / "02-Individual-music"
    documentation = collection / "20-documentation"
    music.mkdir(parents=True)
    documentation.mkdir()
    for index in range(actual_count):
        (music / f"{index + 1:02}.mp3").write_bytes(b"fixture")
    (collection / "workflow-state.json").write_text(
        json.dumps({"planning": {"music": {"expected_file_count": 2}}}),
        encoding="utf-8",
    )
    write_suno_prompt_pair(
        documentation,
        [{"name": "Rain"}],
        duration_filter={"min_sec": 60, "max_sec": 300},
    )
    return collection


def _patch_runtime(monkeypatch) -> None:
    monkeypatch.setattr(media_acceptance, "FFmpegAudioInspector", FixtureInspector)
    monkeypatch.setattr(
        media_acceptance,
        "load_skill_config",
        lambda _skill: {"validation": {"loudness_deviation": {"max_lu": 2.0}}},
    )
    monkeypatch.setattr(
        media_acceptance,
        "load_config",
        lambda: SimpleNamespace(meta=SimpleNamespace(channel_short="ambient-lab")),
    )


def test_cli_passes_and_emits_json_report(monkeypatch, capsys, tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    _patch_runtime(monkeypatch)

    exit_code = media_acceptance.main([str(collection), "--output", "json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "pass"
    assert payload["expected_track_count"] == 2
    assert payload["actual_track_count"] == 2


def test_cli_fails_closed_when_planned_track_is_missing(monkeypatch, capsys, tmp_path: Path) -> None:
    collection = _collection(tmp_path, actual_count=1)
    _patch_runtime(monkeypatch)
    events: list[NotificationEvent] = []
    monkeypatch.setattr(
        media_acceptance,
        "create_discord_notification_sink",
        lambda: SimpleNamespace(send=lambda event: events.append(event) or True),
    )

    exit_code = media_acceptance.main([str(collection), "--output", "json"])

    assert exit_code == 2
    assert "track_count" in capsys.readouterr().err
    assert events == [
        NotificationEvent(
            NotificationEventKind.FAIL_CLOSED_ABORTED,
            "ambient-lab",
            collection.name,
            "media-acceptance",
        )
    ]


def test_cli_output_rejects_unknown_choice() -> None:
    with pytest.raises(SystemExit) as error:
        media_acceptance.build_parser().parse_args(["collection", "--output", "yaml"])

    assert error.value.code == 2
