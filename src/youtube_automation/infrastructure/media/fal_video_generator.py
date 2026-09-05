"""fal queue を使った MiniMax H3 image-to-video 生成境界。"""

from __future__ import annotations

import contextlib
import os
import shutil
import time
from collections.abc import Collection, Mapping
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageOps, UnidentifiedImageError

from youtube_automation.core.errors import ConfigError, GenerationFailedError, GeneratorError, ValidationError
from youtube_automation.infrastructure import cost_tracker
from youtube_automation.infrastructure.media import fal_client
from youtube_automation.infrastructure.media import fal_video_task_store as task_store
from youtube_automation.infrastructure.media.veo_generator import resolve_smooth_codec, smooth_loop

DEFAULT_MODEL = "minimax/h3-max-turbo/image-to-video"
DEFAULT_DURATION_SECONDS = 5
DEFAULT_RESOLUTION = "768P"
DEFAULT_PROMPT_EXPANSION_MODE = "balanced"
DEFAULT_TIMEOUT_SEC = 600.0
DEFAULT_POLL_INTERVAL_SEC = 2.0
DEFAULT_MAX_POLL_RETRIES = 3
DEFAULT_ALLOWED_MODELS = frozenset({DEFAULT_MODEL, "minimax/h3-max/image-to-video"})
DEFAULT_CANVAS = {"16:9": (1344, 768), "9:16": (768, 1344)}
_MAX_PROMPT_CHARS = 2000
_RESOLUTIONS = {"480P", "768P"}
_MODES = {"balanced", "quality"}


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GeneratorError(f"fal {label} が response にありません")
    return value


def _validate_and_resize(image_path: Path, destination: Path, canvas: tuple[int, int]) -> None:
    if image_path.is_symlink() or not image_path.is_file():
        raise ValidationError("fal input image は通常ファイルである必要があります")
    width, height = canvas
    if width <= 0 or height <= 0:
        raise ValidationError("fal canvas は正の幅と高さが必要です")
    try:
        with Image.open(image_path) as source:
            source.verify()
        with Image.open(image_path) as source:
            source_width, source_height = source.size
            if min(source_width, source_height) < min(width, height):
                raise ValidationError("fal input image の短辺は canvas 以上である必要があります")
            if abs(source_width / source_height - width / height) > 0.03:
                raise ValidationError("fal input image の比率が canvas と一致しません")
            destination.parent.mkdir(parents=True, exist_ok=True)
            fitted = ImageOps.fit(source.convert("RGB"), canvas, method=Image.Resampling.LANCZOS)
            fitted.save(destination, format="PNG")
    except (OSError, UnidentifiedImageError):
        raise ValidationError("fal input image を画像として検証できません") from None


def _validate(
    *,
    model: str,
    prompt: str,
    duration_seconds: int,
    resolution: str,
    prompt_expansion_mode: str,
    aspect_ratio: str,
    allowed_models: Collection[str],
    canvas: Mapping[str, tuple[int, int]],
    timeout_sec: float,
    poll_interval_sec: float,
) -> tuple[int, int]:
    if not isinstance(duration_seconds, int) or isinstance(duration_seconds, bool) or not 5 <= duration_seconds <= 15:
        raise ValidationError("fal duration_seconds は 5〜15 の整数である必要があります")
    if resolution not in _RESOLUTIONS:
        raise ValidationError("fal resolution は 480P または 768P が必要です")
    if prompt_expansion_mode not in _MODES:
        raise ValidationError("fal prompt_expansion_mode は balanced または quality が必要です")
    if model not in allowed_models:
        raise ValidationError("fal model は allowed_models に含まれる必要があります")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > _MAX_PROMPT_CHARS:
        raise ValidationError(f"fal prompt は 1〜{_MAX_PROMPT_CHARS} 文字である必要があります")
    if aspect_ratio not in canvas:
        raise ValidationError("fal aspect_ratio に対応する canvas がありません")
    if timeout_sec <= 0 or poll_interval_sec < 0:
        raise ValidationError("fal timeout/poll 設定が不正です")
    return canvas[aspect_ratio]


