"""fal video generator の課金前検証と queue 契約。"""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from youtube_automation.infrastructure.media import fal_video_generator as generator


def _image(path: Path, size: tuple[int, int] = (1400, 800)) -> Path:
    Image.new("RGB", size, "navy").save(path)
    return path


@pytest.mark.parametrize(
    ("overrides", "size"),
    [
        ({"duration_seconds": 4}, (1400, 800)),
        ({"duration_seconds": True}, (1400, 800)),
        ({"resolution": "1080P"}, (1400, 800)),
        ({"prompt_expansion_mode": "fast"}, (1400, 800)),
        ({"model": "unapproved/model"}, (1400, 800)),
        ({"prompt": ""}, (1400, 800)),
        ({}, (800, 1400)),
    ],
)
def test_invalid_input_fails_before_upload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, object],
    size: tuple[int, int],
) -> None:
    upload = Mock()
    monkeypatch.setattr(generator.fal_client, "upload_file", upload)
    arguments = {"model": generator.DEFAULT_MODEL, "prompt": "gentle motion", **overrides}

    assert not generator.generate_loop_video(
        _image(tmp_path / "main.png", size),
        tmp_path / "loop.mp4",
        **arguments,
        channel_root=tmp_path,
    )
    upload.assert_not_called()


def test_submit_uses_one_resized_url_and_records_metadata_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = _image(tmp_path / "main.png")
    output = tmp_path / "20-video" / "loop.mp4"
    submit = Mock(
        return_value={
            "request_id": "request-1",
            "response_url": "https://queue.fal.run/result",
            "status_url": "https://queue.fal.run/status",
            "cancel_url": "https://queue.fal.run/cancel",
        }
    )
    get_url = Mock(
        side_effect=[
            {"status": "COMPLETED"},
            {
                "video": {"url": "https://v3.fal.media/video.mp4"},
                "expanded_prompt": "expanded",
                "metrics": {"inference_time": 7.5},
            },
        ]
    )
    cost_log = tmp_path / "data" / "generation-costs-video.json"
    monkeypatch.setattr(generator.fal_client, "upload_file", Mock(return_value="https://v3.fal.media/input.png"))
    monkeypatch.setattr(generator.fal_client, "submit", submit)
    monkeypatch.setattr(generator.fal_client, "get_url", get_url)
    monkeypatch.setattr(generator.fal_client, "download", Mock(return_value=b"\0\0\0\x18ftypmp42video"))
    monkeypatch.setattr(generator, "smooth_loop", Mock(return_value=True))
    monkeypatch.setattr(generator.cost_tracker, "_log_path", lambda category: cost_log)
    monkeypatch.setattr(generator.cost_tracker, "print_last_report", Mock())
    monkeypatch.setattr(generator.cost_tracker, "relative_to_channel_dir", lambda path: str(path))

    assert generator.generate_loop_video(
        image,
        output,
        generator.DEFAULT_MODEL,
        "gentle motion",
        channel_root=tmp_path / "channel",
    )
    payload = submit.call_args.args[1]
    assert payload["image_url"] == payload["end_image_url"]
    with Image.open(tmp_path / "tmp" / "fal-video-inputs" / "loop.png") as prepared:
        assert prepared.size == (1344, 768)
    [entry] = json.loads(cost_log.read_text())
    assert entry["category"] == "video"
    assert entry["unit"] == "second"
    assert entry["quantity"] == 5
    assert entry["estimated_cost_usd"] is None
    assert entry["metadata"]["request_id"] == "request-1"
    assert (tmp_path / "10-assets" / "loop.expanded-prompt.txt").read_text() == "expanded\n"


def test_matching_state_resumes_without_submit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    image = _image(tmp_path / "main.png")
    output = tmp_path / "loop.mp4"
    generator.task_store.save(
        output,
        image,
        request_id="request-1",
        response_url="https://queue.fal.run/result",
        status_url="https://queue.fal.run/status",
        cancel_url="https://queue.fal.run/cancel",
        submitted_at="2026-09-04T00:00:00Z",
        model=generator.DEFAULT_MODEL,
        prompt="motion",
        duration_seconds=5,
        resolution="768P",
        prompt_expansion_mode="balanced",
        channel_root=tmp_path,
    )
    submit = Mock()
    monkeypatch.setattr(generator.fal_client, "submit", submit)
    monkeypatch.setattr(generator.fal_client, "upload_file", Mock())
    monkeypatch.setattr(
        generator.fal_client,
        "get_url",
        Mock(
            side_effect=[
                {"status": "COMPLETED"},
                {"video": {"url": "https://v3.fal.media/out.mp4"}},
            ]
        ),
    )
    monkeypatch.setattr(generator.fal_client, "download", Mock(return_value=b"\0\0\0\x18ftypmp42video"))
    monkeypatch.setattr(generator, "smooth_loop", Mock(return_value=True))
    monkeypatch.setattr(generator.cost_tracker, "log_generation", Mock(return_value=None))
    monkeypatch.setattr(generator.cost_tracker, "print_last_report", Mock())
    monkeypatch.setattr(generator.cost_tracker, "relative_to_channel_dir", lambda path: str(path))

    assert generator.generate_loop_video(
        image,
        output,
        generator.DEFAULT_MODEL,
        "motion",
        channel_root=tmp_path,
    )
    submit.assert_not_called()


