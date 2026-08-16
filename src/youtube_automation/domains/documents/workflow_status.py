"""Immutable document model for a read-only workflow status snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

ArtifactStatus = Literal["complete", "missing", "inconsistent"]
CollectionStatus = Literal["planning", "live", "complete"]


@dataclass(frozen=True)
class ArtifactStatusView:
    key: str
    label: str
    status: ArtifactStatus
    detail: str


@dataclass(frozen=True)
class CollectionStatusView:
    name: str
    slug: str
    status: CollectionStatus
    phase: str
    blocker: str
    next_action: str
    updated_at: str
    stalled_for: str
    stale: bool
    warnings: tuple[str, ...]
    artifacts: tuple[ArtifactStatusView, ...]


@dataclass(frozen=True)
class WorkflowStatusSnapshot:
    generated_at: datetime
    collections: tuple[CollectionStatusView, ...]
