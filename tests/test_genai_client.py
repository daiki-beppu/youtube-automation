"""utils/genai_client.py のユニットテスト。

Vertex AI 1 本化後の検証:

1. `GOOGLE_CLOUD_PROJECT` が設定されていれば `genai.Client(vertexai=True, project, location)` が呼ばれる
2. env 未設定でも ADC quota project から fallback で取得できる
3. env と ADC 双方が空なら `ConfigError`
4. `GOOGLE_CLOUD_LOCATION` が反映される（既定値 us-central1）
5. `location` 引数は env より優先される (#56: モデル別 region 切替)
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from google.auth.exceptions import DefaultCredentialsError

from youtube_automation.infrastructure.errors import ConfigError

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


@pytest.fixture
def mock_adc():
    """`google.auth.default()` を差し替える。デフォルトでは project None を返す。"""
    with patch(
        "youtube_automation.utils.google_cloud_project.google_auth_default",
        return_value=(MagicMock(), None),
    ) as m:
        yield m


class TestCreateGenaiClient:
    def test_uses_vertex_with_project(self, mock_adc):
        """GOOGLE_CLOUD_PROJECT が設定されていれば Vertex AI モードで初期化される"""
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"

        from youtube_automation.utils import genai_client

        with patch.object(genai_client.genai, "Client") as mock_client:
            genai_client.create_genai_client()

        mock_client.assert_called_once_with(vertexai=True, project="my-project", location="us-central1")
        mock_adc.assert_not_called()

    def test_falls_back_to_adc_project(self, mock_adc):
        """env 未設定なら ADC quota project から自動解決する"""
        mock_adc.return_value = (MagicMock(), "adc-project")

        from youtube_automation.utils import genai_client

        with patch.object(genai_client.genai, "Client") as mock_client:
            genai_client.create_genai_client()

        mock_client.assert_called_once_with(vertexai=True, project="adc-project", location="us-central1")

    def test_without_project_raises_config_error(self, mock_adc):
        """env も ADC も project_id を持たないなら ConfigError"""
        from youtube_automation.utils import genai_client

        with pytest.raises(ConfigError, match="ADC credentials に project_id が含まれていません"):
            genai_client.create_genai_client()

    def test_adc_unavailable_raises_config_error(self, mock_adc):
        """ADC 自体が初期化されていなければ ConfigError"""
        mock_adc.side_effect = DefaultCredentialsError("no ADC")

        from youtube_automation.utils import genai_client

        with pytest.raises(ConfigError, match="GCP project_id を解決できません"):
            genai_client.create_genai_client()

    def test_respects_custom_location(self, mock_adc):
        """GOOGLE_CLOUD_LOCATION で location を上書きできる"""
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"
        os.environ["GOOGLE_CLOUD_LOCATION"] = "europe-west4"

        from youtube_automation.utils import genai_client

        with patch.object(genai_client.genai, "Client") as mock_client:
            genai_client.create_genai_client()

        mock_client.assert_called_once_with(vertexai=True, project="my-project", location="europe-west4")

    def test_location_argument_overrides_env(self, mock_adc):
        """`location` 引数は GOOGLE_CLOUD_LOCATION よりも優先される (画像 global / Veo us-central1 の両立用)"""
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"
        os.environ["GOOGLE_CLOUD_LOCATION"] = "europe-west4"

        from youtube_automation.utils import genai_client

        with patch.object(genai_client.genai, "Client") as mock_client:
            genai_client.create_genai_client(location="global")

        mock_client.assert_called_once_with(vertexai=True, project="my-project", location="global")

    def test_location_argument_without_env(self, mock_adc):
        """env が無くても `location` 引数だけで切替可能"""
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"

        from youtube_automation.utils import genai_client

        with patch.object(genai_client.genai, "Client") as mock_client:
            genai_client.create_genai_client(location="us-central1")

        mock_client.assert_called_once_with(vertexai=True, project="my-project", location="us-central1")
