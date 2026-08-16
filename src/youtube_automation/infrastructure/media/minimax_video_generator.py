"""MiniMax H3 image-to-video の submit・resume・poll・download 境界。"""

from __future__ import annotations

import base64
import hashlib
import mimetypes
import os
import time
from collections.abc import Mapping
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from youtube_automation.core.errors import ConfigError, GeneratorError, ValidationError
from youtube_automation.infrastructure import cost_tracker
from youtube_automation.infrastructure.media import minimax_client
from youtube_automation.infrastructure.media import minimax_video_task_store as task_store
from youtube_automation.infrastructure.media.veo_generator import smooth_loop

DEFAULT_MODEL = "MiniMax-Hailuo-3"
DEFAULT_DURATION_SECONDS = 6
DEFAULT_ASPECT_RATIO = "16:9"
DEFAULT_RESOLUTION = "1080P"
DEFAULT_TIMEOUT_SEC = 600.0
DEFAULT_POLL_INTERVAL_SEC = 5.0
DEFAULT_MAX_POLL_RETRIES = 3

_SUBMIT_PATH = "/v1/video_generation"
_QUERY_PATH = "/v1/query/video_generation"
_FILE_PATH = "/v1/files/retrieve"
_MAX_IMAGE_BYTES = 20 * 1024 * 1024
_MAX_PROMPT_CHARS = 2000
_MIN_SHORT_EDGE = 300
_ASPECT_RATIOS = {"16:9": 16 / 9}
_DURATIONS = {6, 10}
_RESOLUTIONS = {"768P", "1080P"}
_PENDING_STATUSES = {"Preparing", "Queueing", "Processing"}


def _mapping(value: object, label: str) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise GeneratorError(f"MiniMax {label} は object である必要があります")
    return value


def _successful_body(body: object, label: str) -> Mapping[object, object]:
    root = _mapping(body, f"{label} response")
    base_response = _mapping(root.get("base_resp"), f"{label} base_resp")
    status_code = base_response.get("status_code")
    if not isinstance(status_code, int) or isinstance(status_code, bool) or status_code != 0:
        raise GeneratorError(f"MiniMax {label} response は成功状態ではありません")
    return root


def _nonempty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GeneratorError(f"MiniMax {label} は空でない文字列である必要があります")
    return value


def _validate_image(image_path: Path, aspect_ratio: str) -> tuple[str, bytes]:
    if image_path.is_symlink() or not image_path.is_file():
        raise ValidationError(f"MiniMax H3 input image は通常ファイルである必要があります: {image_path}")
    if image_path.stat().st_size >= _MAX_IMAGE_BYTES:
        raise ValidationError("MiniMax H3 input image は 20MB 未満である必要があります")
    mime_type = mimetypes.guess_type(image_path.name)[0]
    if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise ValidationError("MiniMax H3 input image は JPEG / PNG / WebP が必要です")
    try:
        with Image.open(image_path) as image:
            image.verify()
        with Image.open(image_path) as image:
            width, height = image.size
    except (OSError, UnidentifiedImageError):
        raise ValidationError("MiniMax H3 input image を画像として検証できません") from None
    if min(width, height) <= _MIN_SHORT_EDGE:
        raise ValidationError("MiniMax H3 input image の短辺は 300px より大きい必要があります")
    expected_ratio = _ASPECT_RATIOS[aspect_ratio]
    if abs(width / height - expected_ratio) > 0.03:
        raise ValidationError(f"MiniMax H3 input image は {aspect_ratio} である必要があります")
    return mime_type, image_path.read_bytes()


