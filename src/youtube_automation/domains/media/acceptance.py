"""Cloud handoff 後の音源受入判定。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from youtube_automation.core.errors import ValidationError

MediaAcceptanceIssueCode = Literal["track_count", "duration", "loudness", "loudness_deviation"]


@dataclass(frozen=True, slots=True)
class MediaAcceptancePolicy:
    expected_track_count: int
    minimum_duration_seconds: float
    maximum_duration_seconds: float
    minimum_integrated_lufs: float
    maximum_integrated_lufs: float
    maximum_loudness_deviation_lu: float

    def __post_init__(self) -> None:
        values = (
            self.minimum_duration_seconds,
            self.maximum_duration_seconds,
            self.minimum_integrated_lufs,
            self.maximum_integrated_lufs,
            self.maximum_loudness_deviation_lu,
        )
        if self.expected_track_count <= 0:
            raise ValidationError("media acceptance expected_track_count は1以上である必要があります")
        if not all(math.isfinite(value) for value in values):
            raise ValidationError("media acceptance threshold は有限数である必要があります")
        if self.minimum_duration_seconds < 0 or self.minimum_duration_seconds > self.maximum_duration_seconds:
            raise ValidationError("media acceptance duration threshold が不正です")
        if self.minimum_integrated_lufs > self.maximum_integrated_lufs:
            raise ValidationError("media acceptance loudness threshold が不正です")
        if self.maximum_loudness_deviation_lu <= 0:
            raise ValidationError("media acceptance loudness deviation は0より大きい必要があります")


@dataclass(frozen=True, slots=True)
class AudioMeasurement:
    path: Path
    duration_seconds: float
    integrated_lufs: float

    def __post_init__(self) -> None:
        if self.duration_seconds < 0 or not math.isfinite(self.duration_seconds):
            raise ValidationError(f"音源 duration が不正です: {self.path.name}")
        if not math.isfinite(self.integrated_lufs):
            raise ValidationError(f"音源 loudness が不正です: {self.path.name}")


@dataclass(frozen=True, slots=True)
class MediaAcceptanceIssue:
    code: MediaAcceptanceIssueCode
    message: str
    file: str | None = None


@dataclass(frozen=True, slots=True)
class MediaAcceptanceReport:
    policy: MediaAcceptancePolicy
    measurements: tuple[AudioMeasurement, ...]
    issues: tuple[MediaAcceptanceIssue, ...]

    @property
    def passed(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, object]:
        return {
            "status": "pass" if self.passed else "fail",
            "expected_track_count": self.policy.expected_track_count,
            "actual_track_count": len(self.measurements),
            "duration_range_seconds": [
                self.policy.minimum_duration_seconds,
                self.policy.maximum_duration_seconds,
            ],
            "loudness_range_lufs": [
                self.policy.minimum_integrated_lufs,
                self.policy.maximum_integrated_lufs,
            ],
            "maximum_loudness_deviation_lu": self.policy.maximum_loudness_deviation_lu,
            "tracks": [
                {
                    "file": measurement.path.name,
                    "duration_seconds": measurement.duration_seconds,
                    "integrated_lufs": measurement.integrated_lufs,
                }
                for measurement in self.measurements
            ],
            "issues": [{"code": issue.code, "file": issue.file, "message": issue.message} for issue in self.issues],
        }


def evaluate_media_acceptance(
    measurements: tuple[AudioMeasurement, ...],
    policy: MediaAcceptancePolicy,
) -> MediaAcceptanceReport:
    issues: list[MediaAcceptanceIssue] = []
    if len(measurements) != policy.expected_track_count:
        issues.append(
            MediaAcceptanceIssue(
                "track_count",
                f"planned={policy.expected_track_count}, actual={len(measurements)}",
            )
        )
    for measurement in measurements:
        if not policy.minimum_duration_seconds <= measurement.duration_seconds <= policy.maximum_duration_seconds:
            issues.append(
                MediaAcceptanceIssue(
                    "duration",
                    (
                        f"{measurement.duration_seconds:.3f}s is outside "
                        f"{policy.minimum_duration_seconds:.3f}..{policy.maximum_duration_seconds:.3f}s"
                    ),
                    measurement.path.name,
                )
            )
        if not policy.minimum_integrated_lufs <= measurement.integrated_lufs <= policy.maximum_integrated_lufs:
            issues.append(
                MediaAcceptanceIssue(
                    "loudness",
                    (
                        f"{measurement.integrated_lufs:.3f} LUFS is outside "
                        f"{policy.minimum_integrated_lufs:.3f}..{policy.maximum_integrated_lufs:.3f} LUFS"
                    ),
                    measurement.path.name,
                )
            )
    if measurements:
        loudness_values = [measurement.integrated_lufs for measurement in measurements]
        deviation = max(loudness_values) - min(loudness_values)
        if deviation > policy.maximum_loudness_deviation_lu:
            issues.append(
                MediaAcceptanceIssue(
                    "loudness_deviation",
                    f"{deviation:.3f} LU exceeds {policy.maximum_loudness_deviation_lu:.3f} LU",
                )
            )
    return MediaAcceptanceReport(policy, measurements, tuple(issues))
