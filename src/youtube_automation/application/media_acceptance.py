"""Pull 済み音源の受入検証 orchestration。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.media.acceptance import (
    AudioMeasurement,
    MediaAcceptancePolicy,
    MediaAcceptanceReport,
    evaluate_media_acceptance,
)
from youtube_automation.domains.media.loudness_receipt import list_audio_files


class AudioInspector(Protocol):
    def inspect(self, path: Path) -> AudioMeasurement: ...


class MediaAcceptanceEventKind(StrEnum):
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class MediaAcceptanceEvent:
    kind: MediaAcceptanceEventKind
    collection: str
    issue_codes: tuple[str, ...]
    detail: str


MediaAcceptanceEventSink = Callable[[MediaAcceptanceEvent], None]


def _emit_rejection(
    collection: Path,
    issue_codes: tuple[str, ...],
    detail: str,
    on_event: MediaAcceptanceEventSink | None,
) -> None:
    if on_event is not None:
        on_event(MediaAcceptanceEvent(MediaAcceptanceEventKind.REJECTED, collection.name, issue_codes, detail))


def validate_collection_audio(
    collection: Path,
    policy: MediaAcceptancePolicy,
    inspector: AudioInspector,
    *,
    on_event: MediaAcceptanceEventSink | None = None,
) -> MediaAcceptanceReport:
    try:
        files = list_audio_files(collection)
        measurements = tuple(inspector.inspect(path) for path in files)
    except ValidationError as error:
        _emit_rejection(collection, ("probe",), str(error), on_event)
        raise
    report = evaluate_media_acceptance(measurements, policy)
    if report.passed:
        return report
    issue_codes = tuple(dict.fromkeys(issue.code for issue in report.issues))
    detail = "; ".join(
        f"{issue.code}{f'[{issue.file}]' if issue.file else ''}: {issue.message}" for issue in report.issues
    )
    _emit_rejection(collection, issue_codes, detail, on_event)
    raise ValidationError(f"media acceptance failed: {detail}")
