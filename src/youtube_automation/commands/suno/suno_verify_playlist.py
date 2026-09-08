#!/usr/bin/env python3
"""CLI wrapper for playlist × suno-prompts.json consistency gate before masterup."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from youtube_automation.commands._shared.arguments import add_optional_collection_argument
from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.collections.paths import resolve_collection_dir
from youtube_automation.domains.suno.downloaded.archive import (
    _AUDIO_EXTENSIONS,
    _CANONICAL_MUSIC_FILENAME_RE,
    _sanitize_output_stem,
    canonicalize_noncanonical_music_files,
)
from youtube_automation.domains.suno.name_matching import (
    normalize_suno_name_for_lookup,
    suno_name_lookup_candidates,
)
from youtube_automation.domains.suno.playlist import (
    format_verification_report,
    iter_entry_titles,
    load_entry_names,
    normalize_title,
    verify_playlist_titles,
)
from youtube_automation.domains.suno.prompts import read_suno_prompt_entries

_TITLE_SOURCE_ERROR = (
    "playlist 曲名の入力元は --titles / --titles-file / --music-dir / stdin のいずれか 1 つにしてください"
)


@dataclass(frozen=True)
class SunoPromptTitleIdentity:
    canonical_title: str
    aliases: tuple[str, ...]


def _suno_title_aliases(value: str) -> tuple[str, ...]:
    aliases: list[str] = []
    for candidate in suno_name_lookup_candidates(value):
        try:
            sanitized = _sanitize_output_stem(candidate)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        if sanitized and sanitized not in aliases:
            aliases.append(sanitized)
    return tuple(aliases)


def _load_entry_title_identities(collection_dir: Path) -> list[SunoPromptTitleIdentity]:
    identities: list[SunoPromptTitleIdentity] = []
    for name, canonical_title in iter_entry_titles(collection_dir):
        aliases: list[str] = []
        for source in (name, canonical_title):
            for alias in _suno_title_aliases(source):
                if alias not in aliases:
                    aliases.append(alias)
        identities.append(SunoPromptTitleIdentity(canonical_title.strip(), tuple(aliases)))
    return identities


def _build_music_dir_title_lookups(
    identities: list[SunoPromptTitleIdentity],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Map ZIP extraction output stems back to their canonical prompt titles."""
    exact_lookup: dict[str, set[str]] = {}
    normalized_lookup: dict[str, set[str]] = {}
    for identity in identities:
        for alias in identity.aliases:
            exact_lookup.setdefault(alias, set()).add(identity.canonical_title)
            normalized_lookup.setdefault(normalize_suno_name_for_lookup(alias), set()).add(identity.canonical_title)
    return exact_lookup, normalized_lookup


def _music_file_identity(
    audio_path: Path,
    identities: list[SunoPromptTitleIdentity],
    exact_title_lookup: dict[str, set[str]],
    normalized_title_lookup: dict[str, set[str]],
) -> tuple[str, str] | None:
    """Resolve the indexed prompt title and variant, rejecting ambiguous aliases."""
    match = _CANONICAL_MUSIC_FILENAME_RE.fullmatch(audio_path.stem)
    if match is None:
        return None
    entry_index = int(match.group("index"))
    title = match.group("title")
    if entry_index < 1 or entry_index > len(identities):
        return None
    indexed_title = identities[entry_index - 1].canonical_title
    canonical_titles = exact_title_lookup.get(title)
    if canonical_titles is None:
        canonical_titles = normalized_title_lookup.get(normalize_suno_name_for_lookup(title), set())
        if len(canonical_titles) > 1:
            matches = ", ".join(sorted(canonical_titles))
            raise ValidationError(f"ambiguous Suno name {title!r}: matches {matches}")
    canonical_title = indexed_title if indexed_title in canonical_titles else None
    if canonical_title is None:
        return None
    return canonical_title, match.group("variant")


def _read_music_dir_titles(
    music_dir: str,
    collection_dir: Path,
    identities: list[SunoPromptTitleIdentity],
) -> list[str]:
    path = Path(music_dir)
    if not path.is_absolute():
        path = collection_dir / path
    if not path.is_dir():
        raise ValidationError(f"--music-dir が見つかりません: {path}")
    try:
        renamed = canonicalize_noncanonical_music_files(
            collection_dir, path, prompt_entries_reader=read_suno_prompt_entries
        )
    except (OSError, ValueError) as exc:
        raise ValidationError(str(exc)) from exc
    for old_name, new_name in renamed:
        print(f"RENAMED: {old_name} -> {new_name}", file=sys.stderr)
    titles: list[str] = []
    seen_variants: set[tuple[str, str]] = set()
    exact_title_lookup, normalized_title_lookup = _build_music_dir_title_lookups(identities)
    for audio_path in sorted(path.iterdir()):
        if not audio_path.is_file() or audio_path.suffix.lower() not in _AUDIO_EXTENSIONS:
            continue
        identity = _music_file_identity(audio_path, identities, exact_title_lookup, normalized_title_lookup)
        if identity is None:
            titles.append(audio_path.name)
            continue
        canonical_title, variant = identity
        variant_key = (normalize_title(canonical_title), variant)
        if variant_key not in seen_variants:
            titles.append(canonical_title)
            seen_variants.add(variant_key)
    if not titles:
        raise ValidationError(f"--music-dir に音声ファイルがありません: {path}")
    return titles


