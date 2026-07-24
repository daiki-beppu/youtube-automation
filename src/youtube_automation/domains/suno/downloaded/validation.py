"""Shared validation helpers for Suno prompt and lyric artifacts."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml

from youtube_automation.domains.suno.downloaded.models import (
    DOCUMENTATION_DIRNAME,
    SUNO_LYRICS_JSON_FILENAME,
    SUNO_PATTERNS_FILENAME,
    SUNO_PROMPTS_JSON_FILENAME,
    SunoConfig,
    SunoModeInferer,
)
from youtube_automation.domains.uploads.preflight import check_suno_genre_line_char_limit
from youtube_automation.infrastructure.errors import ConfigError

SECTION_TAG_RE = re.compile(r"\[[A-Za-z][A-Za-z0-9 -]*\]")
INSTRUMENTAL_TAG_RE = re.compile(r"\[Instrumental\]", re.IGNORECASE)


def expected_instrumental_prompt_entries(tracks_per_collection: int) -> int:
    return math.ceil(tracks_per_collection / 2)


def positive_integer_issue(value: object, context: str) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return f"{context} must be a positive integer: {value!r}"
    return None


def suno_prompt_entry_name(
    name_jp: str,
    name_en: str,
    variation_index: int | None = None,
) -> str:
    base_name = f"{name_jp} — {name_en}"
    if variation_index is not None:
        base_name = f"{base_name} (Variation {variation_index})"
    return base_name


def suno_prompt_entry_names(
    name_jp: str,
    name_en: str,
    scenes_count: int,
) -> list[str]:
    return _scene_entry_names(name_jp, name_en, scenes_count)


def _scene_entry_names(name_jp: str, name_en: str, scenes_count: int) -> list[str]:
    return [
        suno_prompt_entry_name(name_jp, name_en, variation_index=variation_index)
        for variation_index in _variation_indexes(scenes_count)
    ]


def _variation_indexes(scenes_count: int) -> list[int | None]:
    if scenes_count == 1:
        return [None]
    return list(range(1, scenes_count + 1))


def surrounding_whitespace_issue(*, source_name: str, field_path: str, value: str) -> str | None:
    if value == value.strip():
        return None
    return f"{source_name} {field_path} must not have leading or trailing whitespace"


def instrumental_track_count_issue(
    *,
    source_name: str,
    entries_count: int,
    tracks_per_collection: int,
) -> str | None:
    expected = expected_instrumental_prompt_entries(tracks_per_collection)
    if entries_count == expected:
        return None
    return (
        f"インストモード: tracks_per_collection={tracks_per_collection} から "
        f"ceil({tracks_per_collection}/2)={expected} 個の entry が必要ですが、"
        f"{source_name} には {entries_count} 個あります "
        f"(`patterns:` 配列の `scenes` 行数の合計)。"
    )


def require_instrumental_track_count(
    yaml_path: Path,
    entries_count: int,
    tracks_per_collection: int,
) -> None:
    issue = instrumental_track_count_issue(
        source_name=yaml_path.name,
        entries_count=entries_count,
        tracks_per_collection=tracks_per_collection,
    )
    if issue is not None:
        raise ConfigError(issue)


def vocal_track_count_issues(
    *,
    entries_count: int,
    patterns_tracks: int,
    workflow_track_count: int,
) -> list[str]:
    """Return vocal collection track-count contract violations.

    A vocal collection selects one winner per generated prompt entry.  Extra
    entries are valid audition buffer, but fewer entries than the collection's
    planned track count cannot produce the requested number of winners.
    """
    issues: list[str] = []
    if patterns_tracks != workflow_track_count:
        issues.append(
            "ボーカルモード: suno-patterns.yaml tracks="
            f"{patterns_tracks} must match workflow-state.json track_count={workflow_track_count}."
        )
    if entries_count < workflow_track_count:
        issues.append(
            "ボーカルモード: workflow-state.json track_count="
            f"{workflow_track_count} requires at least {workflow_track_count} prompt entries, "
            f"but suno-patterns.yaml resolves to {entries_count}."
        )
    return issues


def require_vocal_track_count(
    *,
    entries_count: int,
    patterns_tracks: int,
    workflow_track_count: int,
) -> None:
    issues = vocal_track_count_issues(
        entries_count=entries_count,
        patterns_tracks=patterns_tracks,
        workflow_track_count=workflow_track_count,
    )
    if issues:
        raise ConfigError(" ".join(issues))


def duplicated_names(names: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for name in names:
        if name in seen:
            duplicates.add(name)
        seen.add(name)
    return sorted(duplicates)


def unique_entry_names_issue(
    *,
    source_name: str,
    entry_names: list[str],
    label: str,
) -> str | None:
    duplicates = duplicated_names(entry_names)
    if not duplicates:
        return None
    return f"{label} duplicated in {source_name}: {', '.join(duplicates)}"


def require_unique_entry_names(yaml_path: Path, entry_names: list[str]) -> None:
    duplicates = duplicated_names(entry_names)
    if duplicates:
        raise ConfigError(
            f"全曲のタイトル (entry name) はユニークでなければなりません。"
            f"{yaml_path.name} で以下が重複しています: {', '.join(duplicates)}"
        )


def name_set_mismatch_issues(
    *,
    source_name: str,
    expected_names: set[str],
    actual_names: set[str],
) -> list[str]:
    missing = sorted(expected_names - actual_names)
    extra = sorted(actual_names - expected_names)
    issues: list[str] = []
    if missing:
        issues.append(f"{source_name} missing: {', '.join(missing)}")
    if extra:
        issues.append(f"{source_name} extra: {', '.join(extra)}")
    return issues


def require_matching_suno_lyrics_names(
    *,
    lyrics_path: Path,
    expected_names: set[str],
    actual_names: set[str],
) -> None:
    issues = name_set_mismatch_issues(
        source_name=SUNO_LYRICS_JSON_FILENAME,
        expected_names=expected_names,
        actual_names=actual_names,
    )
    if not issues:
        return
    details = "; ".join(issue.removeprefix(f"{SUNO_LYRICS_JSON_FILENAME} ") for issue in issues)
    raise ConfigError(f"{SUNO_LYRICS_JSON_FILENAME} names must match prompt entry names: {lyrics_path} ({details})")


def vocal_lyrics_structure_issues(
    *,
    source_name: str = SUNO_LYRICS_JSON_FILENAME,
    name: str,
    lyrics: str,
) -> list[str]:
    issues: list[str] = []
    if not lyrics.strip():
        issues.append(f"{source_name} entry '{name}' lyrics must be non-empty")
        return issues
    if SECTION_TAG_RE.search(lyrics) is None:
        issues.append(f"{source_name} entry '{name}' lyrics must include a section tag")
    if INSTRUMENTAL_TAG_RE.search(lyrics) is not None:
        issues.append(f"{source_name} entry '{name}' must not include [Instrumental] in vocal mode")
    return issues


_VALID_MODES = frozenset({"instrumental", "vocal"})


@dataclass(frozen=True)
class PatternContract:
    mode: str
    expected_names: list[str]
    style_keys: frozenset[str]
    tracks_per_collection: int | None


@dataclass(frozen=True)
class ArtifactLyrics:
    name: str
    lyrics: str


@dataclass(frozen=True)
class ArtifactEntries:
    names: list[str]
    lyrics_by_name: dict[str, str]
    lyrics_entries: list[ArtifactLyrics]


def load_pattern_contract(
    patterns_path: Path,
    suno_cfg: SunoConfig,
    infer_mode: SunoModeInferer,
) -> tuple[PatternContract | None, list[str]]:
    raw, issues = _load_yaml_mapping(patterns_path, SUNO_PATTERNS_FILENAME)
    if raw is None:
        return None, issues

    mode, mode_issues = _resolve_mode(raw, suno_cfg, infer_mode)
    expected_names, style_keys, pattern_issues = _pattern_contract_data_from_patterns(
        raw.get("patterns"),
    )
    tracks_per_collection, tracks_issues = _resolve_tracks_per_collection(raw, suno_cfg)
    issues.extend(mode_issues)
    issues.extend(pattern_issues)
    issues.extend(tracks_issues)
    if mode is None:
        return None, issues
    contract = PatternContract(
        mode=mode,
        expected_names=expected_names,
        style_keys=style_keys,
        tracks_per_collection=tracks_per_collection,
    )
    return contract, issues


def load_prompt_entries(prompts_path: Path) -> tuple[ArtifactEntries, list[str]]:
    raw, issues = _load_json(prompts_path, SUNO_PROMPTS_JSON_FILENAME)
    if raw is None:
        return ArtifactEntries(names=[], lyrics_by_name={}, lyrics_entries=[]), issues
    if isinstance(raw, Mapping):
        raw_entries = raw.get("entries")
        if not isinstance(raw_entries, list):
            issues.append(f"{SUNO_PROMPTS_JSON_FILENAME} root mapping must contain list field 'entries'")
            return ArtifactEntries(names=[], lyrics_by_name={}, lyrics_entries=[]), issues
        raw = raw_entries
    if not isinstance(raw, list):
        issues.append(f"{SUNO_PROMPTS_JSON_FILENAME} root must be a list of entries or mapping with 'entries'")
        return ArtifactEntries(names=[], lyrics_by_name={}, lyrics_entries=[]), issues
    entries, entry_issues = _prompt_entries_from_json_list(raw)
    issues.extend(entry_issues)
    return entries, issues


def load_lyric_entries(lyrics_path: Path) -> tuple[ArtifactEntries, list[str]]:
    raw, issues = _load_json(lyrics_path, SUNO_LYRICS_JSON_FILENAME)
    if raw is None:
        return ArtifactEntries(names=[], lyrics_by_name={}, lyrics_entries=[]), issues
    if not isinstance(raw, list):
        issues.append(f"{SUNO_LYRICS_JSON_FILENAME} root must be a list of entries")
        return ArtifactEntries(names=[], lyrics_by_name={}, lyrics_entries=[]), issues
    entries, entry_issues = _lyric_entries_from_json_list(raw)
    issues.extend(entry_issues)
    return entries, issues


def _load_json(path: Path, filename: str) -> tuple[object | None, list[str]]:
    if not path.exists():
        return None, [f"{filename} not found: {path}"]
    try:
        return json.loads(path.read_text(encoding="utf-8")), []
    except json.JSONDecodeError as exc:
        return None, [f"{filename} is invalid JSON: {path}: {exc}"]
    except OSError as exc:
        return None, [f"{filename} could not be read: {path}: {exc}"]


def _load_yaml_mapping(path: Path, filename: str) -> tuple[Mapping[str, object] | None, list[str]]:
    if not path.exists():
        return None, [f"{filename} not found: {path}"]
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return None, [f"{filename} is invalid YAML: {path}: {exc}"]
    except OSError as exc:
        return None, [f"{filename} could not be read: {path}: {exc}"]
    if not isinstance(raw, Mapping):
        return None, [f"{filename} root must be a mapping"]
    return raw, []


def _resolve_mode(
    raw: Mapping[str, object], suno_cfg: SunoConfig, infer_mode: SunoModeInferer
) -> tuple[str | None, list[str]]:
    raw_mode = raw.get("mode")
    if raw_mode is None:
        return infer_mode(suno_cfg.genre_line), []
    if not isinstance(raw_mode, str) or raw_mode not in _VALID_MODES:
        return None, [f"{SUNO_PATTERNS_FILENAME} mode must be one of {sorted(_VALID_MODES)}: {raw_mode!r}"]
    return raw_mode, []


def _positive_int(value: object, context: str) -> tuple[int | None, list[str]]:
    issue = positive_integer_issue(value, context)
    if issue is not None:
        return None, [issue]
    return cast(int, value), []


def _pattern_contract_data_from_patterns(
    raw_patterns: object,
) -> tuple[list[str], frozenset[str], list[str]]:
    if not isinstance(raw_patterns, list):
        return [], frozenset(), [f"{SUNO_PATTERNS_FILENAME} patterns must be a list"]

    names: list[str] = []
    style_keys: set[str] = set()
    issues: list[str] = []
    for index, pattern in enumerate(raw_patterns, 1):
        pattern_names, pattern_issues = _entry_names_from_pattern(pattern, index)
        names.extend(pattern_names)
        issues.extend(pattern_issues)
        style_key = _style_key_from_pattern(pattern)
        if style_key is not None:
            style_keys.add(style_key)
    return names, frozenset(style_keys), issues


def _entry_names_from_pattern(
    pattern: object,
    index: int,
) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    if not isinstance(pattern, Mapping):
        return [], [f"{SUNO_PATTERNS_FILENAME} patterns[{index}] must be a mapping"]
    name_jp = pattern.get("name_jp")
    name_en = pattern.get("name_en")
    scenes = pattern.get("scenes")
    if not isinstance(name_jp, str) or not name_jp.strip():
        return [], [f"{SUNO_PATTERNS_FILENAME} patterns[{index}].name_jp must be a non-empty string"]
    if not isinstance(name_en, str) or not name_en.strip():
        return [], [f"{SUNO_PATTERNS_FILENAME} patterns[{index}].name_en must be a non-empty string"]
    for field_name, value in (("name_jp", name_jp), ("name_en", name_en)):
        issue = surrounding_whitespace_issue(
            source_name=SUNO_PATTERNS_FILENAME,
            field_path=f"patterns[{index}].{field_name}",
            value=value,
        )
        if issue is not None:
            issues.append(issue)
    if not isinstance(scenes, list) or not scenes:
        issues.append(f"{SUNO_PATTERNS_FILENAME} patterns[{index}].scenes must be a non-empty list")
        return [], issues
    invalid_scene_indexes = [
        scene_index for scene_index, scene in enumerate(scenes, 1) if not isinstance(scene, str) or not scene.strip()
    ]
    if invalid_scene_indexes:
        joined = ", ".join(str(scene_index) for scene_index in invalid_scene_indexes)
        issues.append(f"{SUNO_PATTERNS_FILENAME} patterns[{index}].scenes has invalid entries: {joined}")
        return [], issues

    return suno_prompt_entry_names(name_jp, name_en, len(scenes)), issues


def _style_key_from_pattern(pattern: object) -> str | None:
    if not isinstance(pattern, Mapping):
        return None
    style_key = pattern.get("style")
    return style_key if isinstance(style_key, str) and style_key else None


def _resolve_tracks_per_collection(
    raw: Mapping[str, object],
    suno_cfg: SunoConfig,
) -> tuple[int | None, list[str]]:
    if "tracks" in raw:
        return _positive_int(raw.get("tracks"), f"{SUNO_PATTERNS_FILENAME} tracks")
    if "tracks_per_collection" not in suno_cfg.raw:
        return None, []
    return _positive_int(
        suno_cfg.raw.get("tracks_per_collection"),
        "config/skills/suno.yaml::tracks_per_collection",
    )


def _prompt_entries_from_json_list(raw: list[object]) -> tuple[ArtifactEntries, list[str]]:
    names: list[str] = []
    lyrics_by_name: dict[str, str] = {}
    lyrics_entries: list[ArtifactLyrics] = []
    issues: list[str] = []
    for index, item in enumerate(raw, 1):
        if not isinstance(item, Mapping):
            issues.append(f"{SUNO_PROMPTS_JSON_FILENAME} entry {index} must be an object")
            continue
        entry, entry_issues = _prompt_entry_from_mapping(item, index)
        names.extend(entry.names)
        lyrics_by_name.update(entry.lyrics_by_name)
        lyrics_entries.extend(entry.lyrics_entries)
        issues.extend(entry_issues)

    duplicate_issue = unique_entry_names_issue(
        source_name=SUNO_PROMPTS_JSON_FILENAME,
        entry_names=names,
        label="prompt entry names",
    )
    if duplicate_issue is not None:
        issues.append(duplicate_issue)
    return ArtifactEntries(names=names, lyrics_by_name=lyrics_by_name, lyrics_entries=lyrics_entries), issues


def _prompt_entry_from_mapping(
    item: Mapping[str, object],
    index: int,
) -> tuple[ArtifactEntries, list[str]]:
    issues: list[str] = []
    name = item.get("name")
    style = item.get("style")
    lyrics = item.get("lyrics")
    if not isinstance(name, str) or not name.strip():
        return ArtifactEntries(names=[], lyrics_by_name={}, lyrics_entries=[]), [
            f"{SUNO_PROMPTS_JSON_FILENAME} entry {index}.name must be a non-empty string"
        ]
    issue = surrounding_whitespace_issue(
        source_name=SUNO_PROMPTS_JSON_FILENAME,
        field_path=f"entry {index}.name",
        value=name,
    )
    if issue is not None:
        issues.append(issue)
    if not isinstance(style, str) or not style.strip():
        issues.append(f"{SUNO_PROMPTS_JSON_FILENAME} entry '{name}' style must be a non-empty string")
    if isinstance(lyrics, str):
        entry = ArtifactEntries(
            names=[name],
            lyrics_by_name={name: lyrics},
            lyrics_entries=[ArtifactLyrics(name=name, lyrics=lyrics)],
        )
    else:
        issues.append(f"{SUNO_PROMPTS_JSON_FILENAME} entry '{name}' lyrics must be a string")
        entry = ArtifactEntries(names=[name], lyrics_by_name={}, lyrics_entries=[])
    return entry, issues


def _lyric_entries_from_json_list(raw: list[object]) -> tuple[ArtifactEntries, list[str]]:
    names: list[str] = []
    lyrics_by_name: dict[str, str] = {}
    lyrics_entries: list[ArtifactLyrics] = []
    issues: list[str] = []
    for index, item in enumerate(raw, 1):
        if not isinstance(item, Mapping):
            issues.append(f"{SUNO_LYRICS_JSON_FILENAME} entry {index} must be an object")
            continue
        entry, entry_issues = _lyric_entry_from_mapping(item, index)
        names.extend(entry.names)
        lyrics_by_name.update(entry.lyrics_by_name)
        lyrics_entries.extend(entry.lyrics_entries)
        issues.extend(entry_issues)

    duplicates = duplicated_names(names)
    if duplicates:
        issues.append(f"{SUNO_LYRICS_JSON_FILENAME} duplicated lyrics entry names: {', '.join(duplicates)}")
    return ArtifactEntries(names=names, lyrics_by_name=lyrics_by_name, lyrics_entries=lyrics_entries), issues


def _lyric_entry_from_mapping(
    item: Mapping[str, object],
    index: int,
) -> tuple[ArtifactEntries, list[str]]:
    issues: list[str] = []
    name = item.get("name")
    lyrics = item.get("lyrics")
    if not isinstance(name, str) or not name.strip():
        return ArtifactEntries(names=[], lyrics_by_name={}, lyrics_entries=[]), [
            f"{SUNO_LYRICS_JSON_FILENAME} entry {index}.name must be a non-empty string"
        ]
    issue = surrounding_whitespace_issue(
        source_name=SUNO_LYRICS_JSON_FILENAME,
        field_path=f"entry {index}.name",
        value=name,
    )
    if issue is not None:
        issues.append(issue)
    if not isinstance(lyrics, str):
        issues.append(f"{SUNO_LYRICS_JSON_FILENAME} entry '{name}' lyrics must be a string")
        return ArtifactEntries(names=[name], lyrics_by_name={}, lyrics_entries=[]), issues
    normalized_lyrics = lyrics.rstrip()
    return (
        ArtifactEntries(
            names=[name],
            lyrics_by_name={name: normalized_lyrics},
            lyrics_entries=[ArtifactLyrics(name=name, lyrics=normalized_lyrics)],
        ),
        issues,
    )


def verify_suno_collection(
    collection_dir: Path, suno_cfg: SunoConfig, infer_mode: SunoModeInferer
) -> tuple[list[str], str]:
    docs_dir = collection_dir / DOCUMENTATION_DIRNAME
    patterns_path = docs_dir / SUNO_PATTERNS_FILENAME
    prompts_path = docs_dir / SUNO_PROMPTS_JSON_FILENAME
    lyrics_path = docs_dir / SUNO_LYRICS_JSON_FILENAME

    issues = _preflight_issues(suno_cfg)
    contract, pattern_issues = load_pattern_contract(patterns_path, suno_cfg, infer_mode)
    issues = [*issues, *pattern_issues]
    if contract is None:
        return issues, "mode=unknown prompt_entries=0"
    issues = [*issues, *_style_variant_genre_line_issues(suno_cfg, contract)]

    expected_name_issue = unique_entry_names_issue(
        source_name=SUNO_PATTERNS_FILENAME,
        entry_names=contract.expected_names,
        label="pattern-derived entry names",
    )
    if expected_name_issue is not None:
        issues = [*issues, expected_name_issue]

    prompts, prompt_issues = _validate_prompts(prompts_path, contract)
    issues = [*issues, *prompt_issues]
    if contract.mode == "vocal":
        vocal_issues, summary = _verify_vocal_artifacts(lyrics_path, contract, prompts)
        return [*issues, *vocal_issues], summary
    return issues, _instrumental_summary(contract, prompts)


def _preflight_issues(suno_cfg: SunoConfig) -> list[str]:
    genre_line_issue = check_suno_genre_line_char_limit({**suno_cfg.raw, "genre_line": suno_cfg.genre_line})
    return [] if genre_line_issue is None else [genre_line_issue]


def _style_variant_genre_line_issues(suno_cfg: SunoConfig, contract: PatternContract) -> list[str]:
    variants = suno_cfg.raw.get("style_variants")
    if not isinstance(variants, Mapping):
        return []

    issues: list[str] = []
    for style_key in sorted(contract.style_keys):
        variant = variants.get(style_key)
        if not isinstance(variant, Mapping):
            continue
        genre_line = variant.get("genre_line")
        if not isinstance(genre_line, str):
            continue
        issue = check_suno_genre_line_char_limit({**suno_cfg.raw, "genre_line": genre_line})
        if issue is not None:
            issues.append(
                issue.replace(
                    "config/skills/suno.yaml::genre_line",
                    f"config/skills/suno.yaml::style_variants.{style_key}.genre_line",
                )
            )
    return issues


def _validate_prompts(prompts_path: Path, contract: PatternContract) -> tuple[ArtifactEntries, list[str]]:
    prompts_exist = prompts_path.exists()
    if not prompts_exist and contract.mode == "vocal":
        return ArtifactEntries(names=contract.expected_names, lyrics_by_name={}, lyrics_entries=[]), []

    prompts, prompt_issues = load_prompt_entries(prompts_path)
    issues = [
        *prompt_issues,
        *name_set_mismatch_issues(
            source_name=SUNO_PROMPTS_JSON_FILENAME,
            expected_names=set(contract.expected_names),
            actual_names=set(prompts.names),
        ),
        *_prompt_count_issues(contract, prompts),
    ]
    return prompts, issues


def _verify_vocal_artifacts(
    lyrics_path: Path,
    contract: PatternContract,
    prompts: ArtifactEntries,
) -> tuple[list[str], str]:
    lyrics, lyric_issues = load_lyric_entries(lyrics_path)
    issues = [
        *lyric_issues,
        *_vocal_artifact_issues(prompts, lyrics),
    ]

    summary = f"mode=vocal prompt_entries={len(prompts.names)} expected_entries={len(contract.expected_names)}"
    return issues, summary


def _instrumental_summary(contract: PatternContract, prompts: ArtifactEntries) -> str:
    tracks_text = contract.tracks_per_collection
    summary = f"mode=instrumental prompt_entries={len(prompts.names)} tracks_per_collection={tracks_text}"
    if contract.tracks_per_collection is not None:
        expected_entries = expected_instrumental_prompt_entries(contract.tracks_per_collection)
        summary = f"{summary} expected_entries={expected_entries}"
    return summary


def _prompt_count_issues(contract: PatternContract, prompts: ArtifactEntries) -> list[str]:
    if contract.mode == "instrumental":
        if contract.tracks_per_collection is None:
            return []
        issue = instrumental_track_count_issue(
            source_name=SUNO_PROMPTS_JSON_FILENAME,
            entries_count=len(prompts.names),
            tracks_per_collection=contract.tracks_per_collection,
        )
        return [] if issue is None else [issue]

    expected_count = len(contract.expected_names)
    actual_count = len(prompts.names)
    if actual_count == expected_count:
        return []
    return [f"mode=vocal expected prompt entries={expected_count}, actual prompt entries={actual_count}"]


def _vocal_artifact_issues(prompts: ArtifactEntries, lyrics: ArtifactEntries) -> list[str]:
    issues = [
        *name_set_mismatch_issues(
            source_name=SUNO_LYRICS_JSON_FILENAME,
            expected_names=set(prompts.names),
            actual_names=set(lyrics.names),
        ),
        *_lyrics_structure_issues(SUNO_PROMPTS_JSON_FILENAME, prompts),
        *_lyrics_structure_issues(SUNO_LYRICS_JSON_FILENAME, lyrics),
    ]
    return issues


def _lyrics_structure_issues(source_name: str, entries: ArtifactEntries) -> list[str]:
    issues: list[str] = []
    for entry in entries.lyrics_entries:
        issues.extend(
            vocal_lyrics_structure_issues(
                source_name=source_name,
                name=entry.name,
                lyrics=entry.lyrics,
            )
        )
    return issues
