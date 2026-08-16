"""MiniMax H3 loop video adapter contract tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, call

import pytest
from PIL import Image

from youtube_automation.core.errors import GeneratorError
from youtube_automation.infrastructure.media import minimax_video_generator


def _image(path: Path, size: tuple[int, int] = (1600, 900)) -> Path:
    Image.new("RGB", size, "navy").save(path)
    return path


def _mp4() -> bytes:
    return b"\x00\x00\x00\x18ftypmp42" + b"video"


def _success_responses() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    return (
        {"task_id": "task-1", "base_resp": {"status_code": 0, "status_msg": "success"}},
        {
            "task_id": "task-1",
            "status": "Success",
            "file_id": "file-1",
            "video_width": 1920,
            "video_height": 1080,
            "base_resp": {"status_code": 0, "status_msg": "success"},
        },
        {
            "file": {"file_id": "file-1", "download_url": "https://cdn.example/video.mp4"},
            "base_resp": {"status_code": 0, "status_msg": "success"},
        },
    )


def test_generates_h3_video_polls_downloads_logs_cost_and_clears_recovery_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = _image(tmp_path / "main.png")
    output = tmp_path / "loop.mp4"
    submit, success, retrieved = _success_responses()
    request_json = Mock(return_value=submit)
    get_json = Mock(side_effect=[success, retrieved])
    download_bytes = Mock(return_value=_mp4())
    log_generation = Mock(return_value={"category": "video"})
    monkeypatch.setattr(minimax_video_generator.minimax_client, "request_json", request_json)
    monkeypatch.setattr(minimax_video_generator.minimax_client, "get_json", get_json)
    monkeypatch.setattr(minimax_video_generator.minimax_client, "download_bytes", download_bytes)
    monkeypatch.setattr(minimax_video_generator.cost_tracker, "log_generation", log_generation)
    monkeypatch.setattr(minimax_video_generator.cost_tracker, "print_last_report", Mock())
    monkeypatch.setattr(minimax_video_generator, "smooth_loop", Mock(return_value=True))

    result = minimax_video_generator.generate_loop_video(
        image,
        output,
        "MiniMax-Hailuo-3",
        "[Static shot] gentle steam",
        duration_seconds=6,
        aspect_ratio="16:9",
        resolution="1080P",
        timeout_sec=30,
        poll_interval_sec=0,
        max_poll_retries=2,
    )

    assert result is True
    assert output.read_bytes() == _mp4()
    request_json.assert_called_once()
    payload = dict(request_json.call_args.args[1])
    image_data_url = payload.pop("first_frame_image")
    assert payload == {
        "model": "MiniMax-Hailuo-3",
        "prompt": "[Static shot] gentle steam",
        "duration": 6,
        "resolution": "1080P",
        "prompt_optimizer": False,
    }
    assert str(image_data_url).startswith("data:image/png;base64,")
    assert get_json.call_args_list == [
        call("/v1/query/video_generation", {"task_id": "task-1"}, timeout=30),
        call("/v1/files/retrieve", {"file_id": "file-1"}, timeout=30),
    ]
    download_bytes.assert_called_once_with("https://cdn.example/video.mp4", timeout=30)
    log_generation.assert_called_once()
    assert log_generation.call_args.args == ("video",)
    assert log_generation.call_args.kwargs["quantity"] == 6
    assert log_generation.call_args.kwargs["unit"] == "second"
    assert not minimax_video_generator.task_store.state_path(output).exists()


@pytest.mark.parametrize(
    ("prompt", "duration", "aspect_ratio", "size"),
    [
        ("", 6, "16:9", (1600, 900)),
        ("x" * 2001, 6, "16:9", (1600, 900)),
        ("valid", 8, "16:9", (1600, 900)),
        ("valid", 6, "4:3", (1600, 900)),
        ("valid", 6, "16:9", (300, 169)),
        ("valid", 6, "16:9", (1000, 1000)),
    ],
)
def test_invalid_paid_inputs_fail_before_submit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prompt: str,
    duration: int,
    aspect_ratio: str,
    size: tuple[int, int],
) -> None:
    image = _image(tmp_path / "main.png", size)
    request_json = Mock(side_effect=AssertionError("invalid input must not spend credits"))
    monkeypatch.setattr(minimax_video_generator.minimax_client, "request_json", request_json)

    assert (
        minimax_video_generator.generate_loop_video(
            image,
            tmp_path / "loop.mp4",
            "MiniMax-Hailuo-3",
            prompt,
            duration_seconds=duration,
            aspect_ratio=aspect_ratio,
            resolution="1080P",
            timeout_sec=30,
            poll_interval_sec=0,
            max_poll_retries=0,
        )
        is False
    )
    request_json.assert_not_called()


def test_symlink_image_fails_before_paid_submit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_image = _image(tmp_path / "real.png")
    image = tmp_path / "main.png"
    image.symlink_to(real_image)
    request_json = Mock(side_effect=AssertionError("symlink must not spend credits"))
    monkeypatch.setattr(minimax_video_generator.minimax_client, "request_json", request_json)

    assert (
        minimax_video_generator.generate_loop_video(
            image,
            tmp_path / "loop.mp4",
            "MiniMax-Hailuo-3",
            "valid prompt",
            duration_seconds=6,
            aspect_ratio="16:9",
            resolution="1080P",
            timeout_sec=30,
            poll_interval_sec=0,
            max_poll_retries=0,
        )
        is False
    )
    request_json.assert_not_called()


def test_resume_uses_saved_task_without_second_paid_submit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = _image(tmp_path / "main.png")
    output = tmp_path / "loop.mp4"
    minimax_video_generator.task_store.save(
        output,
        image,
        task_id="task-paid",
        model="MiniMax-Hailuo-3",
        prompt="gentle motion",
        duration_seconds=6,
        aspect_ratio="16:9",
        resolution="1080P",
        channel_root=tmp_path,
    )
    _submit, success, retrieved = _success_responses()
    success["task_id"] = "task-paid"
    request_json = Mock(side_effect=AssertionError("resume must not submit again"))
    monkeypatch.setattr(minimax_video_generator.task_store, "_resolve_channel_root", Mock(return_value=tmp_path))
    monkeypatch.setattr(minimax_video_generator.minimax_client, "request_json", request_json)
    monkeypatch.setattr(minimax_video_generator.minimax_client, "get_json", Mock(side_effect=[success, retrieved]))
    monkeypatch.setattr(minimax_video_generator.minimax_client, "download_bytes", Mock(return_value=_mp4()))
    monkeypatch.setattr(minimax_video_generator.cost_tracker, "log_generation", Mock())
    monkeypatch.setattr(minimax_video_generator.cost_tracker, "print_last_report", Mock())
    monkeypatch.setattr(minimax_video_generator, "smooth_loop", Mock(return_value=True))

    assert minimax_video_generator.generate_loop_video(
        image,
        output,
        "MiniMax-Hailuo-3",
        "gentle motion",
        duration_seconds=6,
        aspect_ratio="16:9",
        resolution="1080P",
        timeout_sec=30,
        poll_interval_sec=0,
        max_poll_retries=0,
    )
    request_json.assert_not_called()


def test_polling_transient_error_retries_without_resubmitting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = _image(tmp_path / "main.png")
    submit, success, retrieved = _success_responses()
    request_json = Mock(return_value=submit)
    monkeypatch.setattr(minimax_video_generator.minimax_client, "request_json", request_json)
    monkeypatch.setattr(
        minimax_video_generator.minimax_client,
        "get_json",
        Mock(side_effect=[GeneratorError("safe transient"), success, retrieved]),
    )
    monkeypatch.setattr(minimax_video_generator.minimax_client, "download_bytes", Mock(return_value=_mp4()))
    monkeypatch.setattr(minimax_video_generator.cost_tracker, "log_generation", Mock())
    monkeypatch.setattr(minimax_video_generator.cost_tracker, "print_last_report", Mock())
    monkeypatch.setattr(minimax_video_generator, "smooth_loop", Mock(return_value=True))
    monkeypatch.setattr(minimax_video_generator.time, "sleep", Mock())

    assert minimax_video_generator.generate_loop_video(
        image,
        tmp_path / "loop.mp4",
        "MiniMax-Hailuo-3",
        "gentle motion",
        duration_seconds=6,
        aspect_ratio="16:9",
        resolution="1080P",
        timeout_sec=30,
        poll_interval_sec=0,
        max_poll_retries=1,
    )
    request_json.assert_called_once()


@pytest.mark.parametrize(
    "query_response",
    [
        {"status": "Success", "file_id": "file-1", "video_width": 1000, "video_height": 1000},
        {"status": "Unknown"},
        {"status": "Fail"},
        [],
    ],
)
def test_invalid_or_failed_query_response_keeps_output_absent_and_cost_unlogged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    query_response: object,
) -> None:
    image = _image(tmp_path / "main.png")
    output = tmp_path / "loop.mp4"
    submit, _success, _retrieved = _success_responses()
    monkeypatch.setattr(minimax_video_generator.minimax_client, "request_json", Mock(return_value=submit))
    monkeypatch.setattr(minimax_video_generator.minimax_client, "get_json", Mock(return_value=query_response))
    log_generation = Mock()
    monkeypatch.setattr(minimax_video_generator.cost_tracker, "log_generation", log_generation)

    assert (
        minimax_video_generator.generate_loop_video(
            image,
            output,
            "MiniMax-Hailuo-3",
            "gentle motion",
            duration_seconds=6,
            aspect_ratio="16:9",
            resolution="1080P",
            timeout_sec=30,
            poll_interval_sec=0,
            max_poll_retries=0,
        )
        is False
    )
    assert not output.exists()
    log_generation.assert_not_called()


def test_invalid_downloaded_video_is_not_published_or_costed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = _image(tmp_path / "main.png")
    output = tmp_path / "loop.mp4"
    submit, success, retrieved = _success_responses()
    monkeypatch.setattr(minimax_video_generator.minimax_client, "request_json", Mock(return_value=submit))
    monkeypatch.setattr(minimax_video_generator.minimax_client, "get_json", Mock(side_effect=[success, retrieved]))
    monkeypatch.setattr(minimax_video_generator.minimax_client, "download_bytes", Mock(return_value=b"not-video"))
    log_generation = Mock()
    monkeypatch.setattr(minimax_video_generator.cost_tracker, "log_generation", log_generation)

    assert (
        minimax_video_generator.generate_loop_video(
            image,
            output,
            "MiniMax-Hailuo-3",
            "gentle motion",
            duration_seconds=6,
            aspect_ratio="16:9",
            resolution="1080P",
            timeout_sec=30,
            poll_interval_sec=0,
            max_poll_retries=0,
        )
        is False
    )
    assert not output.exists()
    log_generation.assert_not_called()
