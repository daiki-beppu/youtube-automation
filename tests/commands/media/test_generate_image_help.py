"""``yt-generate-image --help`` の自己完結した入力契約。"""

import re
import sys

import pytest

from youtube_automation.commands.media import generate_image


def _help_text(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> str:
    monkeypatch.setattr(sys, "argv", ["yt-generate-image", "--help"])

    with pytest.raises(SystemExit) as exc_info:
        generate_image.main()

    assert exc_info.value.code == 0
    return " ".join(capsys.readouterr().out.split())


def test_help_explains_required_generation_inputs_and_costs_exception(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    help_text = _help_text(monkeypatch, capsys)

    assert "--prompt" in help_text
    assert "--output" in help_text
    assert "通常生成では必須" in help_text
    assert "--costs 単独実行時は不要" in help_text


def test_help_explains_reference_and_approval_semantics(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    help_text = _help_text(monkeypatch, capsys)

    assert "画像ごとに繰り返し指定可能" in help_text
    assert "コスト承認のみを省略" in help_text
    assert "既存出力は上書きせず -vN で自動採番" in help_text


def test_help_explains_reference_index_contract(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    help_text = _help_text(monkeypatch, capsys)

    assert "0-based index" in help_text
    assert "--reference 必須" in help_text
    assert "attempt ループを無効化" in help_text


def test_help_exposes_static_and_dynamic_defaults_without_false_choices(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    help_text = _help_text(monkeypatch, capsys)

    assert "アスペクト比 (デフォルト: 16:9)" in help_text
    assert "OpenAI は 16:9 または 9:16 のみ" in help_text
    assert "Gemini / gemini_cli は provider/config の対応範囲に従う" in help_text
    assert "未指定時は skill-config の provider 別 model" in help_text
    assert "未指定時は skill-config の image_generation.gemini.single_step.max_attempts" in help_text
    assert re.search(r"--aspect-ratio ASPECT_RATIO\b", help_text)
    assert re.search(r"--model MODEL\b", help_text)
    assert re.search(r"--reference-index REFERENCE_INDEX\b", help_text)
