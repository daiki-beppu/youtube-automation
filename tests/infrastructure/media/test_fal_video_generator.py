"""fal video generator の課金前検証と queue 契約。"""

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
    log = Mock(return_value={"estimated_cost_usd": None})
    monkeypatch.setattr(generator.fal_client, "upload_file", Mock(return_value="https://v3.fal.media/input.png"))
    monkeypatch.setattr(generator.fal_client, "submit", submit)
    monkeypatch.setattr(generator.fal_client, "get_url", get_url)
    monkeypatch.setattr(generator.fal_client, "download", Mock(return_value=b"\0\0\0\x18ftypmp42video"))
    monkeypatch.setattr(generator, "smooth_loop", Mock(return_value=True))
    monkeypatch.setattr(generator.cost_tracker, "log_generation", log)
    monkeypatch.setattr(generator.cost_tracker, "print_last_report", Mock())
    monkeypatch.setattr(generator.cost_tracker, "relative_to_channel_dir", lambda path: str(path))

    assert generator.generate_loop_video(
        image,
        output,
        generator.DEFAULT_MODEL,
        "gentle motion",
        channel_root=tmp_path,
    )
    payload = submit.call_args.args[1]
    assert payload["image_url"] == payload["end_image_url"]
    with Image.open(tmp_path / "tmp" / "fal-video-inputs" / "loop.png") as prepared:
        assert prepared.size == (1344, 768)
    assert log.call_args.kwargs["unit"] == "second"
    assert log.return_value["estimated_cost_usd"] is None
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
