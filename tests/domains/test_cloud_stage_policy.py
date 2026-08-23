from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import pytest

from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.cloud_planning import PlanningStagePolicy
from youtube_automation.domains.cloud_stage_policy import ReadinessStagePolicy
from youtube_automation.domains.post_publish import PostPublishStagePolicy


@dataclass(frozen=True, slots=True)
class _Readiness:
    status: str
    collection: Path | None


@dataclass(slots=True)
class _StubStagePolicy(ReadinessStagePolicy):
    stage_label: ClassVar[str] = "stub"


def test_readiness_driven_stage_policies_share_one_base() -> None:
    assert issubclass(PlanningStagePolicy, ReadinessStagePolicy)
    assert issubclass(PostPublishStagePolicy, ReadinessStagePolicy)


def test_waiting_and_collection_name_follow_readiness_then_completion(tmp_path: Path) -> None:
    policy = _StubStagePolicy(tmp_path, "/prompt")

    assert policy.waiting is False
    assert policy.collection_name is None

    policy._readiness = _Readiness("waiting", tmp_path / "demo")
    assert policy.waiting is True
    assert policy.collection_name == "demo"

    policy._readiness = _Readiness("ready", None)
    assert policy.waiting is False
    assert policy.collection_name is None

    policy._completed = tmp_path / "confirmed"
    assert policy.collection_name == "confirmed"


def test_base_rejects_media_handoff_with_the_stage_label(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="stub stage は media handoff を受け付けません"):
        _StubStagePolicy(tmp_path, "/prompt", object())
