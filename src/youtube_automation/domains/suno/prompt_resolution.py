"""Resolve Suno prompt inputs before command-side pattern generation."""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence, Set
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import cast

import yaml

from youtube_automation.configuration.skills import load_channel_override, load_skill_config
from youtube_automation.core.errors import ConfigError, WorkflowStateError
from youtube_automation.domains.collections.workflow_state import read as read_workflow_state
from youtube_automation.domains.suno.config import ResolvedSunoConfig, infer_suno_mode, resolve_suno_config
from youtube_automation.domains.suno.downloaded.models import (
    DOCUMENTATION_DIRNAME,
    SUNO_LYRICS_JSON_FILENAME,
    SUNO_PATTERNS_FILENAME,
    SUNO_PROMPTS_JSON_FILENAME,
    SUNO_PROMPTS_MD_FILENAME,
)
from youtube_automation.domains.suno.downloaded.validation import (
    positive_integer_issue,
    require_instrumental_track_count,
    require_matching_suno_lyrics_names,
    require_unique_entry_names,
    require_vocal_track_count,
)
from youtube_automation.domains.suno.lyrics import load_suno_lyrics_by_name

DEFAULT_FULL_STYLE_CHAR_LIMIT = 256

_DURATION_SEC_KEY = "duration_sec"
_ADVANCED_JSON_KEYS = ("style_influence", "weirdness", "exclude_styles", "vocal_gender", _DURATION_SEC_KEY)
_VOCAL_GENDERS = frozenset({"male", "female", "neutral", "auto"})
_STYLE_VARIATION_BANNED_ADJECTIVES = frozenset(
    {
        "thundering",
        "blazing",
        "crushing",
        "soaring",
        "screaming",
        "devastating",
        "explosive",
        "ferocious",
        "towering",
        "surging",
        "crystalline",
        "shimmering",
        "lush",
        "sweeping",
        "majestic",
        "glorious",
        "echoing",
    }
)
_STYLE_VARIATION_ENVIRONMENT_NG_WORDS = frozenset(
    {
        "ambient noise",
        "dripping",
        "drops",
        "puddles",
        "pouring",
        "rain",
        "rain sounds",
        "splashing",
        "streaming water",
        "trickling",
        "vinyl crackle",
        "white noise",
    }
)
_STYLE_VARIATION_BARE_INSTRUMENTS = frozenset(
    {
        "bass",
        "cello",
        "drums",
        "flute",
        "guitar",
        "organ",
        "piano",
        "strings",
        "synth",
        "trumpet",
    }
)

_StaleOutputInventory = tuple[tuple[str, ...], Path]
_StaleOutputInventoryLoader = Callable[[], _StaleOutputInventory]


@dataclass(frozen=True)
class ResolvedStyleVariation:
    enabled: bool
    sequence: tuple[str, ...]


@dataclass(frozen=True)
class ResolvedPrompts:
    patterns_path: Path
    title: str
    is_vocal: bool
    genre_line: str
    banned_artists: tuple[str, ...]
    auto_lyrics_structure: bool
    duration_filter: Mapping[str, int | float]
    base_style: str
    style_influence: int
    weirdness: int
    exclude_styles: str
    full_style_char_limit: int
    advanced_json_fields: Mapping[str, object]
    style_variants: Mapping[str, Mapping[str, str]]
    uses_channel_style_variants: bool
    style_variation: ResolvedStyleVariation
    patterns: tuple[Mapping[str, object], ...]
    external_lyrics_path: Path
    external_lyrics: Mapping[str, str]
    has_external_lyrics: bool
    workflow_track_count: int | None
    patterns_track_count: int | None
    tracks_per_collection: object | None
    _stale_output_inventory_loader: _StaleOutputInventoryLoader = field(compare=False, repr=False)


@dataclass(frozen=True)
class _ResolvedBase:
    patterns_path: Path
    data: Mapping[str, object]
    title: str
    is_vocal: bool
    genre_line: str
    banned_artists: tuple[str, ...]
    auto_lyrics_structure: bool
    duration_filter: Mapping[str, int | float]
    base_style: str
    style_influence: int
    weirdness: int
    exclude_styles: str
    full_style_char_limit: int
    advanced_json_fields: Mapping[str, object]
    style_variants: Mapping[str, Mapping[str, str]]
    uses_channel_style_variants: bool
    style_variation: ResolvedStyleVariation
    patterns: tuple[Mapping[str, object], ...]
    tracks_per_collection: object | None


