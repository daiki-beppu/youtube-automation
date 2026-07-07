"""Artifact-level verification for `yt-suno-verify`."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from youtube_automation.utils.preflight_checks import check_suno_genre_line_char_limit
from youtube_automation.utils.skill_config import load_skill_config
from youtube_automation.utils.suno_artifact_contracts import (
    DOCUMENTATION_DIRNAME,
    SUNO_LYRICS_JSON_FILENAME,
    SUNO_PATTERNS_FILENAME,
    SUNO_PROMPTS_JSON_FILENAME,
)
from youtube_automation.utils.suno_artifact_validation import (
    expected_instrumental_prompt_entries,
    instrumental_track_count_issue,
    name_set_mismatch_issues,
    unique_entry_names_issue,
    vocal_lyrics_structure_issues,
)
from youtube_automation.utils.suno_effective_config import ResolvedSunoConfig, resolve_suno_config
from youtube_automation.utils.suno_verify_readers import (
    ArtifactEntries,
    PatternContract,
    load_lyric_entries,
    load_pattern_contract,
    load_prompt_entries,
)

SUNO_VERIFY_SKILL_NAME = "suno"


def verify_suno_collection(collection_dir: Path) -> tuple[list[str], str]:
    docs_dir = collection_dir / DOCUMENTATION_DIRNAME
    patterns_path = docs_dir / SUNO_PATTERNS_FILENAME
    prompts_path = docs_dir / SUNO_PROMPTS_JSON_FILENAME
    lyrics_path = docs_dir / SUNO_LYRICS_JSON_FILENAME

    suno_cfg = resolve_suno_config(load_skill_config(SUNO_VERIFY_SKILL_NAME))
    issues = _preflight_issues(suno_cfg)
    contract, pattern_issues = load_pattern_contract(patterns_path, suno_cfg)
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


def _preflight_issues(suno_cfg: ResolvedSunoConfig) -> list[str]:
    genre_line_issue = check_suno_genre_line_char_limit({"genre_line": suno_cfg.genre_line})
    return [] if genre_line_issue is None else [genre_line_issue]


def _style_variant_genre_line_issues(suno_cfg: ResolvedSunoConfig, contract: PatternContract) -> list[str]:
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
        issue = check_suno_genre_line_char_limit({"genre_line": genre_line})
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

    tracks_per_pattern_text = "unknown"
    if contract.tracks_per_pattern is not None:
        tracks_per_pattern_text = str(contract.tracks_per_pattern)
    summary = (
        f"mode=vocal prompt_entries={len(prompts.names)} "
        f"tracks_per_pattern={tracks_per_pattern_text} expected_entries={len(contract.expected_names)}"
    )
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
