"""Effective Suno skill configuration shared by generation and verification."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

from youtube_automation.configuration import channel_dir
from youtube_automation.infrastructure.errors import ConfigError
from youtube_automation.utils.video_analyzer import VIDEO_ANALYSIS_DIRNAME

_TOP_GENRE_PHRASES = 8
_VOCAL_KEYWORDS = ("vocals", "vocal", "singing", "rap", "sings", "sung")


@dataclass(frozen=True)
class ResolvedSunoConfig:
    raw: Mapping[str, object]
    genre_line: str
    exclude_styles: str


def resolve_suno_config(suno_cfg: Mapping[str, object]) -> ResolvedSunoConfig:
    fallback_genre, fallback_exclude = collect_video_analysis_suno_presets()
    return ResolvedSunoConfig(
        raw=suno_cfg,
        genre_line=str(suno_cfg.get("genre_line") or fallback_genre),
        exclude_styles=str(suno_cfg.get("exclude_styles") or fallback_exclude),
    )


def infer_suno_mode(genre_line: str) -> str:
    return "vocal" if any(keyword in genre_line.lower() for keyword in _VOCAL_KEYWORDS) else "instrumental"


def collect_video_analysis_suno_presets() -> tuple[str, str]:
    try:
        base = channel_dir() / "data" / VIDEO_ANALYSIS_DIRNAME
    except ConfigError:
        return "", ""
    if not base.exists():
        return "", ""

    genre_counter: Counter[str] = Counter()
    exclude_seen: dict[str, None] = {}

    for slug_dir in sorted(base.iterdir()):
        if not slug_dir.is_dir():
            continue
        for path in sorted(slug_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            preset = data.get("suno_preset")
            if not isinstance(preset, dict):
                continue
            for phrase in _split_csv(preset.get("genre_line", "")):
                genre_counter[phrase] += 1
            for phrase in _split_csv(preset.get("exclude_styles", "")):
                exclude_seen.setdefault(phrase, None)

    top_genre = ", ".join(phrase for phrase, _ in genre_counter.most_common(_TOP_GENRE_PHRASES))
    return top_genre, ", ".join(exclude_seen)


def _split_csv(value: object) -> list[str]:
    return [part.strip() for part in str(value).split(",") if part.strip()]
