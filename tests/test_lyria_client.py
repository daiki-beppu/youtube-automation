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


@pytest.fixture(autouse=True)
def mock_adc():
    """`google.auth.default()` を差し替える。デフォルトでは project None を返す。"""
    with patch(
        "youtube_automation.utils.google_cloud_project.google_auth_default",
        return_value=(MagicMock(), None),
    ) as m:
        yield m


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

        with pytest.raises(ConfigError, match="ADC credentials に project_id が含まれていません"):
            lyria_client.generate_music("prompt", "lyria-3-pro-preview")

    def test_falls_back_to_adc_project(self, mock_token, mock_adc):
        """env 未設定でも ADC quota project から URL を組み立てる"""
        mock_adc.return_value = (MagicMock(), "adc-project")
        audio = b"\xff\xfb\x90\x00fake-mp3"

        from youtube_automation.utils import lyria_client

        with patch.object(lyria_client.requests, "post", return_value=_ok_response(audio)) as mock_post:
            result = lyria_client.generate_music("ambient test", "lyria-3-pro-preview")

        assert result == audio
        args, _ = mock_post.call_args
        assert args[0] == "https://aiplatform.googleapis.com/v1beta1/projects/adc-project/locations/global/interactions"

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

    def test_bpm_embedded_in_payload_prompt(self, mock_token):
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"
        audio = b"\xff\xfb\x90\x00fake-mp3"

        from youtube_automation.utils import lyria_client

        with patch.object(lyria_client.requests, "post", return_value=_ok_response(audio)) as mock_post:
            lyria_client.generate_music("solo piano", "lyria-3-pro-preview", bpm=120)

        _, kwargs = mock_post.call_args
        assert kwargs["json"]["input"][0]["text"] == "solo piano, 120 BPM"

    def test_intensity_embedded_in_payload_prompt(self, mock_token):
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"
        audio = b"\xff\xfb\x90\x00fake-mp3"

        from youtube_automation.utils import lyria_client

        with patch.object(lyria_client.requests, "post", return_value=_ok_response(audio)) as mock_post:
            lyria_client.generate_music("solo piano", "lyria-3-pro-preview", intensity="low")

        _, kwargs = mock_post.call_args
        assert kwargs["json"]["input"][0]["text"].startswith("mellow, low-energy, solo piano")

    def test_mode_embedded_in_payload_prompt(self, mock_token):
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"
        audio = b"\xff\xfb\x90\x00fake-mp3"

        from youtube_automation.utils import lyria_client

        with patch.object(lyria_client.requests, "post", return_value=_ok_response(audio)) as mock_post:
            lyria_client.generate_music("solo piano", "lyria-3-pro-preview", mode="instrumental")

        _, kwargs = mock_post.call_args
        assert kwargs["json"]["input"][0]["text"] == "solo piano. Instrumental."

    def test_lyrics_embedded_in_payload_prompt(self, mock_token):
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"
        audio = b"\xff\xfb\x90\x00fake-mp3"

        from youtube_automation.utils import lyria_client

        with patch.object(lyria_client.requests, "post", return_value=_ok_response(audio)) as mock_post:
            lyria_client.generate_music("solo piano", "lyria-3-pro-preview", lyrics="[Verse]\nla")

        _, kwargs = mock_post.call_args
        assert "Lyrics: [Verse]\nla" in kwargs["json"]["input"][0]["text"]

    def test_reference_image_added_to_payload_input(self, mock_token, tmp_path):
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"
        audio = b"\xff\xfb\x90\x00fake-mp3"
        img_path = tmp_path / "main.png"
        img_bytes = b"\x89PNG\r\n\x1a\nfake-image-bytes"
        img_path.write_bytes(img_bytes)

        from youtube_automation.utils import lyria_client

        with patch.object(lyria_client.requests, "post", return_value=_ok_response(audio)) as mock_post:
            lyria_client.generate_music("solo piano", "lyria-3-pro-preview", reference_image=img_path)

        _, kwargs = mock_post.call_args
        inputs = kwargs["json"]["input"]
        assert len(inputs) == 2
        assert inputs[0] == {"type": "text", "text": "solo piano"}
        assert inputs[1]["type"] == "image"
        assert inputs[1]["mime_type"] == "image/png"
        assert base64.b64decode(inputs[1]["data"]) == img_bytes

    def test_missing_reference_image_raises_config_error(self, mock_token, tmp_path):
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"
        missing = tmp_path / "missing.png"

        from youtube_automation.utils import lyria_client

        with pytest.raises(ConfigError, match="参照画像が存在しません"):
            lyria_client.generate_music("p", "lyria-3-pro-preview", reference_image=missing)


