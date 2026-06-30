"""Standard stream setup shared by ``yt-*`` console entry points."""

from __future__ import annotations

import os
import sys


def configure_utf8_stdio() -> None:
    """Force predictable UTF-8 stdio for CLI output.

    Windows consoles may expose cp932 as ``sys.stdout.encoding``. Many ``yt-*``
    commands print Japanese text, emoji, and Unicode dashes, so leaving the
    encoding locale-dependent can crash with ``UnicodeEncodeError`` before the
    command finishes.
    """

    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    _reconfigure_stream(getattr(sys, "stdin", None), errors="surrogateescape", stream_name="stdin")
    _reconfigure_stream(
        getattr(sys, "stdout", None),
        errors="backslashreplace",
        stream_name="stdout",
        required=True,
    )
    _reconfigure_stream(
        getattr(sys, "stderr", None),
        errors="backslashreplace",
        stream_name="stderr",
        required=True,
    )


def _reconfigure_stream(
    stream: object | None,
    *,
    errors: str,
    stream_name: str,
    required: bool = False,
) -> bool:
    reconfigure = getattr(stream, "reconfigure", None)
    if not callable(reconfigure):
        if required and _has_non_utf8_encoding(stream):
            raise RuntimeError(f"failed to configure {stream_name} for utf-8")
        return False

    try:
        reconfigure(encoding="utf-8", errors=errors)
    except (AttributeError, TypeError, ValueError, OSError) as exc:
        if required:
            raise RuntimeError(f"failed to configure {stream_name} for utf-8") from exc
        return False

    return True


def _has_non_utf8_encoding(stream: object | None) -> bool:
    encoding = getattr(stream, "encoding", None)
    if not isinstance(encoding, str):
        return False
    return encoding.lower().replace("_", "-") != "utf-8"
