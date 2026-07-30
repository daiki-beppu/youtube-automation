"""Console entrypoint の共通 channel 引数境界テスト。"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from youtube_automation import entrypoints
from youtube_automation.infrastructure.errors import ConfigError


def test_consume_channel_rejects_missing_value_without_mutating_argv() -> None:
    argv = ["yt-command", "--dry-run", "--channel"]

    with pytest.raises(ConfigError, match="channel slug が必要"):
        entrypoints._consume_channel_option(argv)

    assert argv == ["yt-command", "--dry-run", "--channel"]


def test_consume_channel_rejects_empty_equals_value() -> None:
    argv = ["yt-command", "--channel="]

    with pytest.raises(ConfigError, match="空でない channel slug"):
        entrypoints._consume_channel_option(argv)

    assert argv == ["yt-command"]


def test_consume_channel_rejects_duplicates_after_consuming_options() -> None:
    argv = ["yt-command", "--channel", "alpha", "--channel=beta", "--dry-run"]

    with pytest.raises(ConfigError, match="複数回指定"):
        entrypoints._consume_channel_option(argv)

    assert argv == ["yt-command", "--dry-run"]


def test_consume_channel_accepts_equals_form_and_removes_only_that_option() -> None:
    argv = ["yt-command", "--channel=alpha", "--dry-run"]

    assert entrypoints._consume_channel_option(argv) == "alpha"
    assert argv == ["yt-command", "--dry-run"]


def test_consume_channel_stops_at_double_dash_and_preserves_tail() -> None:
    argv = ["yt-command", "--dry-run", "--", "--channel", "target-value"]

    assert entrypoints._consume_channel_option(argv) is None
    assert argv == ["yt-command", "--dry-run", "--", "--channel", "target-value"]


def test_run_rejects_non_callable_module_attribute(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["yt-command"])
    monkeypatch.setattr(entrypoints, "configure_utf8_stdio", lambda: None)
    monkeypatch.setattr(entrypoints, "import_module", lambda _path: SimpleNamespace(main=42))

    with pytest.raises(TypeError, match="dummy.module:main is not callable"):
        entrypoints._run("dummy.module")
