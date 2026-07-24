"""Remove sensitive values from authentication diagnostics."""

import os
import re

_TOKEN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ya29\.[\w\-]+"),
    re.compile(r"1//[\w\-]+"),
    re.compile(r"[\w\-]{20,}\.[\w\-]{20,}\.[\w\-]{20,}"),
)
_SENSITIVE_FIELD_RE = re.compile(
    r"""(?ix)(["']?\b(?:refresh_token|access_token|client_secret|id_token|password|api_key|authorization|token)\b["']?\s*[:=]\s*)("[^"]*"|'[^']*'|(?:Bearer\s+)?[^\s,&}]+)"""
)
_OSERRNO_PATH_RE = re.compile(r": '([^']+)'")
_ABSOLUTE_PATH_RE = re.compile(r"(?<![\w:])/(?:[^/\s]+/)+[^/\s]+")
_REDACTED_TOKEN = "<redacted-token>"
_REDACTED_PATH = "<redacted-path>"


def _replace_sensitive_field(match: re.Match[str]) -> str:
    value = match.group(2)
    if value[:1] in {'"', "'"}:
        return f"{match.group(1)}{value[0]}{_REDACTED_TOKEN}{value[0]}"
    return f"{match.group(1)}{_REDACTED_TOKEN}"


def redact_sensitive_data(message: str, *paths: object) -> str:
    redacted = _OSERRNO_PATH_RE.sub(f": '{_REDACTED_PATH}'", message)
    redacted = _ABSOLUTE_PATH_RE.sub(_REDACTED_PATH, redacted)
    for path in paths:
        redacted = redacted.replace(os.fspath(path), _REDACTED_PATH)
    redacted = _SENSITIVE_FIELD_RE.sub(_replace_sensitive_field, redacted)
    for pattern in _TOKEN_PATTERNS:
        redacted = pattern.sub(_REDACTED_TOKEN, redacted)
    return redacted
