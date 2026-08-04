"""yt-generate-image の codex provider 拒否契約テスト。"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from youtube_automation.commands.media import generate_image


def _run_with_codex_provider(monkeypatch, capsys):
    replace_model = MagicMock()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "yt-generate-image",
            "--prompt",
            "test prompt",
            "--output",
            "out.png",
            "--model",
            "override-model",
        ],
    )
    monkeypatch.setattr(
        generate_image,
        "load_image_generation_config",
        lambda: SimpleNamespace(provider="codex"),
    )
    monkeypatch.setattr(generate_image, "replace_model", replace_model)

    with pytest.raises(SystemExit) as exc_info:
        generate_image.main()

    return exc_info.value.code, capsys.readouterr(), replace_model


def test_generate_image_rejects_codex_before_model_override(monkeypatch, capsys) -> None:
    code, _captured, replace_model = _run_with_codex_provider(monkeypatch, capsys)

    assert code == 1
    replace_model.assert_not_called()


def test_generate_image_codex_error_mentions_script_route(monkeypatch, capsys) -> None:
    code, captured, _replace_model = _run_with_codex_provider(monkeypatch, capsys)

    assert code == 1
    assert "codex-image.sh" in captured.out
    assert "yt-generate-image" in captured.out