def _submit(
    image_path: Path,
    output_path: Path,
    *,
    source_image_path: Path | None = None,
    model: str,
    prompt: str,
    duration_seconds: int,
    resolution: str,
    prompt_expansion_mode: str,
    timeout_sec: float,
    channel_root: Path | None,
) -> dict[str, object]:
    file_url = fal_client.upload_file(image_path, timeout=timeout_sec)
    response = fal_client.submit(
        model,
        {
            "prompt": prompt,
            "image_url": file_url,
            "end_image_url": file_url,
            "duration": duration_seconds,
            "resolution": resolution,
            "prompt_expansion_mode": prompt_expansion_mode,
        },
        timeout=timeout_sec,
    )
    state = {
        key: _text(response.get(key), f"submit {key}")
        for key in ("request_id", "response_url", "status_url", "cancel_url")
    }
    task_store.save(
        output_path,
        source_image_path or image_path,
        submitted_at=datetime.now(timezone.utc).isoformat(),
        model=model,
        prompt=prompt,
        duration_seconds=duration_seconds,
        resolution=resolution,
        prompt_expansion_mode=prompt_expansion_mode,
        channel_root=channel_root,
        **state,
    )
    return state


def _is_expired(error: GeneratorError) -> bool:
    return error.status_code in {404, 410}


