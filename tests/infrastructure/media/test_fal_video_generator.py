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
    output = tmp_path / "10-assets" / "loop.mp4"
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
            {"status": "COMPLETED", "metrics": {"inference_time": 7.5}},
            {
                "video": {"url": "https://v3.fal.media/video.mp4"},
                "expanded_prompt": "expanded",
            },
        ]
    )
    cost_log = tmp_path / "data" / "generation-costs-video.json"
    uploaded: list[tuple[Path, tuple[int, int]]] = []

    def _upload(path: Path, **_: object) -> str:
        with Image.open(path) as prepared:
            uploaded.append((path, prepared.size))
        return "https://v3.fal.media/input.png"

    monkeypatch.setattr(generator.fal_client, "upload_file", _upload)
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
    [(prepared_path, prepared_size)] = uploaded
    assert prepared_path.parent == tmp_path / "channel" / "tmp" / "fal-video-inputs"
    assert prepared_size == (1344, 768)
    assert not prepared_path.exists()
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
        input_canvas="16:9:1344x768",
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
    output = tmp_path / "10-assets" / "loop.mp4"
    old_state = {"request_id": "request-old"}
    events: list[str] = []
    clear = Mock(side_effect=lambda *args, **kwargs: events.append("clear"))
    monkeypatch.setattr(generator.task_store, "load", Mock(return_value=old_state))
    monkeypatch.setattr(generator.task_store, "matches", Mock(return_value=False))
    monkeypatch.setattr(generator.task_store, "clear", clear)
    monkeypatch.setattr(generator.task_store, "save", Mock())
    monkeypatch.setattr(generator.task_store, "save_result", Mock())
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
    output = tmp_path / "10-assets" / "loop.mp4"
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
    monkeypatch.setattr(generator.task_store, "save_result", Mock())
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
    output = tmp_path / "10-assets" / "loop.mp4"
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


def test_postprocessing_failure_keeps_previous_output_and_resumes_offline(tmp_path, monkeypatch):
    image = _image(tmp_path / "main.png")
    output = tmp_path / "10-assets" / "loop.mp4"
    output.parent.mkdir()
    output.write_bytes(b"previous-published-video")
    submit = _mock_successful_new_job(monkeypatch)
    monkeypatch.setattr(
        generator.fal_client,
        "get_url",
        Mock(
            side_effect=[
                {"status": "COMPLETED", "metrics": {"inference_time": 7.5}},
                {"video": {"url": "https://v3.fal.media/out.mp4"}, "expanded_prompt": "expanded"},
            ]
        ),
    )
    monkeypatch.setattr(generator, "smooth_loop", Mock(return_value=False))
    assert not generator.generate_loop_video(image, output, generator.DEFAULT_MODEL, "motion", channel_root=tmp_path)
    assert output.read_bytes() == b"previous-published-video"
    generator.cost_tracker.log_generation.assert_not_called()
    assert generator.task_store.load(output, channel_root=tmp_path) is not None
    for name in ("get_url", "download", "upload_file"):
        monkeypatch.setattr(generator.fal_client, name, Mock(side_effect=AssertionError("must resume offline")))
    monkeypatch.setattr(generator, "smooth_loop", Mock(return_value=True))
    assert generator.generate_loop_video(image, output, generator.DEFAULT_MODEL, "motion", channel_root=tmp_path)
    assert output.read_bytes()[4:8] == b"ftyp"
    submit.assert_called_once()
    generator.cost_tracker.log_generation.assert_called_once()
    assert generator.cost_tracker.log_generation.call_args.kwargs["metadata"]["inference_time_sec"] == 7.5
    assert generator.task_store.load(output, channel_root=tmp_path) is None


def test_terminal_failure_allows_a_new_request_on_next_invocation(tmp_path, monkeypatch):
    image = _image(tmp_path / "main.png")
    output = tmp_path / "10-assets" / "loop.mp4"
    submit = _mock_successful_new_job(monkeypatch)
    monkeypatch.setattr(
        generator.fal_client,
        "get_url",
        Mock(
            side_effect=[
                {"status": "COMPLETED", "error_type": "provider_failure"},
                {"status": "COMPLETED"},
                {"video": {"url": "https://v3.fal.media/out.mp4"}},
            ]
        ),
    )
    assert not generator.generate_loop_video(image, output, generator.DEFAULT_MODEL, "motion", channel_root=tmp_path)
    assert generator.task_store.load(output, channel_root=tmp_path) is None
    assert generator.generate_loop_video(image, output, generator.DEFAULT_MODEL, "motion", channel_root=tmp_path)
    assert submit.call_count == 2


def test_inference_metrics_come_from_completed_status(tmp_path, monkeypatch):
    image = _image(tmp_path / "main.png")
    _mock_successful_new_job(monkeypatch)
    monkeypatch.setattr(
        generator.fal_client,
        "get_url",
        Mock(
            side_effect=[
                {"status": "COMPLETED", "metrics": {"inference_time": 7.5}},
                {"video": {"url": "https://v3.fal.media/out.mp4"}, "timings": {"inference": 3.0}},
            ]
        ),
    )
    assert generator.generate_loop_video(
        image, tmp_path / "10-assets" / "loop.mp4", generator.DEFAULT_MODEL, "motion", channel_root=tmp_path
    )
    assert generator.cost_tracker.log_generation.call_args.kwargs["metadata"]["inference_time_sec"] == 7.5


