"""GCP project ID の明示 override 優先順位テスト。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from youtube_automation.infrastructure.runtime import google_cloud_project


def test_explicit_project_override_precedes_environment_and_adc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "environment-project")
    adc = MagicMock(return_value=(object(), "adc-project"))
    monkeypatch.setattr(google_cloud_project, "google_auth_default", adc)

    assert google_cloud_project.resolve_project_id("explicit-project") == "explicit-project"
    adc.assert_not_called()
