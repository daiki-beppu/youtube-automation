"""Readers for Suno verify artifact inputs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml

from youtube_automation.utils.suno_artifact_contracts import (
    SUNO_LYRICS_JSON_FILENAME,
    SUNO_PATTERNS_FILENAME,
    SUNO_PROMPTS_JSON_FILENAME,
)
from youtube_automation.utils.suno_artifact_validation import (
    duplicated_names,
    positive_integer_issue,
    suno_prompt_entry_names,
    surrounding_whitespace_issue,
    unique_entry_names_issue,
)
from youtube_automation.utils.suno_effective_config import ResolvedSunoConfig, infer_suno_mode

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
    suno_cfg: ResolvedSunoConfig,
) -> tuple[PatternContract | None, list[str]]:
    raw, issues = _load_yaml_mapping(patterns_path, SUNO_PATTERNS_FILENAME)
    if raw is None:
        return None, issues

    mode, mode_issues = _resolve_mode(raw, suno_cfg)
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


def _resolve_mode(raw: Mapping[str, object], suno_cfg: ResolvedSunoConfig) -> tuple[str | None, list[str]]:
    raw_mode = raw.get("mode")
    if raw_mode is None:
        return infer_suno_mode(suno_cfg.genre_line), []
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
    suno_cfg: ResolvedSunoConfig,
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
