"""Gemini Omni Flash image-to-video 生成の単体テスト。"""

from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import httpx

from youtube_automation.utils import omni_generator


def _paths(tmp_path: Path) -> tuple[Path, Path]:
    image = tmp_path / "main.png"
    image.write_bytes(b"image")
    return image, tmp_path / "loop.mp4"


def test_create_client_uses_managed_gemini_api_key() -> None:
    with (
        patch.object(omni_generator, "get_secret", return_value="managed-key") as get_secret,
        patch.object(omni_generator.genai, "Client", return_value="client") as client_factory,
    ):
        client = omni_generator.create_omni_client()

    assert client == "client"
    get_secret.assert_called_once_with("GEMINI_API_KEY")
    client_factory.assert_called_once_with(api_key="managed-key")


def test_inline_video_success_writes_output_and_smooths(tmp_path: Path) -> None:
    image, output = _paths(tmp_path)
    client = MagicMock()
    client.interactions.create.return_value = SimpleNamespace(
        output_video=SimpleNamespace(data=base64.b64encode(b"video").decode(), uri=None)
    )

    with patch.object(omni_generator, "smooth_loop", return_value=True) as smooth:
        result = omni_generator.generate_loop_video(
            client,
            image,
            output,
            "omni-override",
            "gentle movement",
        )

    assert result is True
    assert output.read_bytes() == b"video"
    request = client.interactions.create.call_args.kwargs
    assert request["model"] == "omni-override"
    assert request["generation_config"] == {"video_config": {"task": "image_to_video"}}
    assert request["response_format"]["delivery"] == "uri"
    assert request["input"][0]["mime_type"] == "image/png"
    smooth.assert_called_once_with(output, crossfade_sec=0.5, trim_tail_sec=1.0, crf=18, preset="slow")


def test_uri_video_polls_until_active_then_downloads(tmp_path: Path) -> None:
    image, output = _paths(tmp_path)
    client = MagicMock()
    uri = "https://generativelanguage.googleapis.com/v1beta/files/abc123:download?alt=media"
    client.interactions.create.return_value = SimpleNamespace(output_video=SimpleNamespace(data=None, uri=uri))
    client.files.get.side_effect = [SimpleNamespace(state="PROCESSING"), SimpleNamespace(state="ACTIVE")]
    client.files.download.return_value = b"downloaded"

    with (
        patch.object(omni_generator.time, "sleep") as sleep,
        patch.object(omni_generator, "smooth_loop", return_value=True),
    ):
        result = omni_generator.generate_loop_video(
            client,
            image,
            output,
            omni_generator.DEFAULT_MODEL,
            "prompt",
            poll_interval_sec=0.25,
        )

    assert result is True
    assert output.read_bytes() == b"downloaded"
    assert client.files.get.call_args_list == [call(name="files/abc123"), call(name="files/abc123")]
    client.files.download.assert_called_once_with(file=uri)
    sleep.assert_called_once_with(0.25)


def test_uri_video_failed_state_returns_false_without_output(tmp_path: Path) -> None:
    image, output = _paths(tmp_path)
    client = MagicMock()
    client.interactions.create.return_value = SimpleNamespace(
        output_video=SimpleNamespace(data=None, uri="https://example.test/v1beta/files/failed-id:download")
    )
    client.files.get.return_value = SimpleNamespace(state=SimpleNamespace(name="FAILED"))

    result = omni_generator.generate_loop_video(client, image, output, omni_generator.DEFAULT_MODEL, "prompt")

    assert result is False
    assert not output.exists()
    client.files.download.assert_not_called()


def test_uri_video_timeout_returns_false_without_output(tmp_path: Path) -> None:
    image, output = _paths(tmp_path)
    client = MagicMock()
    client.interactions.create.return_value = SimpleNamespace(
        output_video=SimpleNamespace(data=None, uri="https://example.test/v1beta/files/slow-id:download")
    )
    client.files.get.return_value = SimpleNamespace(state="PROCESSING")

    with (
        patch.object(omni_generator.time, "monotonic", side_effect=[0.0, 0.0, 2.0]),
        patch.object(omni_generator.time, "sleep"),
    ):
        result = omni_generator.generate_loop_video(
            client,
            image,
            output,
            omni_generator.DEFAULT_MODEL,
            "prompt",
            timeout_sec=1,
        )

    assert result is False
    assert not output.exists()


def test_interactions_timeout_returns_false(tmp_path: Path) -> None:
    image, output = _paths(tmp_path)
    client = MagicMock()
    client.interactions.create.side_effect = httpx.ReadTimeout("request timed out")

    result = omni_generator.generate_loop_video(client, image, output, omni_generator.DEFAULT_MODEL, "prompt")

    assert result is False
    assert not output.exists()
