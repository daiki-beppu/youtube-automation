"""オーディオ設定の責務別 dataclass（bobble 独自・optional）."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Audio:
    """`audio` セクション（optional、bobble のみ）."""

    target_duration_min: float | None = None
    target_duration_max: float | None = None
    chapter_max: int = 100
