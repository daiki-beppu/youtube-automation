from __future__ import annotations

import pytest

from youtube_automation.domains.notifications import (
    NotificationEventCategory,
    NotificationEventKind,
    category_for,
)


@pytest.mark.parametrize(
    "kind",
    [
        NotificationEventKind.HANDOFF_COMPLETED,
        NotificationEventKind.PUBLISH_COMPLETED,
        NotificationEventKind.CANARY_COMPLETED,
        NotificationEventKind.HUMAN_TASKS_PENDING,
    ],
)
def test_category_for_classifies_successful_pipeline_events_as_normal(
    kind: NotificationEventKind,
) -> None:
    assert category_for(kind) is NotificationEventCategory.NORMAL


@pytest.mark.parametrize(
    "kind",
    [
        NotificationEventKind.NON_FAST_FORWARD_STOPPED,
        NotificationEventKind.FAIL_CLOSED_ABORTED,
        NotificationEventKind.GUARD_EXCEEDED,
        NotificationEventKind.CANARY_FAILED,
    ],
)
def test_category_for_classifies_stopped_pipeline_events_as_abnormal(
    kind: NotificationEventKind,
) -> None:
    assert category_for(kind) is NotificationEventCategory.ABNORMAL
