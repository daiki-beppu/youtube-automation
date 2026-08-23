from __future__ import annotations

from youtube_automation.domains.notifications import (
    NotificationEventKind,
    category_for,
)


def test_notification_kinds_have_stable_operator_classification() -> None:
    assert category_for(NotificationEventKind.PUBLISH_COMPLETED).value == "normal"
    assert category_for(NotificationEventKind.NON_FAST_FORWARD_STOPPED).value == "abnormal"
