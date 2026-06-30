"""Standard stream setup shared by ``yt-*`` console entry points."""

from __future__ import annotations

import os
import sys
from typing import Any


def configure_utf8_stdio() -> None:
    """Force predictable UTF-8 stdio for CLI output.

    Windows consoles may expose cp932 as ``sys.stdout.encoding``. Many ``yt-*``
    commands print Japanese text, emoji, and Unicode dashes, so leaving the
    encoding locale-dependent can crash with ``UnicodeEncodeError`` before the
    command finishes.
    """

    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    _reconfigure_stream(getattr(sys, "stdin", None), errors="surrogateescape")
    _reconfigure_stream(getattr(sys, "stdout", None), errors="backslashreplace")
    _reconfigure_stream(getattr(sys, "stderr", None), errors="backslashreplace")


def _reconfigure_stream(stream: Any, *, errors: str) -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if not callable(reconfigure):
        return

    try:
        reconfigure(encoding="utf-8", errors=errors)
    except (AttributeError, TypeError, ValueError, OSError):
        return
