"""Shared readiness/completion base for cloud stage policy adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Protocol

from youtube_automation.core.errors import ValidationError


class StageReadiness(Protocol):
    """stage policy が readiness 値に求める最小契約。"""

    @property
    def status(self) -> str: ...

    @property
    def collection(self) -> Path | None: ...


class OpaqueMediaHandoff(Protocol):
    """media handoff 設定を「None 判定だけする不透明値」として表す marker。

    実体は `application.hybrid_runner.MediaHandoffRequest` だが、`domains/` は
    `application/` に依存できないため、中身を参照しない marker 型として受け取る。
    """


@dataclass(slots=True)
class ReadinessStagePolicy:
    """readiness → verify → allowlist を辿る cloud stage adapter の共通土台。

    media handoff は pipeline stage 専用のため、この土台を使う stage は構築時点
    （= runner が resource probe などの副作用へ進む前）で必ず拒否する。
    """

    stage_label: ClassVar[str]

    root: Path
    prompt: str
    media_handoff: OpaqueMediaHandoff | None = None
    _readiness: StageReadiness | None = field(init=False, default=None, repr=False)
    _completed: Path | None = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        if self.media_handoff is not None:
            raise ValidationError(f"{self.stage_label} stage は media handoff を受け付けません")

    @property
    def waiting(self) -> bool:
        return self._readiness is not None and self._readiness.status == "waiting"

    @property
    def collection_name(self) -> str | None:
        collection = self._completed or (self._readiness.collection if self._readiness else None)
        return collection.name if collection else None
