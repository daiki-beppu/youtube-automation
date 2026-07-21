"""ライブチャットの機械フィルタ."""

from __future__ import annotations

import re

_JAPANESE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
_LATIN = re.compile(r"[A-Za-z]")


def detected_language(text: str) -> str | None:
    if _JAPANESE.search(text):
        return "ja"
    if _LATIN.search(text):
        return "en"
    return None


def audit_text(text: str, *, expected_language: str | None, ng_words: list[str], max_length: int) -> str | None:
    value = text.strip()
    if not value or len(value) > max_length:
        return "empty_or_too_long"
    lowered = value.casefold()
    if any(word and word.casefold() in lowered for word in ng_words):
        return "ng_word"
    actual = detected_language(value)
    normalized = (expected_language or "").lower().split("-")[0]
    if normalized in {"ja", "en"} and actual is not None and actual != normalized:
        return "language_mismatch"
    return None
