"""Vertex AI 専用 google-genai client factory の unit test."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from google.auth.exceptions import DefaultCredentialsError

from youtube_automation.utils.exceptions import ConfigError


@pytest.fixture(autouse=True)
def clean_project_env():
    """project の process override を各テスト間で分離する."""
    saved = os.environ.pop("GOOGLE_CLOUD_PROJECT", None)
    yield
    if saved is None:
        os.environ.pop("GOOGLE_CLOUD_PROJECT", None)
    else:
        os.environ["GOOGLE_CLOUD_PROJECT"] = saved


@pytest.fixture
def mock_adc():
    """`google.auth.default()` を差し替える。既定では project を返さない."""
    with patch(
        "youtube_automation.utils.google_cloud_project.google_auth_default",
        return_value=(MagicMock(), None),
    ) as mocked:
        yield mocked


class TestCreateGenaiClient:
    def test_process_project_override_uses_vertex_ai(self, mock_adc):
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"

        from youtube_automation.utils import genai_client

        with patch.object(genai_client.genai, "Client") as mock_client:
            genai_client.create_global_genai_client()

        mock_client.assert_called_once_with(vertexai=True, project="my-project", location="global")
        mock_adc.assert_not_called()

    def test_falls_back_to_adc_quota_project(self, mock_adc):
        mock_adc.return_value = (MagicMock(), "adc-project")

        from youtube_automation.utils import genai_client

        with patch.object(genai_client.genai, "Client") as mock_client:
            genai_client.create_global_genai_client()

        mock_client.assert_called_once_with(vertexai=True, project="adc-project", location="global")

    def test_without_project_raises_config_error(self, mock_adc):
        from youtube_automation.utils import genai_client

        with pytest.raises(ConfigError, match="ADC credentials に project_id が含まれていません"):
            genai_client.create_global_genai_client()

    def test_adc_unavailable_raises_config_error(self, mock_adc):
        mock_adc.side_effect = DefaultCredentialsError("no ADC")

        from youtube_automation.utils import genai_client

        with pytest.raises(ConfigError, match="GCP project_id を解決できません"):
            genai_client.create_global_genai_client()

    def test_global_factory_ignores_location_environment(self, mock_adc, monkeypatch):
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"
        monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "europe-west4")
        monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "false")

        from youtube_automation.utils import genai_client

        with patch.object(genai_client.genai, "Client") as mock_client:
            genai_client.create_global_genai_client()

        mock_client.assert_called_once_with(vertexai=True, project="my-project", location="global")

    def test_veo_factory_uses_us_central1(self, mock_adc):
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"

        from youtube_automation.utils import genai_client

        with patch.object(genai_client.genai, "Client") as mock_client:
            genai_client.create_veo_genai_client()

        mock_client.assert_called_once_with(vertexai=True, project="my-project", location="us-central1")
