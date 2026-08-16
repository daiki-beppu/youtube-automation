"""Provider-neutral pipeline notification events."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class NotificationEventCategory(StrEnum):
    NORMAL = "normal"
    ABNORMAL = "abnormal"


class NotificationEventKind(StrEnum):
    HANDOFF_COMPLETED = "handoff_completed"
    PUBLISH_COMPLETED = "publish_completed"
    NON_FAST_FORWARD_STOPPED = "non_fast_forward_stopped"
    FAIL_CLOSED_ABORTED = "fail_closed_aborted"
    GUARD_EXCEEDED = "guard_exceeded"
    CANARY_COMPLETED = "canary_completed"
    CANARY_FAILED = "canary_failed"


_CATEGORY_BY_KIND = {
    NotificationEventKind.HANDOFF_COMPLETED: NotificationEventCategory.NORMAL,
    NotificationEventKind.PUBLISH_COMPLETED: NotificationEventCategory.NORMAL,
    NotificationEventKind.NON_FAST_FORWARD_STOPPED: NotificationEventCategory.ABNORMAL,
    NotificationEventKind.FAIL_CLOSED_ABORTED: NotificationEventCategory.ABNORMAL,
    NotificationEventKind.GUARD_EXCEEDED: NotificationEventCategory.ABNORMAL,
    NotificationEventKind.CANARY_COMPLETED: NotificationEventCategory.NORMAL,
    NotificationEventKind.CANARY_FAILED: NotificationEventCategory.ABNORMAL,
}


@dataclass(frozen=True, slots=True)
class NotificationEvent:
    kind: NotificationEventKind
    channel: str
    collection: str
    stage: str


class NotificationSink(Protocol):
    def send(self, event: NotificationEvent) -> bool: ...


def category_for(kind: NotificationEventKind) -> NotificationEventCategory:
    """Return the stable operator-facing classification for an event kind."""

    return _CATEGORY_BY_KIND[kind]
