"""Suno prompt names and downloaded filenames share this matching policy."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Hashable, Iterable
from dataclasses import dataclass
from typing import TypeVar

_SUNO_TRACK_PREFIX_RE = re.compile(r"^Track\s+\d+\s+(.+)$", re.IGNORECASE)
_SUNO_STUDIO_TRACK_PREFIX_RE = re.compile(r"^(?P<track_number>\d+)\s+(?P<title>.+)$")
_LATIN_TITLE_TAIL_RE = re.compile(r"([A-Za-z][A-Za-z0-9 &'(),.!?:/-]*)$")
_DUP_SUFFIX_RE = re.compile(r"^(?P<base>.+?)(?:\s*\((?P<paren>\d+)\)|_(?P<underscore>\d+))$")

_Identifier = TypeVar("_Identifier", bound=Hashable)


class AmbiguousSunoNameError(ValueError):
    """A filename resolves to more than one prompt after normalization."""


def normalize_suno_name_for_lookup(value: str) -> str:
    """Build a case-insensitive key from Unicode letters, marks, and numbers.

    Suno can remove punctuation while leaving or inserting whitespace in archive
    filenames.  NFKC first aligns compatibility forms; retaining only semantic
    letter/mark/number characters then gives every punctuation, symbol, and
    whitespace character one policy instead of maintaining a character list.
    """
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(char for char in normalized if unicodedata.category(char)[0] in {"L", "M", "N"})


def suno_name_lookup_candidates(name: str) -> tuple[str, ...]:
    """Return full and derived aliases in most-specific-first order.

    Both prompt names and downloaded filename stems flow through here, so this
    only strips conventions that never occur inside a real song title.  Filename
    conventions that a title could legitimately start with belong to
    :func:`suno_filename_lookup_candidates`.
    """
    stripped_name = name.strip()
    prefix_match = _SUNO_TRACK_PREFIX_RE.match(stripped_name)
    base = prefix_match.group(1).strip() if prefix_match is not None else stripped_name
    candidates = [base]
    dash_positions = [index for index, char in enumerate(base) if unicodedata.category(char) == "Pd"]
    candidates.extend(base[index + 1 :].strip() for index in dash_positions)
    tail_match = _LATIN_TITLE_TAIL_RE.search(base)
    if tail_match is not None:
        candidates.append(tail_match.group(1).strip())
    return tuple(dict.fromkeys(candidate for candidate in candidates if candidate))


def suno_filename_lookup_candidates(stem: str) -> tuple[str, ...]:
    """Return lookup candidates for a downloaded audio filename stem.

    Studio Multitrack members carry a ``<track number> `` prefix that is not part
    of the prompt name.  The unstripped stem stays first so a title that itself
    begins with a number (``3 AM``) keeps matching its own entry, and the
    stripped aliases only act as a fallback.
    """
    stem_candidates = suno_name_lookup_candidates(stem)
    base, track_number = split_suno_studio_track_prefix(stem)
    if track_number is None:
        return stem_candidates

    base_candidates = suno_name_lookup_candidates(base)
    candidates = [stem_candidates[0], *base_candidates, *stem_candidates[1:]]
    return tuple(dict.fromkeys(candidate for candidate in candidates if candidate))


def split_suno_studio_track_prefix(stem: str) -> tuple[str, int | None]:
    """Split a filename stem's Studio Multitrack ``<track number> <title>`` prefix.

    Only ever call this on filename stems: prompt names may legitimately start
    with ``<number> `` and must keep their prefix.
    """
    stripped_stem = stem.strip()
    match = _SUNO_STUDIO_TRACK_PREFIX_RE.match(stripped_stem)
    if match is None:
        return stripped_stem, None
    return match.group("title").strip(), int(match.group("track_number"))


def split_suno_duplicate_stem(stem: str) -> tuple[str, int]:
    """Split Suno's ``Title_1`` / browser ``Title (1)`` duplicate suffix."""
    match = _DUP_SUFFIX_RE.fullmatch(stem.strip())
    if match is None:
        return stem.strip(), 0
    duplicate_number = int(match.group("paren") or match.group("underscore"))
    return match.group("base"), duplicate_number


@dataclass(frozen=True, slots=True)
class SunoNameIndex:
    """Resolve exact aliases and accept only unique normalized matches."""

    exact: dict[str, _Identifier]
    normalized: dict[str, frozenset[_Identifier]]

    @classmethod
    def build(
        cls,
        alias_groups: Iterable[tuple[_Identifier, Iterable[str]]],
    ) -> SunoNameIndex:
        exact: dict[str, _Identifier] = {}
        normalized: dict[str, set[_Identifier]] = {}
        for identifier, aliases in alias_groups:
            for alias in aliases:
                if not alias:
                    continue
                exact[alias] = identifier
                key = normalize_suno_name_for_lookup(alias)
                if key:
                    normalized.setdefault(key, set()).add(identifier)
        return cls(
            exact=exact,
            normalized={key: frozenset(values) for key, values in normalized.items()},
        )

    def __bool__(self) -> bool:
        return bool(self.exact)

    def resolve(self, candidates: Iterable[str]) -> _Identifier | None:
        resolved = self.resolve_with_candidate(candidates)
        return None if resolved is None else resolved[0]

    def resolve_with_candidate(
        self,
        candidates: Iterable[str],
    ) -> tuple[_Identifier, str] | None:
        ordered = tuple(dict.fromkeys(candidate for candidate in candidates if candidate))
        if not ordered:
            return None

        full_name = ordered[0]
        exact_full = self.exact.get(full_name)
        if exact_full is not None:
            return exact_full, full_name
        if not _has_non_latin_letters(full_name):
            normalized_full = self._normalized_match(full_name)
            if normalized_full is not None:
                return normalized_full, full_name
        for candidate in ordered[1:]:
            exact_alias = self.exact.get(candidate)
            if exact_alias is not None:
                return exact_alias, candidate
        normalized_full = self._normalized_match(full_name)
        if normalized_full is not None:
            return normalized_full, full_name
        for candidate in ordered[1:]:
            normalized_alias = self._normalized_match(candidate)
            if normalized_alias is not None:
                return normalized_alias, candidate
        return None

    def _normalized_match(self, candidate: str) -> _Identifier | None:
        key = normalize_suno_name_for_lookup(candidate)
        return self._unique_match(candidate, self.normalized.get(key))

    @staticmethod
    def _unique_match(
        candidate: str,
        matches: frozenset[_Identifier] | None,
    ) -> _Identifier | None:
        if not matches:
            return None
        if len(matches) > 1:
            identifiers = ", ".join(str(identifier) for identifier in sorted(matches, key=str))
            raise AmbiguousSunoNameError(f"ambiguous Suno name {candidate!r}: matches {identifiers}")
        return next(iter(matches))


def _has_non_latin_letters(value: str) -> bool:
    return any(
        unicodedata.category(char).startswith("L") and "LATIN" not in unicodedata.name(char, "") for char in value
    )
