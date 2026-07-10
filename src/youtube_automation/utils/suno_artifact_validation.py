"""Shared validation helpers for Suno prompt and lyric artifacts."""

from __future__ import annotations

import math
import re
from pathlib import Path

from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.suno_artifact_contracts import SUNO_LYRICS_JSON_FILENAME

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
    take_index: int | None = None,
) -> str:
    base_name = f"{name_jp} — {name_en}"
    if variation_index is not None:
        base_name = f"{base_name} (Variation {variation_index})"
    if take_index is not None:
        base_name = f"{base_name} (Take {take_index})"
    return base_name


def suno_prompt_entry_names(
    name_jp: str,
    name_en: str,
    scenes_count: int,
    *,
    tracks_per_pattern: int = 1,
) -> list[str]:
    scene_names = _scene_entry_names(name_jp, name_en, scenes_count)
    if tracks_per_pattern == 1:
        return scene_names
    return [
        suno_prompt_entry_name(
            name_jp,
            name_en,
            variation_index=variation_index,
            take_index=take_index,
        )
        for variation_index in _variation_indexes(scenes_count)
        for take_index in range(1, tracks_per_pattern + 1)
    ]


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
