"""utils/genai_client.py のユニットテスト。

環境変数による AI Studio / Vertex AI 切替ロジックを検証する:

1. デフォルト (GOOGLE_GENAI_USE_VERTEXAI 未設定) → `genai.Client(api_key=...)`
2. GOOGLE_GENAI_USE_VERTEXAI=true + PROJECT 設定 → `genai.Client(vertexai=True, project, location)`
3. GOOGLE_GENAI_USE_VERTEXAI=true + PROJECT 未設定 → ConfigError
4. GOOGLE_CLOUD_LOCATION が反映される
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from youtube_automation.utils.exceptions import ConfigError

_ENV_KEYS = ("GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION")


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
    def test_default_uses_api_key(self):
        """環境変数未設定時は API キーモードで初期化される"""
        from youtube_automation.utils import genai_client

        with (
            patch.object(genai_client, "get_gemini_api_key", return_value="test-key"),
            patch.object(genai_client.genai, "Client") as mock_client,
        ):
            genai_client.create_genai_client()

        mock_client.assert_called_once_with(api_key="test-key")

    def test_vertex_mode_true_uses_vertex(self):
        """GOOGLE_GENAI_USE_VERTEXAI=true で Vertex AI モードに切り替わる"""
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"

        from youtube_automation.utils import genai_client

        with patch.object(genai_client.genai, "Client") as mock_client:
            genai_client.create_genai_client()

        mock_client.assert_called_once_with(vertexai=True, project="my-project", location="us-central1")

    def test_vertex_mode_case_insensitive(self):
        """GOOGLE_GENAI_USE_VERTEXAI は大文字小文字を問わず真偽を判定する"""
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "TRUE"
        os.environ["GOOGLE_CLOUD_PROJECT"] = "p"

        from youtube_automation.utils import genai_client

        with patch.object(genai_client.genai, "Client") as mock_client:
            genai_client.create_genai_client()

        assert mock_client.call_args.kwargs["vertexai"] is True

    def test_vertex_mode_accepts_numeric_truthy(self):
        """GOOGLE_GENAI_USE_VERTEXAI=1 も真として扱われる"""
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "1"
        os.environ["GOOGLE_CLOUD_PROJECT"] = "p"

        from youtube_automation.utils import genai_client

        with patch.object(genai_client.genai, "Client") as mock_client:
            genai_client.create_genai_client()

        assert mock_client.call_args.kwargs["vertexai"] is True

    def test_vertex_mode_false_falls_back_to_api_key(self):
        """GOOGLE_GENAI_USE_VERTEXAI=false は API キーモードのまま"""
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "false"

        from youtube_automation.utils import genai_client

        with (
            patch.object(genai_client, "get_gemini_api_key", return_value="test-key"),
            patch.object(genai_client.genai, "Client") as mock_client,
        ):
            genai_client.create_genai_client()

        mock_client.assert_called_once_with(api_key="test-key")

    def test_vertex_mode_without_project_raises_config_error(self):
        """Vertex AI モードで PROJECT 未設定なら ConfigError"""
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"

        from youtube_automation.utils import genai_client

        with pytest.raises(ConfigError, match="GOOGLE_CLOUD_PROJECT"):
            genai_client.create_genai_client()

    def test_vertex_mode_respects_custom_location(self):
        """GOOGLE_CLOUD_LOCATION で location を上書きできる"""
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"
        os.environ["GOOGLE_CLOUD_LOCATION"] = "europe-west4"

        from youtube_automation.utils import genai_client

        with patch.object(genai_client.genai, "Client") as mock_client:
            genai_client.create_genai_client()

        mock_client.assert_called_once_with(vertexai=True, project="my-project", location="europe-west4")
