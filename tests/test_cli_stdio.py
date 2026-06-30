"""CLI stdio bootstrap tests for Windows cp932 environments."""

from __future__ import annotations

import importlib
import io
import os
import sys
import tomllib
import types
from pathlib import Path

import pytest


def _cp932_stream() -> tuple[io.BytesIO, io.TextIOWrapper]:
    buffer = io.BytesIO()
    return buffer, io.TextIOWrapper(buffer, encoding="cp932", errors="strict")


def _drop_youtube_automation_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    for module_name in list(sys.modules):
        if module_name == "youtube_automation" or module_name.startswith("youtube_automation."):
            monkeypatch.delitem(sys.modules, module_name, raising=False)


def test_package_import_does_not_configure_stdio(monkeypatch):
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    _drop_youtube_automation_modules(monkeypatch)

    _, stdout = _cp932_stream()
    _, stderr = _cp932_stream()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    importlib.import_module("youtube_automation")

    assert "PYTHONUTF8" not in os.environ
    assert "PYTHONIOENCODING" not in os.environ
    assert sys.stdout.encoding.lower() == "cp932"
    assert sys.stderr.encoding.lower() == "cp932"


def test_cli_entrypoint_configures_utf8_stdout_and_stderr(monkeypatch):
    from youtube_automation.cli_entrypoints import _run

    stdout_buffer, stdout = _cp932_stream()
    stderr_buffer, stderr = _cp932_stream()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    module = types.ModuleType("dummy_cli_module")

    def main() -> None:
        print("日本語パス C:\\音楽\\作業 — 完了", file=sys.stdout)
        print("エラー詳細 — 続行", file=sys.stderr)
        sys.stdout.flush()
        sys.stderr.flush()

    module.main = main
    monkeypatch.setitem(sys.modules, module.__name__, module)

    assert _run(module.__name__) is None

    assert sys.stdout.encoding.lower().replace("_", "-") == "utf-8"
    assert sys.stderr.encoding.lower().replace("_", "-") == "utf-8"
    assert stdout_buffer.getvalue().decode("utf-8") == "日本語パス C:\\音楽\\作業 — 完了\n"
    assert stderr_buffer.getvalue().decode("utf-8") == "エラー詳細 — 続行\n"


def test_configure_utf8_stdio_reconfigures_cp932_stdout_and_stderr(monkeypatch):
    from youtube_automation.cli_stdio import configure_utf8_stdio

    stdout_buffer, stdout = _cp932_stream()
    stderr_buffer, stderr = _cp932_stream()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    configure_utf8_stdio()
    print("日本語パス C:\\音楽\\作業 — 完了", file=sys.stdout)
    print("エラー詳細 — 続行", file=sys.stderr)
    sys.stdout.flush()
    sys.stderr.flush()

    assert sys.stdout.encoding.lower().replace("_", "-") == "utf-8"
    assert sys.stderr.encoding.lower().replace("_", "-") == "utf-8"
    assert stdout_buffer.getvalue().decode("utf-8") == "日本語パス C:\\音楽\\作業 — 完了\n"
    assert stderr_buffer.getvalue().decode("utf-8") == "エラー詳細 — 続行\n"


def test_configure_utf8_stdio_sets_child_python_defaults(monkeypatch):
    from youtube_automation.cli_stdio import configure_utf8_stdio

    monkeypatch.delenv("PYTHONUTF8", raising=False)
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)

    configure_utf8_stdio()

    assert os.environ["PYTHONUTF8"] == "1"
    assert os.environ["PYTHONIOENCODING"] == "utf-8"


def test_configure_utf8_stdio_fails_fast_when_stdout_stays_non_utf8(monkeypatch):
    from youtube_automation.cli_stdio import configure_utf8_stdio

    class FailingStdout:
        encoding = "cp932"

        def reconfigure(self, *, encoding: str, errors: str) -> None:
            raise OSError("unsupported")

    monkeypatch.setattr(sys, "stdout", FailingStdout())

    with pytest.raises(RuntimeError, match="stdout"):
        configure_utf8_stdio()


def test_project_scripts_route_through_cli_entrypoint_wrappers():
    from youtube_automation import cli_entrypoints

    pyproject = tomllib.loads(Path("pyproject.toml").read_text())
    scripts = pyproject["project"]["scripts"]

    assert scripts
    for script_name, target in scripts.items():
        module_name, _, function_name = target.partition(":")
        assert script_name.startswith("yt-")
        assert module_name == "youtube_automation.cli_entrypoints"
        assert function_name
        assert hasattr(cli_entrypoints, function_name)
