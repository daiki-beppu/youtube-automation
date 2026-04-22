"""utils/lyria_client.py のユニットテスト。"""

from __future__ import annotations

import base64
import os
from unittest.mock import MagicMock, patch

import pytest

from youtube_automation.utils.exceptions import ConfigError


@pytest.fixture(autouse=True)
def clean_env():
    saved = os.environ.pop("GOOGLE_CLOUD_PROJECT", None)
    yield
    if saved is None:
        os.environ.pop("GOOGLE_CLOUD_PROJECT", None)
    else:
        os.environ["GOOGLE_CLOUD_PROJECT"] = saved


@pytest.fixture
def mock_token():
    with patch("youtube_automation.utils.lyria_client._access_token", return_value="fake-token"):
        yield


def _ok_response(audio_bytes: bytes) -> MagicMock:
    resp = MagicMock()
    resp.ok = True
    resp.json.return_value = {
        "status": "completed",
        "outputs": [
            {"type": "text", "text": "lyrics"},
            {"type": "audio", "mime_type": "audio/mpeg", "data": base64.b64encode(audio_bytes).decode()},
        ],
    }
    return resp


class TestGenerateMusic:
    def test_returns_audio_bytes_on_success(self, mock_token):
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"
        audio = b"\xff\xfb\x90\x00fake-mp3"

        from youtube_automation.utils import lyria_client

        with patch.object(lyria_client.requests, "post", return_value=_ok_response(audio)) as mock_post:
            result = lyria_client.generate_music("ambient test", "lyria-3-pro-preview")

        assert result == audio
        args, kwargs = mock_post.call_args
        assert args[0] == "https://aiplatform.googleapis.com/v1beta1/projects/my-project/locations/global/interactions"
        assert kwargs["json"] == {
            "model": "lyria-3-pro-preview",
            "input": [{"type": "text", "text": "ambient test"}],
        }
        assert kwargs["headers"]["Authorization"] == "Bearer fake-token"

    def test_without_project_raises_config_error(self):
        from youtube_automation.utils import lyria_client

        with pytest.raises(ConfigError, match="GOOGLE_CLOUD_PROJECT"):
            lyria_client.generate_music("prompt", "lyria-3-pro-preview")

    def test_returns_none_on_http_error(self, mock_token):
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"

        resp = MagicMock()
        resp.ok = False
        resp.status_code = 400
        resp.text = "INVALID_ARGUMENT"

        from youtube_automation.utils import lyria_client

        with patch.object(lyria_client.requests, "post", return_value=resp):
            result = lyria_client.generate_music("p", "lyria-3-pro-preview")

        assert result is None

    def test_returns_none_when_no_audio_in_response(self, mock_token):
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"

        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {"status": "completed", "outputs": [{"type": "text", "text": "only text"}]}

        from youtube_automation.utils import lyria_client

        with patch.object(lyria_client.requests, "post", return_value=resp):
            result = lyria_client.generate_music("p", "lyria-3-pro-preview")

        assert result is None

    def test_returns_none_on_network_exception(self, mock_token):
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"

        from youtube_automation.utils import lyria_client

        with patch.object(lyria_client.requests, "post", side_effect=lyria_client.requests.ConnectionError("boom")):
            result = lyria_client.generate_music("p", "lyria-3-pro-preview")

        assert result is None
