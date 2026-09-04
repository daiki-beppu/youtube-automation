"""fal queue を使った MiniMax H3 image-to-video 生成境界。"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from youtube_automation.core.errors import ConfigError, GeneratorError, ValidationError
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
    allowed_models: set[str] | frozenset[str],
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


def _poll(state: Mapping[str, object], *, timeout_sec: float, poll_interval_sec: float) -> dict[str, object]:
    started = time.monotonic()
    while True:
        if time.monotonic() - started > timeout_sec:
            raise GeneratorError("fal polling が timeout しました")
        status_body = fal_client.get_url(_text(state.get("status_url"), "status_url"), timeout=timeout_sec)
        status = _text(status_body.get("status"), "status")
        if status in {"IN_QUEUE", "IN_PROGRESS"}:
            time.sleep(poll_interval_sec)
            continue
        if status != "COMPLETED":
            raise GeneratorError("fal status が契約外です")
        if status_body.get("error_type"):
            raise GeneratorError("fal generation が失敗しました")
        result = fal_client.get_url(_text(state.get("response_url"), "response_url"), timeout=timeout_sec)
        if result.get("error_type"):
            raise GeneratorError("fal generation が失敗しました")
        return result


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
    allowed_models: set[str] | frozenset[str] = DEFAULT_ALLOWED_MODELS,
    canvas: Mapping[str, tuple[int, int]] = DEFAULT_CANVAS,
    upscale_to: tuple[int, int] | None = (1920, 1080),
    compression: dict | None = None,
    channel_root: Path | None = None,
) -> bool:
    """入力を canvas 化し、再開可能な fal queue job として生成する。"""
    try:
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
        collection_root = output_path.parent.parent
        prepared = collection_root / "tmp" / "fal-video-inputs" / f"{output_path.stem}.png"
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
            polled = _poll(submitted, timeout_sec=timeout_sec, poll_interval_sec=poll_interval_sec)
            return submitted, polled

        state = task_store.load(output_path, channel_root=channel_root)
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
                result = _poll(state, timeout_sec=timeout_sec, poll_interval_sec=poll_interval_sec)
            except GeneratorError as error:
                if not _is_expired(error):
                    raise
                task_store.clear(output_path, channel_root=channel_root)
                state, result = submit_and_poll()
        else:
            if state is not None:
                task_store.clear(output_path, channel_root=channel_root)
            state, result = submit_and_poll()
        _persist(fal_client.download(_video_url(result), timeout=timeout_sec), output_path)
    except (ConfigError, GeneratorError, ValidationError) as error:
        print(f"  [ERROR]  {error}")
        return False

    crf, preset = resolve_smooth_codec(compression)
    if not smooth_loop(output_path, crossfade_sec=0.5, trim_tail_sec=1.0, scale_to=upscale_to, crf=crf, preset=preset):
        print("  [Warn]   fal 動画のループ補正に失敗しました（生成済み動画は保持します）")
    expanded = result.get("expanded_prompt")
    if isinstance(expanded, str) and expanded:
        assets = collection_root / "10-assets"
        assets.mkdir(parents=True, exist_ok=True)
        (assets / "loop.expanded-prompt.txt").write_text(expanded + "\n", encoding="utf-8")
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
    task_store.clear(output_path, channel_root=channel_root)
    return True