@dataclass(frozen=True)
class _ResolvedConfigHead:
    resolved_suno: ResolvedSunoConfig
    banned_artists: tuple[str, ...]
    auto_lyrics_structure: bool
    duration_filter: Mapping[str, int | float]
    full_style_char_limit: int
    advanced_json_fields: dict[str, object]


_SkillConfigLoader = Callable[[str], Mapping[str, object]]
_LyricsLoader = Callable[[Path], Mapping[str, str]]


def _freeze_value(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_value(item) for key, item in value.items()})
    if isinstance(value, (bytearray, memoryview)):
        return bytes(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, Set):
        return frozenset(_freeze_value(item) for item in value)
    return value


def _freeze_mapping(values: Mapping[str, object]) -> Mapping[str, object]:
    return cast(Mapping[str, object], _freeze_value(values))


def _resolve_full_style_char_limit(config: Mapping[str, object], override: Mapping[str, object]) -> int:
    if "full_style_char_limit" in override:
        value = override["full_style_char_limit"]
        source = "full_style_char_limit"
    elif "style_char_limit" in override:
        value = override["style_char_limit"]
        source = "style_char_limit"
    else:
        value = config.get("full_style_char_limit", DEFAULT_FULL_STYLE_CHAR_LIMIT)
        source = "full_style_char_limit"
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(f"config/skills/music.yaml::prompt.{source} must be a positive integer")
    return value


def _validate_duration_sec_override(override: Mapping[str, object]) -> None:
    if _DURATION_SEC_KEY not in override:
        return
    value = override[_DURATION_SEC_KEY]
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError("config/skills/music.yaml::prompt.duration_sec must be a positive integer")


def _build_advanced_json_fields(override: Mapping[str, object]) -> dict[str, object]:
    fields: dict[str, object] = {}
    for key in _ADVANCED_JSON_KEYS:
        if key not in override:
            continue
        value = override[key]
        if key in {"exclude_styles", "vocal_gender"} and value == "":
            continue
        fields[key] = value
    return fields


def _resolve_duration_filter(config: Mapping[str, object]) -> Mapping[str, int | float]:
    raw = config.get("duration_filter", {})
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise ConfigError("config/skills/music.yaml::prompt.duration_filter must be a mapping")
    min_sec = raw.get("min_sec", 60)
    max_sec = raw.get("max_sec", 300)
    if (
        isinstance(min_sec, bool)
        or isinstance(max_sec, bool)
        or not isinstance(min_sec, (int, float))
        or not isinstance(max_sec, (int, float))
        or not math.isfinite(min_sec)
        or not math.isfinite(max_sec)
    ):
        raise ConfigError("config/skills/music.yaml::prompt.duration_filter min_sec/max_sec must be finite numeric")
    if min_sec < 0 or max_sec < 0 or min_sec > max_sec:
        raise ConfigError("config/skills/music.yaml::prompt.duration_filter must satisfy 0 <= min_sec <= max_sec")
    return MappingProxyType({"min_sec": min_sec, "max_sec": max_sec})


def _resolve_config_head(config: Mapping[str, object], override: Mapping[str, object]) -> _ResolvedConfigHead:
    _validate_duration_sec_override(override)
    full_style_char_limit = _resolve_full_style_char_limit(config, override)
    advanced_json_fields = _build_advanced_json_fields(override)
    resolved_suno = resolve_suno_config(config)
    return _ResolvedConfigHead(
        resolved_suno=resolved_suno,
        banned_artists=tuple(cast(list[str], config.get("banned_artists", []))),
        auto_lyrics_structure=cast(bool, config.get("auto_lyrics_structure", False)),
        duration_filter=_resolve_duration_filter(config),
        full_style_char_limit=full_style_char_limit,
        advanced_json_fields=advanced_json_fields,
    )


def _resolve_genre_line(data: Mapping[str, object], channel_fallback: str, patterns_path: Path) -> str:
    if "genre_line" not in data:
        return channel_fallback
    genre_line = data["genre_line"]
    if not isinstance(genre_line, str):
        raise ConfigError(f"{patterns_path}: genre_line must be a string")
    return genre_line


