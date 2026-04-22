"""utils/genai_client.py のユニットテスト。

Vertex AI 1 本化後の検証:

1. `GOOGLE_CLOUD_PROJECT` が設定されていれば `genai.Client(vertexai=True, project, location)` が呼ばれる
2. `GOOGLE_CLOUD_PROJECT` 未設定なら `ConfigError`
3. `GOOGLE_CLOUD_LOCATION` が反映される（既定値 us-central1）
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from youtube_automation.utils.exceptions import ConfigError

_ENV_KEYS = ("GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION")


@pytest.fixture(autouse=True)
def clean_env():
    """各テスト前後で関連環境変数をクリーンにする"""
    saved = {k: os.environ.pop(k, None) for k in _ENV_KEYS}
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


class TestCreateGenaiClient:
    def test_uses_vertex_with_project(self):
        """GOOGLE_CLOUD_PROJECT が設定されていれば Vertex AI モードで初期化される"""
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"

        from youtube_automation.utils import genai_client

        with patch.object(genai_client.genai, "Client") as mock_client:
            genai_client.create_genai_client()

        mock_client.assert_called_once_with(vertexai=True, project="my-project", location="us-central1")

    def test_without_project_raises_config_error(self):
        """GOOGLE_CLOUD_PROJECT 未設定なら ConfigError"""
        from youtube_automation.utils import genai_client

        with pytest.raises(ConfigError, match="GOOGLE_CLOUD_PROJECT"):
            genai_client.create_genai_client()

    def test_respects_custom_location(self):
        """GOOGLE_CLOUD_LOCATION で location を上書きできる"""
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"
        os.environ["GOOGLE_CLOUD_LOCATION"] = "europe-west4"

        from youtube_automation.utils import genai_client

        with patch.object(genai_client.genai, "Client") as mock_client:
            genai_client.create_genai_client()

        mock_client.assert_called_once_with(vertexai=True, project="my-project", location="europe-west4")
