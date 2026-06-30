"""CLI stdio bootstrap tests for Windows cp932 environments."""

from __future__ import annotations

import io
import os
import sys

from youtube_automation.cli_stdio import configure_utf8_stdio


def test_configure_utf8_stdio_reconfigures_cp932_stdout(monkeypatch):
    buffer = io.BytesIO()
    stdout = io.TextIOWrapper(buffer, encoding="cp932", errors="strict")
    monkeypatch.setattr(sys, "stdout", stdout)

    configure_utf8_stdio()
    print("日本語パス C:\\音楽\\作業 — 完了", file=sys.stdout)
    sys.stdout.flush()

    assert sys.stdout.encoding.lower().replace("_", "-") == "utf-8"
    assert buffer.getvalue().decode("utf-8") == "日本語パス C:\\音楽\\作業 — 完了\n"


def test_configure_utf8_stdio_sets_child_python_defaults(monkeypatch):
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)

    configure_utf8_stdio()

    assert os.environ["PYTHONUTF8"] == "1"
    assert os.environ["PYTHONIOENCODING"] == "utf-8"