def _resolve_exclude_styles(
    data: Mapping[str, object],
    channel_fallback: str,
    channel_json_fields: Mapping[str, object],
    patterns_path: Path,
) -> tuple[str, dict[str, object]]:
    if "exclude_styles" not in data:
        return channel_fallback, dict(channel_json_fields)
    exclude_styles = data["exclude_styles"]
    if not isinstance(exclude_styles, str):
        raise ConfigError(f"{patterns_path}: exclude_styles must be a string")
    return exclude_styles, {**channel_json_fields, "exclude_styles": exclude_styles}


def _resolve_vocal_gender(
    data: Mapping[str, object], channel_json_fields: Mapping[str, object], patterns_path: Path
) -> dict[str, object]:
    if "vocal_gender" not in data:
        return dict(channel_json_fields)
    vocal_gender = data["vocal_gender"]
    if not isinstance(vocal_gender, str) or (vocal_gender and vocal_gender not in _VOCAL_GENDERS):
        raise ConfigError(f"{patterns_path}: vocal_gender must be empty or one of: male, female, neutral, auto")
    resolved_fields = dict(channel_json_fields)
    if vocal_gender:
        resolved_fields["vocal_gender"] = vocal_gender
    else:
        resolved_fields.pop("vocal_gender", None)
    return resolved_fields


def _resolve_style_variants(
    data: Mapping[str, object], channel_fallback: object, patterns_path: Path
) -> tuple[Mapping[str, Mapping[str, str]], bool]:
    if "style_variants" not in data:
        frozen = _freeze_value(channel_fallback)
        return cast(Mapping[str, Mapping[str, str]], frozen), True
    style_variants = data["style_variants"]
    if not isinstance(style_variants, Mapping):
        raise ConfigError(f"{patterns_path}: style_variants must be a mapping")
    for key, variant in style_variants.items():
        if not isinstance(key, str) or not key:
            raise ConfigError(f"{patterns_path}: style_variants keys must be non-empty strings")
        if not isinstance(variant, Mapping):
            raise ConfigError(f"{patterns_path}: style_variants.{key} must be a mapping")
        for field_name in ("name", "genre_line"):
            if not isinstance(variant.get(field_name), str):
                raise ConfigError(f"{patterns_path}: style_variants.{key}.{field_name} must be a string")
    frozen = _freeze_value(style_variants)
    return cast(Mapping[str, Mapping[str, str]], frozen), False


def _contains_token_or_phrase(text: str, phrase: str) -> bool:
    if " " in phrase:
        return phrase in text
    return re.search(rf"\b{re.escape(phrase)}\b", text) is not None


def _validate_style_variation_descriptor(axis: str, descriptor: str, banned_artists: list[str]) -> None:
    normalized = " ".join(descriptor.lower().split())
    if normalized in _STYLE_VARIATION_BARE_INSTRUMENTS:
        raise ConfigError(f"suno.style_variation.pools.{axis} の descriptor は裸楽器名を使用できません: {descriptor!r}")
    for word in sorted(_STYLE_VARIATION_BANNED_ADJECTIVES):
        if _contains_token_or_phrase(normalized, word):
            raise ConfigError(
                f"suno.style_variation.pools.{axis} の descriptor に禁止形容詞を含めることはできません: {descriptor!r}"
            )
    for word in sorted(_STYLE_VARIATION_ENVIRONMENT_NG_WORDS):
        if _contains_token_or_phrase(normalized, word):
            raise ConfigError(
                f"suno.style_variation.pools.{axis} の descriptor に"
                f"雨音・環境音 NG ワードを含めることはできません: {descriptor!r}"
            )
    for artist in banned_artists:
        if isinstance(artist, str) and artist.strip() and artist.lower() in normalized:
            raise ConfigError(
                f"suno.style_variation.pools.{axis} の descriptor に"
                f"アーティスト名を含めることはできません: {descriptor!r}"
            )


def _build_variation_sequence(pools: Mapping[str, list[str]]) -> list[str]:
    axes = [pools[name] for name in sorted(pools) if pools[name]]
    if not axes:
        return []
    sequence: list[str] = []
    for index in range(max(len(axis) for axis in axes)):
        for axis in axes:
            if index < len(axis):
                sequence.append(axis[index])
    return sequence