def _validate_inputs(
    image_path: Path,
    model: str,
    prompt: str,
    duration_seconds: int,
    aspect_ratio: str,
    resolution: str,
    timeout_sec: float,
    poll_interval_sec: float,
    max_poll_retries: int,
) -> tuple[str, bytes]:
    if not model.strip():
        raise ValidationError("MiniMax H3 model は空にできません")
    if not prompt.strip() or len(prompt) > _MAX_PROMPT_CHARS:
        raise ValidationError(f"MiniMax H3 prompt は 1〜{_MAX_PROMPT_CHARS} 文字である必要があります")
    if duration_seconds not in _DURATIONS:
        raise ValidationError("MiniMax H3 duration_seconds は 6 または 10 が必要です")
    if aspect_ratio not in _ASPECT_RATIOS:
        raise ValidationError("MiniMax H3 aspect_ratio は 16:9 が必要です")
    if resolution not in _RESOLUTIONS:
        raise ValidationError("MiniMax H3 resolution は 768P または 1080P が必要です")
    if duration_seconds == 10 and resolution == "1080P":
        raise ValidationError("MiniMax H3 は 10秒 / 1080P の組み合わせをサポートしません")
    if timeout_sec <= 0 or poll_interval_sec < 0 or max_poll_retries < 0:
        raise ValidationError("MiniMax H3 timeout/retry 設定が不正です")
    return _validate_image(image_path, aspect_ratio)


def _submit(
    image_path: Path,
    output_path: Path,
    *,
    model: str,
    prompt: str,
    image_data_url: str,
    duration_seconds: int,
    aspect_ratio: str,
    resolution: str,
    timeout_sec: float,
) -> str:
    body = minimax_client.request_json(
        _SUBMIT_PATH,
        {
            "model": model,
            "prompt": prompt,
            "first_frame_image": image_data_url,
            "duration": duration_seconds,
            "resolution": resolution,
            "prompt_optimizer": False,
        },
        timeout=timeout_sec,
    )
    task_id = _nonempty_string(_successful_body(body, "submit").get("task_id"), "submit task_id")
    task_store.save(
        output_path,
        image_path,
        task_id=task_id,
        model=model,
        prompt=prompt,
        duration_seconds=duration_seconds,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
    )
    return task_id


def _get_json_with_retries(
    path: str,
    params: Mapping[str, object],
    *,
    timeout_sec: float,
    max_retries: int,
) -> dict[str, object]:
    for attempt in range(max_retries + 1):
        try:
            return minimax_client.get_json(path, params, timeout=timeout_sec)
        except GeneratorError:
            if attempt == max_retries:
                raise
            time.sleep(min(2**attempt, 8))
    raise AssertionError("retry loop must return or raise")


def _poll_task(
    task_id: str,
    output_path: Path,
    *,
    aspect_ratio: str,
    timeout_sec: float,
    poll_interval_sec: float,
    max_poll_retries: int,
) -> str:
    started = time.monotonic()
    while True:
        if time.monotonic() - started > timeout_sec:
            raise GeneratorError("MiniMax H3 polling が timeout しました")
        body = _get_json_with_retries(
            _QUERY_PATH,
            {"task_id": task_id},
            timeout_sec=timeout_sec,
            max_retries=max_poll_retries,
        )
        root = _successful_body(body, "query")
        status = _nonempty_string(root.get("status"), "query status")
        if status in _PENDING_STATUSES:
            time.sleep(poll_interval_sec)
            continue
        if status == "Fail":
            task_store.clear(output_path)
            raise GeneratorError("MiniMax H3 generation が失敗しました")
        if status != "Success":
            raise GeneratorError("MiniMax H3 query status が契約外です")
        width = root.get("video_width")
        height = root.get("video_height")
        if (
            not isinstance(width, int)
            or isinstance(width, bool)
            or not isinstance(height, int)
            or isinstance(height, bool)
            or width <= 0
            or height <= 0
            or abs(width / height - _ASPECT_RATIOS[aspect_ratio]) > 0.03
        ):
            raise GeneratorError(f"MiniMax H3 output video は {aspect_ratio} である必要があります")
        return _nonempty_string(root.get("file_id"), "query file_id")