def test_expanded_prompts_are_separate_for_each_output(tmp_path, monkeypatch):
    image = _image(tmp_path / "main.png")
    _mock_successful_new_job(monkeypatch)
    for name in ("loop", "short-loop"):
        monkeypatch.setattr(
            generator.fal_client,
            "get_url",
            Mock(
                side_effect=[
                    {"status": "COMPLETED"},
                    {"video": {"url": "https://v3.fal.media/out.mp4"}, "expanded_prompt": name},
                ]
            ),
        )
        assert generator.generate_loop_video(
            image, tmp_path / "10-assets" / f"{name}.mp4", generator.DEFAULT_MODEL, "motion", channel_root=tmp_path
        )
    for name in ("loop", "short-loop"):
        assert (tmp_path / "10-assets" / f"{name}.expanded-prompt.txt").read_text() == name + "\n"


@pytest.mark.parametrize("failures,retries,expected", [(1, 3, True), (3, 2, False)])
def test_poll_retries_are_bounded_without_resubmission(tmp_path, monkeypatch, failures, retries, expected):
    image = _image(tmp_path / "main.png")
    submit = _mock_successful_new_job(monkeypatch)
    get = Mock(
        side_effect=[generator.GeneratorError("temporary", status_code=503)] * failures
        + [
            {"status": "COMPLETED"},
            {"video": {"url": "https://v3.fal.media/out.mp4"}},
        ]
    )
    monkeypatch.setattr(generator.fal_client, "get_url", get)
    assert (
        generator.generate_loop_video(
            image,
            tmp_path / "10-assets" / "loop.mp4",
            generator.DEFAULT_MODEL,
            "motion",
            channel_root=tmp_path,
            max_poll_retries=retries,
            poll_interval_sec=0,
        )
        is expected
    )
    submit.assert_called_once()
    assert get.call_count == (failures + 2 if expected else retries + 1)


def test_real_postprocessing_publishes_only_silent_scaled_video(tmp_path, monkeypatch):
    import subprocess

    from youtube_automation.infrastructure.media import veo_generator

    raw = tmp_path / "raw.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=96x54:r=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=32000",
            "-t",
            "2",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(raw),
        ],
        check=True,
    )
    image = _image(tmp_path / "main.png")
    output = tmp_path / "10-assets" / "loop.mp4"
    _mock_successful_new_job(monkeypatch)
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
    monkeypatch.setattr(generator.fal_client, "download", Mock(return_value=raw.read_bytes()))
    monkeypatch.setattr(generator, "smooth_loop", veo_generator.smooth_loop)
    assert generator.generate_loop_video(
        image, output, generator.DEFAULT_MODEL, "motion", upscale_to=(192, 108), channel_root=tmp_path
    )
    streams = json.loads(
        subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(output)])
    )["streams"]
    assert len(streams) == 1
    assert (streams[0]["codec_type"], streams[0]["width"], streams[0]["height"]) == ("video", 192, 108)
    assert sorted(p.name for p in output.parent.iterdir()) == ["loop.mp4"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"canvas": {"16:9": (1008, 576)}},
        {"aspect_ratio": "9:16", "canvas": {"9:16": (1344, 768)}},
    ],
)
def test_changed_input_canvas_submits_new_job_after_postprocessing_failure(tmp_path, monkeypatch, overrides):
    image = _image(tmp_path / "main.png")
    output = tmp_path / "loop.mp4"
    submit = _mock_successful_new_job(monkeypatch)
    monkeypatch.setattr(
        generator.fal_client,
        "get_url",
        Mock(
            side_effect=[
                {"status": "COMPLETED"},
                {"video": {"url": "https://v3.fal.media/out.mp4"}},
            ]
            * 2
        ),
    )
    monkeypatch.setattr(generator, "smooth_loop", Mock(side_effect=[False, True]))
    assert not generator.generate_loop_video(image, output, generator.DEFAULT_MODEL, "motion", channel_root=tmp_path)
    assert generator.generate_loop_video(
        image, output, generator.DEFAULT_MODEL, "motion", channel_root=tmp_path, **overrides
    )
    assert submit.call_count == 2
    assert generator.fal_client.upload_file.call_count == 2
    assert generator.fal_client.download.call_count == 2


def test_raw_dimensions_are_reported_before_upscale(tmp_path, monkeypatch, capsys):
    from youtube_automation.infrastructure.media import probe

    image = _image(tmp_path / "short.png", (800, 1400))
    _mock_successful_new_job(monkeypatch)
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

    def smooth(*args, **kwargs):
        stdout = capsys.readouterr().out
        assert "fal 生出力: 720x1280" in stdout
        assert "canvas 想定: 768x1344" in stdout
        assert kwargs["scale_to"] == (1080, 1920)
        return True

    monkeypatch.setattr(generator, "smooth_loop", smooth)
    monkeypatch.setattr(probe, "probe_video", Mock(return_value=probe.VideoProbe(8.0, 720, 1280, "h264")))
    assert generator.generate_loop_video(
        image,
        tmp_path / "10-assets" / "short-loop.mp4",
        generator.DEFAULT_MODEL,
        "motion",
        aspect_ratio="9:16",
        upscale_to=(1080, 1920),
        channel_root=tmp_path,
    )