def _resolve_style_variation(raw: object, *, banned_artists: list[str] | None = None) -> ResolvedStyleVariation:
    if raw is None:
        raise ConfigError("suno.style_variation は mapping である必要があります: None")
    if not isinstance(raw, Mapping):
        raise ConfigError(f"suno.style_variation は mapping である必要があります: {raw!r}")

    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigError(f"suno.style_variation.enabled は bool である必要があります: {enabled!r}")

    pools_raw = raw.get("pools", {})
    if pools_raw is None:
        raise ConfigError("suno.style_variation.pools は mapping である必要があります: None")
    if not isinstance(pools_raw, Mapping):
        raise ConfigError(f"suno.style_variation.pools は mapping である必要があります: {pools_raw!r}")

    pools: dict[str, list[str]] = {}
    for axis, descriptors_raw in pools_raw.items():
        if not isinstance(axis, str) or not axis.strip():
            raise ConfigError(f"suno.style_variation.pools の axis 名は非空文字列である必要があります: {axis!r}")
        if not isinstance(descriptors_raw, list):
            raise ConfigError(
                f"suno.style_variation.pools.{axis} は list[str] である必要があります: {descriptors_raw!r}"
            )
        descriptors: list[str] = []
        for descriptor in descriptors_raw:
            if not isinstance(descriptor, str) or not descriptor.strip():
                raise ConfigError(
                    f"suno.style_variation.pools.{axis} の descriptor は非空文字列である必要があります: {descriptor!r}"
                )
            _validate_style_variation_descriptor(axis, descriptor, banned_artists or [])
            descriptors.append(descriptor)
        pools[axis] = descriptors

    sequence = _build_variation_sequence(pools) if enabled else []
    return ResolvedStyleVariation(enabled=enabled, sequence=tuple(sequence))


def _resolve_base(
    patterns: Mapping[str, object],
    config: Mapping[str, object],
    override: Mapping[str, object],
    patterns_path: Path,
    *,
    config_head: _ResolvedConfigHead | None = None,
) -> _ResolvedBase:
    head = config_head if config_head is not None else _resolve_config_head(config, override)
    genre_line = _resolve_genre_line(patterns, head.resolved_suno.genre_line, patterns_path)
    exclude_styles, advanced_json_fields = _resolve_exclude_styles(
        patterns, head.resolved_suno.exclude_styles, head.advanced_json_fields, patterns_path
    )
    advanced_json_fields = _resolve_vocal_gender(patterns, advanced_json_fields, patterns_path)
    style_variants, uses_channel_style_variants = _resolve_style_variants(
        patterns, config.get("style_variants", {}), patterns_path
    )
    style_variation = _resolve_style_variation(
        config.get("style_variation"),
        banned_artists=cast(list[str], config.get("banned_artists", [])),
    )

    base_parts = [genre_line]
    mood_descriptors = config.get("mood_descriptors", "")
    if mood_descriptors:
        base_parts.append(cast(str, mood_descriptors))
    mode = patterns.get("mode", infer_suno_mode(genre_line))
    is_vocal = mode == "vocal"
    tracks_override = patterns.get("tracks")
    tracks_per_collection = tracks_override if tracks_override is not None else config.get("tracks_per_collection")

    return _ResolvedBase(
        patterns_path=patterns_path,
        data=patterns,
        title=cast(str, patterns.get("title", "Suno Prompts")),
        is_vocal=is_vocal,
        genre_line=genre_line,
        banned_artists=head.banned_artists,
        auto_lyrics_structure=head.auto_lyrics_structure,
        duration_filter=head.duration_filter,
        base_style=", ".join(base_parts),
        style_influence=cast(int, config.get("style_influence", 50)),
        weirdness=cast(int, config.get("weirdness", 50)),
        exclude_styles=exclude_styles,
        full_style_char_limit=head.full_style_char_limit,
        advanced_json_fields=_freeze_mapping(advanced_json_fields),
        style_variants=style_variants,
        uses_channel_style_variants=uses_channel_style_variants,
        style_variation=style_variation,
        patterns=tuple(
            _freeze_mapping(pattern) for pattern in cast(list[Mapping[str, object]], patterns.get("patterns", []))
        ),
        tracks_per_collection=_freeze_value(tracks_per_collection),
    )


def _workflow_state_path(patterns_path: Path) -> Path | None:
    if patterns_path.name != SUNO_PATTERNS_FILENAME or patterns_path.parent.name != DOCUMENTATION_DIRNAME:
        return None
    return patterns_path.parent.parent.resolve() / "workflow-state.json"


