"""Console entrypoint の共通 channel 引数境界テスト。"""

from __future__ import annotations

import sys
from collections.abc import Callable
from types import SimpleNamespace

import pytest

from youtube_automation import entrypoints
from youtube_automation.commands._shared.arguments import CompetitorArgumentParser


def test_run_rejects_non_callable_module_attribute(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["yt-command"])
    monkeypatch.setattr(entrypoints, "configure_utf8_stdio", lambda: None)
    monkeypatch.setattr(entrypoints, "import_module", lambda _path: SimpleNamespace(main=42))

    with pytest.raises(TypeError, match="dummy.module:main is not callable"):
        entrypoints._run("dummy.module")


@pytest.mark.parametrize(
    "cli_entrypoint",
    [
        pytest.param(entrypoints.yt_benchmark_comments, id="benchmark-comments"),
        pytest.param(entrypoints.yt_thumbnail_compare, id="thumbnail-compare"),
    ],
)
def test_competitor_cli_rejects_channel_without_selecting_self_channel(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    cli_entrypoint: Callable[[], object],
) -> None:
    parser = CompetitorArgumentParser()
    monkeypatch.setattr(sys, "argv", ["yt-command", "--channel", "competitor-x"])
    monkeypatch.setattr(entrypoints, "configure_utf8_stdio", lambda: None)
    monkeypatch.setattr(
        entrypoints,
        "import_module",
        lambda _path: SimpleNamespace(main=lambda: parser.parse_args()),
    )

    with pytest.raises(SystemExit, match="2"):
        cli_entrypoint()

    assert "--channel は --competitor に変わりました" in capsys.readouterr().err
