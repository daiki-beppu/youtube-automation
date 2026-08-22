"""文書公開と state 投影の crash-safe 調停契約。"""

from __future__ import annotations

import pytest

from youtube_automation.application.documents.projection import publish_and_project
from youtube_automation.core.errors import WorkflowStateError


def test_projection_failure_converges_when_publish_is_retried() -> None:
    published: list[str] = []
    projected: list[str] = []
    attempts = 0

    def publish() -> str:
        published[:] = ["canonical-document"]
        return published[0]

    def project(document: str) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise WorkflowStateError("injected projection failure")
        projected[:] = [document]

    with pytest.raises(WorkflowStateError, match="injected projection failure"):
        publish_and_project(publish, project)

    assert published == ["canonical-document"]
    assert projected == []

    assert publish_and_project(publish, project) == "canonical-document"
    assert published == ["canonical-document"]
    assert projected == ["canonical-document"]


def test_publish_failure_never_runs_projection() -> None:
    projected = False

    def publish() -> str:
        raise OSError("injected publish failure")

    def project(_document: str) -> None:
        nonlocal projected
        projected = True

    with pytest.raises(OSError, match="injected publish failure"):
        publish_and_project(publish, project)

    assert projected is False