def _read_workflow_track_count(workflow_state_path: Path) -> int:
    if not workflow_state_path.is_file():
        raise ConfigError(f"workflow-state.json is required for vocal mode: {workflow_state_path}")
    try:
        state = read_workflow_state(workflow_state_path)
        track_count = state.track_count
    except WorkflowStateError as exc:
        if "root must be an object" in str(exc):
            raise ConfigError(
                f"workflow-state.json のトップレベルは object である必要があります: {workflow_state_path}"
            ) from exc
        raise ConfigError(f"workflow-state.json を読み取れませんでした: {workflow_state_path}") from exc
    issue = positive_integer_issue(track_count, "workflow-state.json::track_count")
    if issue is not None:
        raise ConfigError(f"{issue}: {workflow_state_path}")
    return cast(int, track_count)


def _patterns_track_count(base: _ResolvedBase, workflow_state_path: Path | None) -> int | None:
    if not base.is_vocal or workflow_state_path is None:
        return None
    track_count = base.data.get("tracks")
    issue = positive_integer_issue(track_count, "suno-patterns.yaml::tracks")
    if issue is not None:
        raise ConfigError(f"{issue}: {base.patterns_path}")
    return cast(int, track_count)


def _finalize(
    base: _ResolvedBase,
    *,
    workflow_track_count: int | None,
    patterns_track_count: int | None,
    lyrics: Mapping[str, str] | None,
    existing_output_names: tuple[str, ...],
    verification_collection_path: Path,
    stale_output_inventory_loader: _StaleOutputInventoryLoader | None = None,
) -> ResolvedPrompts:
    external_lyrics_path = base.patterns_path.parent / SUNO_LYRICS_JSON_FILENAME
    if base.is_vocal and lyrics is None:
        raise ConfigError(
            f"{SUNO_LYRICS_JSON_FILENAME} is required for vocal mode. "
            f"Run /music --lyric first and write: {external_lyrics_path}"
        )
    frozen_output_names = tuple(existing_output_names)
    if stale_output_inventory_loader is None:
        inventory = (frozen_output_names, verification_collection_path)

        def load_stale_output_inventory() -> _StaleOutputInventory:
            return inventory

        stale_output_inventory_loader = load_stale_output_inventory

    return ResolvedPrompts(
        patterns_path=base.patterns_path,
        title=base.title,
        is_vocal=base.is_vocal,
        genre_line=base.genre_line,
        banned_artists=base.banned_artists,
        auto_lyrics_structure=base.auto_lyrics_structure,
        duration_filter=base.duration_filter,
        base_style=base.base_style,
        style_influence=base.style_influence,
        weirdness=base.weirdness,
        exclude_styles=base.exclude_styles,
        full_style_char_limit=base.full_style_char_limit,
        advanced_json_fields=base.advanced_json_fields,
        style_variants=base.style_variants,
        uses_channel_style_variants=base.uses_channel_style_variants,
        style_variation=base.style_variation,
        patterns=base.patterns,
        external_lyrics_path=external_lyrics_path,
        external_lyrics=MappingProxyType({} if lyrics is None else dict(lyrics)),
        has_external_lyrics=base.is_vocal,
        workflow_track_count=workflow_track_count,
        patterns_track_count=patterns_track_count,
        tracks_per_collection=base.tracks_per_collection,
        _stale_output_inventory_loader=stale_output_inventory_loader,
    )


def resolve(
    patterns: Mapping[str, object],
    config: Mapping[str, object],
    override: Mapping[str, object],
    *,
    patterns_path: Path,
    workflow_state_path: Path | None,
    workflow_track_count: int | None,
    lyrics: Mapping[str, str] | None,
    existing_output_names: tuple[str, ...],
    verification_collection_path: Path,
) -> ResolvedPrompts:
    """Resolve loaded mappings without performing file I/O."""
    base = _resolve_base(patterns, config, override, patterns_path)
    if base.is_vocal and workflow_state_path is not None and workflow_track_count is None:
        raise ConfigError(f"workflow-state.json is required for vocal mode: {workflow_state_path}")
    return _finalize(
        base,
        workflow_track_count=workflow_track_count,
        patterns_track_count=_patterns_track_count(base, workflow_state_path),
        lyrics=lyrics,
        existing_output_names=existing_output_names,
        verification_collection_path=verification_collection_path,
    )