class TestComposePrompt:
    def test_none_params_returns_base_as_is(self):
        from youtube_automation.utils.lyria_client import _compose_prompt

        assert _compose_prompt("solo piano", None, None, None, None) == "solo piano"

    def test_bpm_appended_after_base(self):
        from youtube_automation.utils.lyria_client import _compose_prompt

        assert _compose_prompt("solo piano", 120, None, None, None) == "solo piano, 120 BPM"

    def test_intensity_low_prepended(self):
        from youtube_automation.utils.lyria_client import _compose_prompt

        result = _compose_prompt("solo piano", None, "low", None, None)
        assert result.startswith("mellow, low-energy, ")
        assert "solo piano" in result

    def test_intensity_medium_prepended(self):
        from youtube_automation.utils.lyria_client import _compose_prompt

        result = _compose_prompt("solo piano", None, "medium", None, None)
        assert result.startswith("balanced, moderate energy, ")

    def test_intensity_high_prepended(self):
        from youtube_automation.utils.lyria_client import _compose_prompt

        result = _compose_prompt("solo piano", None, "high", None, None)
        assert result.startswith("driving, high-energy, ")

    def test_mode_instrumental_appended(self):
        from youtube_automation.utils.lyria_client import _compose_prompt

        assert _compose_prompt("solo piano", None, None, "instrumental", None) == "solo piano. Instrumental."

    def test_mode_vocal_without_lyrics_appends_with_vocals(self):
        from youtube_automation.utils.lyria_client import _compose_prompt

        assert _compose_prompt("solo piano", None, None, "vocal", None) == "solo piano. With vocals."

    def test_mode_vocal_with_lyrics_skips_with_vocals(self):
        from youtube_automation.utils.lyria_client import _compose_prompt

        result = _compose_prompt("solo piano", None, None, "vocal", "[Verse]\nla la la")
        assert "With vocals" not in result
        assert "Lyrics: [Verse]\nla la la" in result

    def test_lyrics_appended(self):
        from youtube_automation.utils.lyria_client import _compose_prompt

        result = _compose_prompt("solo piano", None, None, None, "[Chorus]\nsing")
        assert result == "solo piano. Lyrics: [Chorus]\nsing"

    def test_all_params_combined_order(self):
        from youtube_automation.utils.lyria_client import _compose_prompt

        result = _compose_prompt("solo piano in A minor", 90, "low", "vocal", "[Verse]\nmelody")
        assert result == "mellow, low-energy, solo piano in A minor, 90 BPM. Lyrics: [Verse]\nmelody"

    def test_all_params_instrumental_with_lyrics(self):
        from youtube_automation.utils.lyria_client import _compose_prompt

        result = _compose_prompt("jazz trio", 130, "high", "instrumental", "hum")
        assert result == "driving, high-energy, jazz trio, 130 BPM. Instrumental. Lyrics: hum"


class TestEncodeReferenceImage:
    def test_png_encoded_with_correct_mime(self, tmp_path):
        from youtube_automation.utils.lyria_client import _encode_reference_image

        path = tmp_path / "img.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        result = _encode_reference_image(path)
        assert result["type"] == "image"
        assert result["mime_type"] == "image/png"
        assert base64.b64decode(result["data"]) == b"\x89PNG\r\n\x1a\nfake"

    def test_jpg_encoded_as_image_jpeg(self, tmp_path):
        from youtube_automation.utils.lyria_client import _encode_reference_image

        path = tmp_path / "img.jpg"
        path.write_bytes(b"\xff\xd8\xff\xe0fake-jpg")
        result = _encode_reference_image(path)
        assert result["mime_type"] == "image/jpeg"

    def test_jpeg_encoded_as_image_jpeg(self, tmp_path):
        from youtube_automation.utils.lyria_client import _encode_reference_image

        path = tmp_path / "img.jpeg"
        path.write_bytes(b"\xff\xd8\xff\xe0fake-jpg")
        result = _encode_reference_image(path)
        assert result["mime_type"] == "image/jpeg"

    def test_webp_encoded_as_image_webp(self, tmp_path):
        from youtube_automation.utils.lyria_client import _encode_reference_image

        path = tmp_path / "img.webp"
        path.write_bytes(b"RIFFxxxxWEBPfake")
        result = _encode_reference_image(path)
        assert result["mime_type"] == "image/webp"

    def test_unsupported_extension_raises_config_error(self, tmp_path):
        from youtube_automation.utils.lyria_client import _encode_reference_image

        path = tmp_path / "img.gif"
        path.write_bytes(b"GIF89afake")
        with pytest.raises(ConfigError, match="対応していない画像形式"):
            _encode_reference_image(path)

    def test_missing_file_raises_config_error(self, tmp_path):
        from youtube_automation.utils.lyria_client import _encode_reference_image

        path = tmp_path / "missing.png"
        with pytest.raises(ConfigError, match="参照画像が存在しません"):
            _encode_reference_image(path)
