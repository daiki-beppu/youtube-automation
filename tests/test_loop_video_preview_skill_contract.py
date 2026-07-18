"""`/loop-video` の確認・プレビュー承認ゲート契約を検証する。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / ".claude" / "skills" / "loop-video" / "SKILL.md"


def _read() -> str:
    return SKILL.read_text(encoding="utf-8")


def test_preview_approval_gate_is_declared_near_the_top() -> None:
    first_60_lines = "\n".join(_read().splitlines()[:60])

    assert "## 確認・プレビュー承認ゲート" in first_60_lines
    assert "承認されるまで `/videoup`" in first_60_lines
    assert "静止画やキーフレームだけ" in first_60_lines


def test_preview_opens_the_generated_video_and_requires_two_choice_approval() -> None:
    text = _read()

    assert 'open "$LOOP_VIDEO_PATH"' in text
    assert "動画として再生できるプレビュー" in text
    assert "AskUserQuestion" in text
    assert "承認する" in text
    assert "受理せず修正する" in text


def test_rejected_or_repaired_video_cannot_bypass_preview_gate() -> None:
    text = _read()

    assert "受理しない場合" in text
    assert "`--smooth`" in text
    assert "Veo 再生成" in text
    assert "[改善しました]" in text
    assert "再び同じ動画プレビューを開く" in text
    assert "生成・リトライ・`--smooth`" in text


def test_preview_checklist_exposes_static_fallback_and_loop_seam() -> None:
    text = _read()

    assert "時間経過で被写体または背景が実際に動く" in text
    assert "静止画 fallback" in text
    assert "ループの継ぎ目" in text