def resolve_from_path(
    patterns_path: Path,
    *,
    skill_config_loader: _SkillConfigLoader | None = None,
    channel_override_loader: _SkillConfigLoader | None = None,
    lyrics_loader: _LyricsLoader | None = None,
) -> ResolvedPrompts:
    """Load config and prompt artifacts, then delegate mapping resolution."""
    config = (load_skill_config if skill_config_loader is None else skill_config_loader)("music.prompt")
    override = (load_channel_override if channel_override_loader is None else channel_override_loader)("music.prompt")
    config_head = _resolve_config_head(config, override)
    with open(patterns_path) as file:
        patterns = cast(Mapping[str, object], yaml.safe_load(file))

    base = _resolve_base(patterns, config, override, patterns_path, config_head=config_head)
    workflow_state_path = _workflow_state_path(patterns_path) if base.is_vocal else None
    workflow_track_count = _read_workflow_track_count(workflow_state_path) if workflow_state_path is not None else None
    external_lyrics_path = patterns_path.parent / SUNO_LYRICS_JSON_FILENAME
    if base.is_vocal and not external_lyrics_path.exists():
        lyrics = None
    else:
        loader = load_suno_lyrics_by_name if lyrics_loader is None else lyrics_loader
        lyrics = loader(external_lyrics_path) if base.is_vocal else None
    verification_collection_path = (
        patterns_path.parent.parent if patterns_path.parent.name == DOCUMENTATION_DIRNAME else patterns_path.parent
    )

    def load_stale_output_inventory() -> _StaleOutputInventory:
        names = tuple(
            path.name
            for path in (
                patterns_path.parent / SUNO_PROMPTS_MD_FILENAME,
                patterns_path.parent / SUNO_PROMPTS_JSON_FILENAME,
            )
            if path.exists()
        )
        return names, verification_collection_path

    return _finalize(
        base,
        workflow_track_count=workflow_track_count,
        patterns_track_count=_patterns_track_count(base, workflow_state_path),
        lyrics=lyrics,
        existing_output_names=(),
        verification_collection_path=verification_collection_path,
        stale_output_inventory_loader=load_stale_output_inventory,
    )


def resolve_style_variant(resolved: ResolvedPrompts, style_key: object) -> Mapping[str, str] | None:
    if not style_key:
        return None
    if style_key in resolved.style_variants:
        return resolved.style_variants[cast(str, style_key)]

    base_message = (
        f"{resolved.patterns_path}: pattern.style に未定義の style variant が指定されています: {style_key!r}。"
    )
    if not resolved.uses_channel_style_variants:
        raise ConfigError(
            base_message
            + "collection-local style_variants にこの key を追加するか、pattern.style の typo を修正してください。"
        )

    message = (
        base_message + "patterns root に style_variants がない legacy collection のため、"
        "channel fallback drift（config/skills/music.yaml::prompt 側で key が変更・削除された可能性）があります。"
        "channel 共有設定には依存せず、必要な定義を collection-local "
        "suno-patterns.yaml::style_variants へ移してください。"
    )
    existing_output_names, verification_collection_path = resolved._stale_output_inventory_loader()
    if existing_output_names:
        message += (
            f"既存成果物 ({', '.join(existing_output_names)}) は更新されず stale のままです。"
            "設定修正後に再生成し、"
            f"`uv run yt-suno-verify {verification_collection_path}` を実行してください。"
        )
    raise ConfigError(message)


def validate_generated_prompts(
    resolved: ResolvedPrompts,
    *,
    entry_names: list[str],
    entries_count: int,
    expected_external_lyrics_names: set[str],
) -> None:
    """Apply post-generation count, lyrics, and uniqueness contracts."""
    if resolved.has_external_lyrics:
        require_matching_suno_lyrics_names(
            lyrics_path=resolved.external_lyrics_path,
            expected_names=expected_external_lyrics_names,
            actual_names=set(resolved.external_lyrics),
        )

    if not resolved.is_vocal:
        if resolved.tracks_per_collection is not None:
            require_instrumental_track_count(
                resolved.patterns_path,
                entries_count,
                resolved.tracks_per_collection,
            )
    elif resolved.workflow_track_count is not None and resolved.patterns_track_count is not None:
        require_vocal_track_count(
            entries_count=len(entry_names),
            patterns_tracks=resolved.patterns_track_count,
            workflow_track_count=resolved.workflow_track_count,
        )

    require_unique_entry_names(resolved.patterns_path, entry_names)