def _download_video(file_id: str, *, timeout_sec: float, max_poll_retries: int) -> bytes:
    body = _get_json_with_retries(
        _FILE_PATH,
        {"file_id": file_id},
        timeout_sec=timeout_sec,
        max_retries=max_poll_retries,
    )
    file_info = _mapping(_successful_body(body, "file retrieve").get("file"), "file retrieve file")
    returned_file_id = _nonempty_string(file_info.get("file_id"), "file retrieve file_id")
    if returned_file_id != file_id:
        raise GeneratorError("MiniMax file retrieve の file_id が一致しません")
    download_url = _nonempty_string(file_info.get("download_url"), "file retrieve download_url")
    video = minimax_client.download_bytes(download_url, timeout=timeout_sec)
    if len(video) < 12 or video[4:8] != b"ftyp":
        raise GeneratorError("MiniMax H3 download は MP4 ではありません")
    return video


def _persist_video(video: bytes, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(".mp4.tmp")
    try:
        temporary.write_bytes(video)
        os.replace(temporary, output_path)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        recovery = output_path.parent.parent / "tmp" / "minimax-video-recovered"
        recovery.mkdir(parents=True, exist_ok=True)
        recovered = recovery / f"{hashlib.sha256(video).hexdigest()}.mp4"
        recovered.write_bytes(video)
        raise GeneratorError(f"MiniMax H3 video を保存できません。回収先: {recovered}") from error


def generate_loop_video(
    image_path: Path,
    output_path: Path,
    model: str,
    prompt: str,
    *,
    duration_seconds: int,
    aspect_ratio: str,
    resolution: str,
    timeout_sec: float,
    poll_interval_sec: float,
    max_poll_retries: int,
    compression: dict | None = None,
) -> bool:
    """H3 task を再開可能に生成し、検証済み MP4 を ``output_path`` へ公開する。"""
    try:
        mime_type, image_bytes = _validate_inputs(
            image_path,
            model,
            prompt,
            duration_seconds,
            aspect_ratio,
            resolution,
            timeout_sec,
            poll_interval_sec,
            max_poll_retries,
        )
        state = task_store.load(output_path)
        if state is not None and task_store.matches(
            state,
            image_path,
            model=model,
            prompt=prompt,
            duration_seconds=duration_seconds,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
        ):
            task_id = _nonempty_string(state["task_id"], "recovery task_id")
            print(f"  [Resume] MiniMax H3 task を再開します: {task_id}")
        else:
            if state is not None:
                task_store.clear(output_path)
            encoded_image = base64.b64encode(image_bytes).decode("ascii")
            task_id = _submit(
                image_path,
                output_path,
                model=model,
                prompt=prompt,
                image_data_url=f"data:{mime_type};base64,{encoded_image}",
                duration_seconds=duration_seconds,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                timeout_sec=timeout_sec,
            )
        file_id = _poll_task(
            task_id,
            output_path,
            aspect_ratio=aspect_ratio,
            timeout_sec=timeout_sec,
            poll_interval_sec=poll_interval_sec,
            max_poll_retries=max_poll_retries,
        )
        video = _download_video(file_id, timeout_sec=timeout_sec, max_poll_retries=max_poll_retries)
        _persist_video(video, output_path)
    except (ConfigError, GeneratorError, ValidationError) as error:
        print(f"  [ERROR]  {error}")
        return False

    crf = int(compression.get("crf", 22)) if compression and compression.get("enabled", True) else 18
    preset = str(compression.get("preset", "slow")) if compression and compression.get("enabled", True) else "slow"
    if not smooth_loop(output_path, crossfade_sec=0.5, trim_tail_sec=1.0, crf=crf, preset=preset):
        print("  [Warn]   H3 動画のループ補正に失敗しました（生成済み動画は保持します）")
    entry = cost_tracker.log_generation(
        "video",
        model=model,
        quantity=duration_seconds,
        unit="second",
        metadata={
            "duration_sec": duration_seconds,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "output_file": cost_tracker.relative_to_channel_dir(output_path),
        },
    )
    cost_tracker.print_last_report(entry)
    task_store.clear(output_path)
    return True
