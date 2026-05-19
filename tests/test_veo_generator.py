"""utils.veo_generator の単体テスト。

Issue #186: `trim_tail` / `smooth_loop` の duration 取得 argv に `"--"` sentinel
リグレッションガード。
Issue #358: `build_structured_prompt` のプロンプト構築検証。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from youtube_automation.utils import veo_generator
from youtube_automation.utils.veo_generator import build_structured_prompt


def _install_capture(monkeypatch) -> dict:
    """`subprocess.check_output` を fake 化し、cmd を捕捉して即座に
    `ValueError` を発生させる。`trim_tail` / `smooth_loop` は
    `Exception` 全般を catch して `False` を返すため、これで
    argv 検証だけに絞った最小テストになる。
    """
    captured: dict = {}

    def fake_check_output(cmd, **kwargs):
        captured["cmd"] = cmd
        # float() で ValueError を発生させ、関数を早期 False で抜けさせる。
        return "not-a-number"

    monkeypatch.setattr(veo_generator.subprocess, "check_output", fake_check_output)
    return captured


# ---------- trim_tail ----------


def test_trim_tail_places_sentinel_before_path(monkeypatch) -> None:
    captured = _install_capture(monkeypatch)

    veo_generator.trim_tail(Path("/fake.mp4"))

    assert captured["cmd"][-2] == "--"
    assert captured["cmd"][-1] == "/fake.mp4"


def test_trim_tail_keeps_sentinel_for_dash_prefixed_path(monkeypatch) -> None:
    captured = _install_capture(monkeypatch)

    veo_generator.trim_tail(Path("-evil.mp4"))

    assert captured["cmd"][-2] == "--"
    assert captured["cmd"][-1] == "-evil.mp4"


# ---------- smooth_loop ----------


def test_smooth_loop_places_sentinel_before_path(monkeypatch) -> None:
    captured = _install_capture(monkeypatch)

    veo_generator.smooth_loop(Path("/fake.mp4"))

    assert captured["cmd"][-2] == "--"
    assert captured["cmd"][-1] == "/fake.mp4"


def test_smooth_loop_keeps_sentinel_for_dash_prefixed_path(monkeypatch) -> None:
    captured = _install_capture(monkeypatch)

    veo_generator.smooth_loop(Path("-evil.mp4"))

    assert captured["cmd"][-2] == "--"
    assert captured["cmd"][-1] == "-evil.mp4"


# ---------- build_structured_prompt (Issue #358) ----------

_TEMPLATE = (
    "Static composition. The scene is a living painting: {static_clause} remain exactly as in the source image. "
    "The only motion is {motion_clause} — subtle, gentle. {base_rules} Loop seamlessly."
)
_BASE_RULES = "Preserve the original lighting."


class TestBuildStructuredPrompt:
    def test_expands_both_motion_and_static(self) -> None:
        prompt = build_structured_prompt(
            motion_targets=["slow leaves swaying", "subtle steam"],
            static_targets=["the character", "two animals (count remains 2)"],
            template=_TEMPLATE,
            base_rules=_BASE_RULES,
        )
        assert "slow leaves swaying and subtle steam" in prompt
        assert "the character and two animals (count remains 2)" in prompt
        assert "Preserve the original lighting." in prompt
        assert "{motion_clause}" not in prompt
        assert "{static_clause}" not in prompt
        assert "{base_rules}" not in prompt

    def test_oxford_comma_for_three_or_more_motion_items(self) -> None:
        prompt = build_structured_prompt(
            motion_targets=["leaves", "steam", "candle flicker"],
            static_targets=["character"],
            template=_TEMPLATE,
            base_rules="",
        )
        assert "leaves, steam, and candle flicker" in prompt

    def test_single_item_renders_without_conjunction(self) -> None:
        prompt = build_structured_prompt(
            motion_targets=["slow leaves swaying"],
            static_targets=["character"],
            template=_TEMPLATE,
            base_rules="",
        )
        assert "The only motion is slow leaves swaying" in prompt
        assert " and slow leaves" not in prompt

    def test_empty_static_falls_back_to_rest_of_scene(self) -> None:
        prompt = build_structured_prompt(
            motion_targets=["leaves"],
            static_targets=[],
            template=_TEMPLATE,
            base_rules="",
        )
        assert "the rest of the scene remain exactly as in the source image" in prompt

    def test_empty_motion_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="motion_targets"):
            build_structured_prompt(
                motion_targets=[],
                static_targets=["character"],
                template=_TEMPLATE,
                base_rules="",
            )

    def test_whitespace_only_motion_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="motion_targets"):
            build_structured_prompt(
                motion_targets=["", "  ", "\t"],
                static_targets=["character"],
                template=_TEMPLATE,
                base_rules="",
            )

    def test_strips_and_filters_empty_items(self) -> None:
        prompt = build_structured_prompt(
            motion_targets=["  leaves  ", "", "  steam"],
            static_targets=["  character  ", "  "],
            template=_TEMPLATE,
            base_rules="",
        )
        assert "leaves and steam" in prompt
        # static_targets は strip 後にそのまま join される（自動冠詞補完なし）
        assert "character remain exactly as in the source image" in prompt

    def test_empty_base_rules_renders_cleanly(self) -> None:
        prompt = build_structured_prompt(
            motion_targets=["leaves"],
            static_targets=["character"],
            template=_TEMPLATE,
            base_rules="",
        )
        assert "{base_rules}" not in prompt
        # base_rules 空時に連続スペースが残らない (re.sub で正規化)
        assert "  " not in prompt

    def test_template_with_brace_in_english_text_is_safe(self) -> None:
        # Veo 英文に {curly} を含めても .format() ではなく .replace() なので壊れない
        template = (
            "Style: {motion_clause}; static: {static_clause}; rules: {base_rules}; note: this is { not a placeholder }."
        )
        prompt = build_structured_prompt(
            motion_targets=["leaves"],
            static_targets=["character"],
            template=template,
            base_rules="",
        )
        assert "{ not a placeholder }" in prompt
