"""Origin policy shared by loopback local servers."""

from __future__ import annotations

EXTENSION_ORIGIN_SCHEME = "chrome-extension://"
DEFAULT_ALLOWED_WEB_ORIGINS = frozenset(
    {
        "https://suno.com",
        "https://www.suno.com",
        "https://distrokid.com",
        "https://www.distrokid.com",
    }
)


def is_origin_allowed(origin: str | None, allow_origin: str | None) -> bool:
    """Apply the default helper-site policy or an exact explicit origin lock."""
    if not origin:
        return False
    if allow_origin is not None:
        return origin == allow_origin
    if origin.startswith(EXTENSION_ORIGIN_SCHEME):
        return True
    return origin in DEFAULT_ALLOWED_WEB_ORIGINS


def is_read_origin_allowed(origin: str | None, allow_origin: str | None, _path: str) -> bool:
    """Apply the same exact-lock policy to read-only endpoints."""
    return is_origin_allowed(origin, allow_origin)
