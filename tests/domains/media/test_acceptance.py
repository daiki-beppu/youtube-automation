from __future__ import annotations

from pathlib import Path

import pytest

from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.media.acceptance import (
    AudioMeasurement,
    MediaAcceptancePolicy,
    evaluate_media_acceptance,
)


def _measurement(name: str, *, duration: float = 180.0, loudness: float = -14.0) -> AudioMeasurement:
    return AudioMeasurement(Path(name), duration, loudness)


def _policy(*, expected: int = 2) -> MediaAcceptancePolicy:
    return MediaAcceptancePolicy(
        expected_track_count=expected,
        minimum_duration_seconds=60.0,
        maximum_duration_seconds=300.0,
        minimum_integrated_lufs=-40.0,
        maximum_integrated_lufs=-5.0,
        maximum_loudness_deviation_lu=2.0,
    )


def test_acceptance_passes_when_count_duration_and_loudness_are_valid() -> None:
    measurements = (
        _measurement("01.mp3", loudness=-14.0),
        _measurement("02.mp3", duration=240.0, loudness=-15.0),
    )

    report = evaluate_media_acceptance(measurements, _policy())

    assert report.passed is True
    assert report.issues == ()


def test_acceptance_rejects_missing_tracks_against_planned_count() -> None:
    measurements = (_measurement("01.mp3"),)

    report = evaluate_media_acceptance(measurements, _policy(expected=2))

    assert report.passed is False
    assert [issue.code for issue in report.issues] == ["track_count"]


@pytest.mark.parametrize("duration", [59.9, 300.1])
def test_acceptance_rejects_duration_outside_suno_yield_guard(duration: float) -> None:
    measurements = (
        _measurement("01.mp3", duration=duration),
        _measurement("02.mp3"),
    )

    report = evaluate_media_acceptance(measurements, _policy())

    assert report.passed is False
    assert any(issue.code == "duration" and issue.file == "01.mp3" for issue in report.issues)


@pytest.mark.parametrize("loudness", [-40.1, -4.9])
def test_acceptance_rejects_absolute_loudness_outside_safe_range(loudness: float) -> None:
    measurements = (
        _measurement("01.mp3", loudness=loudness),
        _measurement("02.mp3", loudness=loudness),
    )

    report = evaluate_media_acceptance(measurements, _policy())

    assert report.passed is False
    assert {issue.code for issue in report.issues} == {"loudness"}


def test_acceptance_rejects_collection_loudness_deviation() -> None:
    measurements = (
        _measurement("01.mp3", loudness=-14.0),
        _measurement("02.mp3", loudness=-17.0),
    )

    report = evaluate_media_acceptance(measurements, _policy())

    assert report.passed is False
    assert [issue.code for issue in report.issues] == ["loudness_deviation"]


def test_acceptance_policy_rejects_inverted_thresholds() -> None:
    with pytest.raises(ValidationError):
        MediaAcceptancePolicy(
            expected_track_count=2,
            minimum_duration_seconds=300.0,
            maximum_duration_seconds=60.0,
            minimum_integrated_lufs=-5.0,
            maximum_integrated_lufs=-40.0,
            maximum_loudness_deviation_lu=0.0,
        )
