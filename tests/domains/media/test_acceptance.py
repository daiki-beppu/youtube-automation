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


@pytest.mark.parametrize("duration", [60.0, 300.0])
@pytest.mark.parametrize("loudness", [-40.0, -5.0])
def test_acceptance_includes_absolute_range_endpoints(duration: float, loudness: float) -> None:
    report = evaluate_media_acceptance(
        (_measurement("01.mp3", duration=duration, loudness=loudness),), _policy(expected=1)
    )

    assert report.passed is True


def test_acceptance_reports_all_range_failures_in_track_order_with_units() -> None:
    report = evaluate_media_acceptance(
        (
            _measurement("01.mp3", duration=59.9999, loudness=-40.0001),
            _measurement("02.mp3", duration=300.0001, loudness=-4.9999),
        ),
        _policy(expected=3),
    )

    issues = report.to_dict()["issues"]
    assert issues == [
        {"code": "track_count", "file": None, "message": "planned=3, actual=2"},
        {"code": "duration", "file": "01.mp3", "message": "60.000s is outside 60.000..300.000s"},
        {"code": "loudness", "file": "01.mp3", "message": "-40.000 LUFS is outside -40.000..-5.000 LUFS"},
        {"code": "duration", "file": "02.mp3", "message": "300.000s is outside 60.000..300.000s"},
        {"code": "loudness", "file": "02.mp3", "message": "-5.000 LUFS is outside -40.000..-5.000 LUFS"},
        {"code": "loudness_deviation", "file": None, "message": "35.000 LU exceeds 2.000 LU"},
    ]
