"""Thumbnail candidate selection policy."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from youtube_automation.domains.thumbnail.features import (
    extract_features_from_path,
    feature_distance,
)
from youtube_automation.utils.exceptions import ConfigError, ValidationError

_TARGET_ASPECT = 16 / 9
_DEFAULT_MIN_WIDTH = 1280
_DEFAULT_MIN_HEIGHT = 720
_DEFAULT_ASPECT_TOLERANCE = 0.01
_MODE_SELECTION_ONLY = "selection_only"
_MODE_FULL = "full"
_ALLOWED_MODES = (_MODE_SELECTION_ONLY, _MODE_FULL)


@dataclass(frozen=True)
class AutoSelectionSettings:
    enabled: bool
    mode: str
    min_width: int
    min_height: int
    aspect_tolerance: float


@dataclass(frozen=True)
class CandidateScore:
    path: Path
    width: int
    height: int
    distance: float
    eligible: bool
    reasons: list[str]


def _image_generation_section(cfg: dict[str, object]) -> dict[str, object]:
    section = cfg.get("image_generation") or {}
    if not isinstance(section, dict):
        raise ConfigError(f"thumbnail.image_generation は mapping である必要があります: {section!r}")
    return section


def resolve_auto_selection_settings(cfg: dict[str, object]) -> AutoSelectionSettings:
    raw = _image_generation_section(cfg).get("auto_selection") or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"thumbnail.image_generation.auto_selection は mapping である必要があります: {raw!r}")

    def positive_int(key: str, default: int) -> int:
        value = raw.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ConfigError(f"auto_selection.{key} は正の整数である必要があります: {value!r}")
        return value

    tolerance = raw.get("aspect_tolerance", _DEFAULT_ASPECT_TOLERANCE)
    if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or tolerance < 0:
        raise ConfigError(f"auto_selection.aspect_tolerance は 0 以上の数値である必要があります: {tolerance!r}")
    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigError(f"auto_selection.enabled は boolean である必要があります: {enabled!r}")
    mode = raw.get("mode", _MODE_SELECTION_ONLY)
    if mode is None:
        mode = _MODE_SELECTION_ONLY
    if not isinstance(mode, str) or mode not in _ALLOWED_MODES:
        raise ConfigError(f"auto_selection.mode は {_ALLOWED_MODES!r} である必要があります: {mode!r}")
    return AutoSelectionSettings(
        enabled=enabled,
        mode=mode,
        min_width=positive_int("min_width", _DEFAULT_MIN_WIDTH),
        min_height=positive_int("min_height", _DEFAULT_MIN_HEIGHT),
        aspect_tolerance=float(tolerance),
    )


def _eligibility_reasons(width: int, height: int, settings: AutoSelectionSettings) -> list[str]:
    reasons: list[str] = []
    if width < settings.min_width or height < settings.min_height:
        reasons.append(f"解像度不足: {width}x{height}")
    aspect = width / height if height else 0.0
    if abs(aspect - _TARGET_ASPECT) > settings.aspect_tolerance:
        reasons.append(f"16:9 逸脱: aspect={aspect:.4f}")
    return reasons


def score_candidates(
    candidates: list[Path],
    centroid: dict[str, float],
    settings: AutoSelectionSettings,
) -> list[CandidateScore]:
    """Score candidates using the configured feature vector."""
    scores: list[CandidateScore] = []
    for path in candidates:
        try:
            with Image.open(path) as image:
                width, height = image.size
            distance = feature_distance(extract_features_from_path(path), centroid)
        except (OSError, UnidentifiedImageError) as exc:
            raise ValidationError(f"thumbnail 候補画像を読み込めません: {path}: {exc}") from exc
        reasons = _eligibility_reasons(width, height, settings)
        scores.append(
            CandidateScore(
                path=path,
                width=width,
                height=height,
                distance=distance,
                eligible=not reasons,
                reasons=reasons,
            )
        )
    return sorted(scores, key=lambda score: (score.distance, score.path.name))


def select_best(scores: list[CandidateScore], *, mode: str) -> CandidateScore:
    """Select the closest eligible candidate or report every eligibility failure."""
    for score in scores:
        if score.eligible:
            return score
    detail = " / ".join(f"{score.path.name}: {'; '.join(score.reasons)}" for score in scores)
    message = f"16:9・最小解像度を満たす適格候補がありません: {detail}"
    if mode == _MODE_FULL:
        message += (
            "\nmode: full のため自動処理を停止しました。selection_only に切り替えて手動フローを実行してください。"
        )
    raise ValidationError(message)
