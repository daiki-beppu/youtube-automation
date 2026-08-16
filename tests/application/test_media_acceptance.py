from __future__ import annotations

from pathlib import Path

import pytest

from youtube_automation.application.media_acceptance import (
    MediaAcceptanceEventKind,
    validate_collection_audio,
)
from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.media.acceptance import AudioMeasurement, MediaAcceptancePolicy


class FixtureInspector:
    def __init__(self, values: dict[str, tuple[float, float]]) -> None:
        self._values = values

    def inspect(self, path: Path) -> AudioMeasurement:
        duration, loudness = self._values[path.name]
        return AudioMeasurement(path, duration, loudness)


def _collection(tmp_path: Path) -> Path:
    collection = tmp_path / "20260816-clm-rain-collection"
    music = collection / "02-Individual-music"
    music.mkdir(parents=True)
    (music / "01.mp3").write_bytes(b"one")
    (music / "02.m4a").write_bytes(b"two")
    return collection


def _policy() -> MediaAcceptancePolicy:
    return MediaAcceptancePolicy(2, 60.0, 300.0, -40.0, -5.0, 2.0)


def test_validation_returns_report_without_event_when_all_tracks_pass(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    events = []
    inspector = FixtureInspector({"01.mp3": (180.0, -14.0), "02.m4a": (200.0, -15.0)})

    report = validate_collection_audio(collection, _policy(), inspector, on_event=events.append)

    assert report.passed is True
    assert events == []


def test_validation_emits_rejected_event_and_stops_before_downstream(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    events = []
    inspector = FixtureInspector({"01.mp3": (30.0, -14.0), "02.m4a": (200.0, -15.0)})

    with pytest.raises(ValidationError, match="media acceptance failed"):
        validate_collection_audio(collection, _policy(), inspector, on_event=events.append)

    assert len(events) == 1
    assert events[0].kind is MediaAcceptanceEventKind.REJECTED
    assert events[0].collection == collection.name
    assert events[0].issue_codes == ("duration",)


def test_probe_failure_emits_rejected_event_and_stops(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    events = []

    class FailingInspector:
        def inspect(self, path: Path) -> AudioMeasurement:
            raise ValidationError(f"probe failed: {path.name}")

    with pytest.raises(ValidationError, match="probe failed"):
        validate_collection_audio(collection, _policy(), FailingInspector(), on_event=events.append)

    assert events[0].kind is MediaAcceptanceEventKind.REJECTED
    assert events[0].issue_codes == ("probe",)


def test_empty_music_directory_is_a_track_count_rejection(tmp_path: Path) -> None:
    collection = tmp_path / "20260816-clm-empty-collection"
    (collection / "02-Individual-music").mkdir(parents=True)
    events = []

    with pytest.raises(ValidationError, match="track_count"):
        validate_collection_audio(collection, _policy(), FixtureInspector({}), on_event=events.append)

    assert events[0].issue_codes == ("track_count",)
