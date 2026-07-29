"""Gemini Omni Flash image-to-video 生成の単体テスト。"""

from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import httpx
import pytest

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


@pytest.mark.parametrize(
    "output_video",
    [
        None,
        SimpleNamespace(data=None, uri=None),
        SimpleNamespace(data="not valid base64!", uri=None),
    ],
    ids=["missing-video", "missing-data-and-uri", "invalid-base64"],
)
def test_invalid_inline_responses_fail_without_output_or_smoothing(tmp_path: Path, output_video: object) -> None:
    image, output = _paths(tmp_path)
    client = MagicMock()
    client.interactions.create.return_value = SimpleNamespace(output_video=output_video)

    with patch.object(omni_generator, "smooth_loop") as smooth:
        result = omni_generator.generate_loop_video(client, image, output, omni_generator.DEFAULT_MODEL, "prompt")

    assert result is False
    assert not output.exists()
    client.files.get.assert_not_called()
    client.files.download.assert_not_called()
    smooth.assert_not_called()


def test_malformed_uri_fails_without_files_api_or_output(tmp_path: Path) -> None:
    image, output = _paths(tmp_path)
    client = MagicMock()
    client.interactions.create.return_value = SimpleNamespace(
        output_video=SimpleNamespace(data=None, uri="https://example.test/not-a-file")
    )

    with patch.object(omni_generator, "smooth_loop") as smooth:
        result = omni_generator.generate_loop_video(client, image, output, omni_generator.DEFAULT_MODEL, "prompt")

    assert result is False
    assert not output.exists()
    client.files.get.assert_not_called()
    client.files.download.assert_not_called()
    smooth.assert_not_called()


def test_files_get_error_fails_without_download_or_output(tmp_path: Path) -> None:
    image, output = _paths(tmp_path)
    client = MagicMock()
    client.interactions.create.return_value = SimpleNamespace(
        output_video=SimpleNamespace(data=None, uri="https://example.test/v1beta/files/get-error")
    )
    client.files.get.side_effect = httpx.ReadError("state request failed")

    with patch.object(omni_generator, "smooth_loop") as smooth:
        result = omni_generator.generate_loop_video(client, image, output, omni_generator.DEFAULT_MODEL, "prompt")

    assert result is False
    assert not output.exists()
    client.files.download.assert_not_called()
    smooth.assert_not_called()


def test_files_download_error_fails_without_output_or_smoothing(tmp_path: Path) -> None:
    image, output = _paths(tmp_path)
    client = MagicMock()
    uri = "https://example.test/v1beta/files/download-error"
    client.interactions.create.return_value = SimpleNamespace(output_video=SimpleNamespace(data=None, uri=uri))
    client.files.get.return_value = SimpleNamespace(state="ACTIVE")
    client.files.download.side_effect = httpx.ReadError("download failed")

    with patch.object(omni_generator, "smooth_loop") as smooth:
        result = omni_generator.generate_loop_video(client, image, output, omni_generator.DEFAULT_MODEL, "prompt")

    assert result is False
    assert not output.exists()
    client.files.download.assert_called_once_with(file=uri)
    smooth.assert_not_called()


def test_uri_video_cancelled_state_returns_false_without_download_or_output(tmp_path: Path) -> None:
    image, output = _paths(tmp_path)
    client = MagicMock()
    client.interactions.create.return_value = SimpleNamespace(
        output_video=SimpleNamespace(data=None, uri="https://example.test/v1beta/files/cancelled-id")
    )
    client.files.get.return_value = SimpleNamespace(state="CANCELLED")

    with patch.object(omni_generator, "smooth_loop") as smooth:
        result = omni_generator.generate_loop_video(client, image, output, omni_generator.DEFAULT_MODEL, "prompt")

    assert result is False
    assert not output.exists()
    client.files.download.assert_not_called()
    smooth.assert_not_called()


@pytest.mark.parametrize(
    ("compression", "expected_crf", "expected_preset"),
    [
        ({"enabled": True, "crf": 27, "preset": "fast"}, 27, "fast"),
        ({"enabled": False, "crf": 27, "preset": "fast"}, 18, "slow"),
    ],
    ids=["configured", "disabled"],
)
def test_smooth_failure_keeps_generated_video_and_resolves_compression(
    tmp_path: Path,
    compression: dict[str, object],
    expected_crf: int,
    expected_preset: str,
) -> None:
    image, output = _paths(tmp_path)
    client = MagicMock()
    client.interactions.create.return_value = SimpleNamespace(
        output_video=SimpleNamespace(data=base64.b64encode(b"generated").decode(), uri=None)
    )

    with patch.object(omni_generator, "smooth_loop", return_value=False) as smooth:
        result = omni_generator.generate_loop_video(
            client,
            image,
            output,
            omni_generator.DEFAULT_MODEL,
            "prompt",
            compression=compression,
        )

    assert result is True
    assert output.read_bytes() == b"generated"
    client.files.download.assert_not_called()
    smooth.assert_called_once_with(
        output,
        crossfade_sec=0.5,
        trim_tail_sec=1.0,
        crf=expected_crf,
        preset=expected_preset,
    )