def _mock_successful_new_job(monkeypatch: pytest.MonkeyPatch) -> Mock:
    submit = Mock(
        return_value={
            "request_id": "request-new",
            "response_url": "https://queue.fal.run/new/result",
            "status_url": "https://queue.fal.run/new/status",
            "cancel_url": "https://queue.fal.run/new/cancel",
        }
    )
    monkeypatch.setattr(generator.fal_client, "upload_file", Mock(return_value="https://v3.fal.media/input.png"))
    monkeypatch.setattr(generator.fal_client, "submit", submit)
    monkeypatch.setattr(generator.fal_client, "download", Mock(return_value=b"\0\0\0\x18ftypmp42video"))
    monkeypatch.setattr(generator, "smooth_loop", Mock(return_value=True))
    monkeypatch.setattr(generator.cost_tracker, "log_generation", Mock(return_value=None))
    monkeypatch.setattr(generator.cost_tracker, "print_last_report", Mock())
    monkeypatch.setattr(generator.cost_tracker, "relative_to_channel_dir", lambda path: str(path))
    return submit


def test_mismatched_resume_state_is_cleared_before_submit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    image = _image(tmp_path / "main.png")
    output = tmp_path / "20-video" / "loop.mp4"
    old_state = {"request_id": "request-old"}
    events: list[str] = []
    clear = Mock(side_effect=lambda *args, **kwargs: events.append("clear"))
    monkeypatch.setattr(generator.task_store, "load", Mock(return_value=old_state))
    monkeypatch.setattr(generator.task_store, "matches", Mock(return_value=False))
    monkeypatch.setattr(generator.task_store, "clear", clear)
    monkeypatch.setattr(generator.task_store, "save", Mock())
    submit = _mock_successful_new_job(monkeypatch)
    response = submit.return_value
    submit.side_effect = lambda *args, **kwargs: (events.append("submit"), response)[1]
    monkeypatch.setattr(
        generator.fal_client,
        "get_url",
        Mock(side_effect=[{"status": "COMPLETED"}, {"video": {"url": "https://v3.fal.media/out.mp4"}}]),
    )

    assert generator.generate_loop_video(image, output, generator.DEFAULT_MODEL, "changed", channel_root=tmp_path)
    clear.assert_any_call(output, channel_root=tmp_path)
    submit.assert_called_once()
    assert events[:2] == ["clear", "submit"]


@pytest.mark.parametrize("status_code", [404, 410])
def test_expired_status_url_clears_and_resubmits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status_code: int
) -> None:
    image = _image(tmp_path / "main.png")
    output = tmp_path / "20-video" / "loop.mp4"
    resumed = {
        "request_id": "request-old",
        "response_url": "https://queue.fal.run/old/result",
        "status_url": "https://queue.fal.run/old/status",
        "cancel_url": "https://queue.fal.run/old/cancel",
    }
    clear = Mock()
    monkeypatch.setattr(generator.task_store, "load", Mock(return_value=resumed))
    monkeypatch.setattr(generator.task_store, "matches", Mock(return_value=True))
    monkeypatch.setattr(generator.task_store, "clear", clear)
    monkeypatch.setattr(generator.task_store, "save", Mock())
    submit = _mock_successful_new_job(monkeypatch)
    monkeypatch.setattr(
        generator.fal_client,
        "get_url",
        Mock(
            side_effect=[
                generator.GeneratorError("wording may change", status_code=status_code),
                {"status": "COMPLETED"},
                {"video": {"url": "https://v3.fal.media/out.mp4"}},
            ]
        ),
    )

    assert generator.generate_loop_video(image, output, generator.DEFAULT_MODEL, "motion", channel_root=tmp_path)
    clear.assert_any_call(output, channel_root=tmp_path)
    submit.assert_called_once()


def test_completed_status_with_error_type_fails_without_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = _image(tmp_path / "main.png")
    output = tmp_path / "20-video" / "loop.mp4"
    _mock_successful_new_job(monkeypatch)
    download = Mock()
    monkeypatch.setattr(generator.fal_client, "download", download)
    monkeypatch.setattr(
        generator.fal_client, "get_url", Mock(return_value={"status": "COMPLETED", "error_type": "bad"})
    )

    assert not generator.generate_loop_video(image, output, generator.DEFAULT_MODEL, "motion", channel_root=tmp_path)
    download.assert_not_called()


def test_error_output_redacts_api_key_and_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = "fal-secret-must-not-leak"
    payload = "private-prompt-must-not-leak"
    monkeypatch.setattr(
        generator.fal_client,
        "upload_file",
        Mock(side_effect=generator.GeneratorError("fal upload HTTP error", status_code=422)),
    )

    assert not generator.generate_loop_video(
        _image(tmp_path / "main.png"),
        tmp_path / "20-video" / "loop.mp4",
        generator.DEFAULT_MODEL,
        payload,
        channel_root=tmp_path,
    )
    output = capsys.readouterr().out
    assert secret not in output
    assert payload not in output