def _poll_get(url: str, *, deadline: float, poll_interval_sec: float, max_poll_retries: int) -> dict[str, object]:
    for attempt in range(max_poll_retries + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise GeneratorError("fal polling が timeout しました")
        try:
            return fal_client.get_url(url, timeout=remaining)
        except GeneratorError as error:
            if error.status_code not in {None, 408, 429, 500, 502, 503, 504} or attempt == max_poll_retries:
                raise
            time.sleep(min(poll_interval_sec, max(0, deadline - time.monotonic())))
    raise GeneratorError("fal polling の再試行上限に達しました")


def _poll(
    state: Mapping[str, object], *, timeout_sec: float, poll_interval_sec: float, max_poll_retries: int
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_sec

    def get(key: str) -> dict[str, object]:
        return _poll_get(
            _text(state.get(key), key),
            deadline=deadline,
            poll_interval_sec=poll_interval_sec,
            max_poll_retries=max_poll_retries,
        )

    while True:
        status_body = get("status_url")
        status = _text(status_body.get("status"), "status")
        if status in {"IN_QUEUE", "IN_PROGRESS"}:
            time.sleep(min(poll_interval_sec, max(0, deadline - time.monotonic())))
            continue
        if status != "COMPLETED":
            raise GeneratorError("fal status が契約外です")
        if status_body.get("error_type"):
            raise GenerationFailedError("fal generation が失敗しました")
        try:
            result = get("response_url")
        except GeneratorError as error:
            if error.status_code == 422:
                raise GenerationFailedError("fal generation が失敗しました") from None
            raise
        if result.get("error_type"):
            raise GenerationFailedError("fal generation が失敗しました")
        return {**result, "metrics": status_body.get("metrics")}


def _video_url(result: Mapping[str, object]) -> str:
    video = result.get("video")
    if isinstance(video, Mapping):
        return _text(video.get("url"), "result video URL")
    return _text(result.get("video_url"), "result video URL")


def _persist(video: bytes, output_path: Path) -> None:
    if len(video) < 12 or video[4:8] != b"ftyp":
        raise GeneratorError("fal download は MP4 ではありません")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    try:
        temporary.write_bytes(video)
        os.replace(temporary, output_path)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise GeneratorError("fal video を保存できません") from error


def _finalize_video(
    raw_video: Path,
    output_path: Path,
    result: Mapping[str, object],
    *,
    upscale_to: tuple[int, int] | None,
    compression: dict | None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=f".{output_path.stem}.fal-", dir=output_path.parent) as staging_dir:
        staged = Path(staging_dir) / output_path.name
        shutil.copyfile(raw_video, staged)
        crf, preset = resolve_smooth_codec(compression)
        if not smooth_loop(staged, crossfade_sec=0.5, trim_tail_sec=1.0, scale_to=upscale_to, crf=crf, preset=preset):
            raise GeneratorError("fal 動画のループ補正に失敗しました（生動画を保持し、次回は後処理から再開します）")
        expanded = result.get("expanded_prompt")
        if isinstance(expanded, str) and expanded:
            output_path.with_suffix(".expanded-prompt.txt").write_text(expanded + "\n", encoding="utf-8")
        os.replace(staged, output_path)


def generate_loop_video(
    image_path: Path,
    output_path: Path,
    model: str,
    prompt: str,
    *,
    duration_seconds: int = DEFAULT_DURATION_SECONDS,
    aspect_ratio: str = "16:9",
    resolution: str = DEFAULT_RESOLUTION,
    prompt_expansion_mode: str = DEFAULT_PROMPT_EXPANSION_MODE,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    poll_interval_sec: float = DEFAULT_POLL_INTERVAL_SEC,
    max_poll_retries: int = DEFAULT_MAX_POLL_RETRIES,
    allowed_models: Collection[str] = DEFAULT_ALLOWED_MODELS,
    canvas: Mapping[str, tuple[int, int]] = DEFAULT_CANVAS,
    upscale_to: tuple[int, int] | None = (1920, 1080),
    compression: dict | None = None,
    channel_root: Path | None = None,
) -> bool:
    """入力を canvas 化し、再開可能な fal queue job として生成する。"""
    try:
        if not isinstance(max_poll_retries, int) or isinstance(max_poll_retries, bool) or max_poll_retries < 0:
            raise ValidationError("fal max_poll_retries は 0 以上の整数である必要があります")
        size = _validate(
            model=model,
            prompt=prompt,
            duration_seconds=duration_seconds,
            resolution=resolution,
            prompt_expansion_mode=prompt_expansion_mode,
            aspect_ratio=aspect_ratio,
            allowed_models=allowed_models,
            canvas=canvas,
            timeout_sec=timeout_sec,
            poll_interval_sec=poll_interval_sec,
        )
        prepared = task_store.input_image_path(output_path, channel_root=channel_root)
        _validate_and_resize(image_path, prepared, size)

        def submit_and_poll() -> tuple[dict[str, object], dict[str, object]]:
            submitted = _submit(
                prepared,
                output_path,
                source_image_path=image_path,
                model=model,
                prompt=prompt,
                duration_seconds=duration_seconds,
                resolution=resolution,
                prompt_expansion_mode=prompt_expansion_mode,
                timeout_sec=timeout_sec,
                channel_root=channel_root,
            )
            polled = _poll(
                submitted,
                timeout_sec=timeout_sec,
                poll_interval_sec=poll_interval_sec,
                max_poll_retries=max_poll_retries,
            )
            return submitted, polled

        raw_video = task_store.raw_video_path(output_path, channel_root=channel_root)
        state = task_store.load(output_path, channel_root=channel_root)
        cached = False
        if state is not None and task_store.matches(
            state,
            image_path,
            model=model,
            prompt=prompt,
            duration_seconds=duration_seconds,
            resolution=resolution,
            prompt_expansion_mode=prompt_expansion_mode,
        ):
            try:
                saved_result = state.get("result")
                cached = isinstance(saved_result, dict) and raw_video.is_file() and not raw_video.is_symlink()
                result = (
                    saved_result
                    if cached
                    else _poll(
                        state,
                        timeout_sec=timeout_sec,
                        poll_interval_sec=poll_interval_sec,
                        max_poll_retries=max_poll_retries,
                    )
                )
            except GeneratorError as error:
                if not _is_expired(error):
                    raise
                task_store.clear(output_path, channel_root=channel_root)
                state, result = submit_and_poll()
        else:
            if state is not None:
                task_store.clear(output_path, channel_root=channel_root)
            state, result = submit_and_poll()
        if not cached:
            _persist(fal_client.download(_video_url(result), timeout=timeout_sec), raw_video)
            task_store.save_result(output_path, result, channel_root=channel_root)
        _finalize_video(raw_video, output_path, result, upscale_to=upscale_to, compression=compression)
    except GenerationFailedError as error:
        task_store.clear(output_path, channel_root=channel_root)
        print(f"  [ERROR]  {error}")
        return False
    except OSError:
        print("  [ERROR]  fal 動画の保存・後処理に失敗しました（再開情報は保持します）")
        return False
    except (ConfigError, GeneratorError, ValidationError) as error:
        print(f"  [ERROR]  {error}")
        return False

    metrics = result.get("metrics")
    inference = metrics.get("inference_time") if isinstance(metrics, Mapping) else None
    entry = cost_tracker.log_generation(
        "video",
        model=model,
        quantity=duration_seconds,
        unit="second",
        metadata={
            "request_id": state["request_id"],
            "endpoint": model,
            "prompt_expansion_mode": prompt_expansion_mode,
            "inference_time_sec": inference,
            "resolution": resolution,
            "aspect_ratio": aspect_ratio,
            "output_file": cost_tracker.relative_to_channel_dir(output_path),
        },
    )
    cost_tracker.print_last_report(entry)
    with contextlib.suppress(OSError):
        prepared.unlink(missing_ok=True)
    task_store.clear(output_path, channel_root=channel_root)
    return True