def _validate_title_sources(args: argparse.Namespace) -> None:
    """Reject conflicting explicit inputs before reading the selected source."""
    explicit_sources = [name for name in ("titles_file", "music_dir") if getattr(args, name)]
    if args.titles or (args.music_dir and args.titles is not None):
        explicit_sources.append("titles")
    if len(explicit_sources) > 1:
        raise ValidationError(_TITLE_SOURCE_ERROR)

    if args.music_dir and not sys.stdin.isatty():
        stdin_titles = _nonblank_titles(sys.stdin.read().splitlines())
        if stdin_titles:
            raise ValidationError(_TITLE_SOURCE_ERROR)


def _nonblank_titles(titles: Iterable[str]) -> list[str]:
    """Exclude blank titles without trimming or reordering the supplied names."""
    return [title for title in titles if title.strip()]


def _read_titles_file(path: Path) -> list[str]:
    """Read a JSON array or one-title-per-line text, preserving nonblank titles."""
    if not path.is_file():
        raise ValidationError(f"--titles-file が見つかりません: {path}")
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(raw)
        if not isinstance(data, list) or not all(isinstance(t, str) for t in data):
            raise ValidationError("--titles-file (JSON) は文字列の配列にしてください")
        return _nonblank_titles(data)
    return _nonblank_titles(raw.splitlines())


def _read_titles(
    args: argparse.Namespace,
    collection_dir: Path,
    identities: list[SunoPromptTitleIdentity],
) -> list[str]:
    _validate_title_sources(args)

    if args.titles is not None:
        titles = _nonblank_titles(args.titles)
        if not titles:
            raise ValidationError("--titles には 1 件以上の曲名を指定してください")
        return titles
    if args.titles_file:
        return _read_titles_file(Path(args.titles_file))
    if args.music_dir:
        return _read_music_dir_titles(args.music_dir, collection_dir, identities)
    if not sys.stdin.isatty():
        titles = _nonblank_titles(sys.stdin.read().splitlines())
        if titles:
            return titles
    raise ValidationError("playlist 曲名を --titles / --titles-file / --music-dir / stdin のいずれかで渡してください")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Suno playlist の曲名一覧を suno-prompts.json の entry title/name と突合し、"
            "混入（unknown）と未生成（missing）を fail-loud で検出する"
        )
    )
    add_optional_collection_argument(parser)
    parser.add_argument("--titles", nargs="*", help="playlist の曲名（複数指定）")
    parser.add_argument("--titles-file", help="曲名リストのファイル（1行1曲、または JSON 配列）")
    parser.add_argument(
        "--music-dir",
        help=(
            "数字2桁以上{a|b}-<title>.<ext> 形式の音声ファイルがあるディレクトリ（相対パスは collection 基準）。"
            "非正準形ファイルは suno-prompts.json と照合して正準形へ自動リネームしてから突合する"
        ),
    )
    parser.add_argument(
        "--expected-clips-per-entry",
        type=int,
        default=2,
        help="entry あたりの期待 clip 数（既定 2、0 で不足チェック無効）",
    )
    parser.add_argument("--json", action="store_true", help="結果を JSON で出力する")
    args = parser.parse_args()

    try:
        if args.expected_clips_per_entry < 0:
            raise ValidationError("--expected-clips-per-entry は 0 以上にしてください")
        collection_dir = resolve_collection_dir(args.collection)
        if args.music_dir:
            identities = _load_entry_title_identities(collection_dir)
            entry_names = [identity.canonical_title for identity in identities]
        else:
            identities = []
            entry_names = load_entry_names(collection_dir)
        titles = _read_titles(args, collection_dir, identities)
        result = verify_playlist_titles(
            entry_names,
            titles,
            expected_clips_per_entry=args.expected_clips_per_entry,
        )
    except (ValidationError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(
            json.dumps(
                {
                    "ok": result.ok,
                    "matched": dict(result.matched),
                    "unknown_titles": list(result.unknown_titles),
                    "missing_entries": list(result.missing_entries),
                    "underfilled_entries": list(result.underfilled_entries),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(format_verification_report(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
