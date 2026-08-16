"""video generate mode と CLI / script help の ownership 境界。"""

from __future__ import annotations

import re

from tests.helpers.paths import REPO_ROOT

SKILL_TEXT = (REPO_ROOT / ".claude" / "skills" / "video" / "references" / "generate.md").read_text(encoding="utf-8")


def _section(start: str, end: str) -> str:
    start_index = SKILL_TEXT.index(start)
    end_index = SKILL_TEXT.index(end, start_index)
    return SKILL_TEXT[start_index:end_index]


def _quick_reference_commands() -> list[str]:
    quick_reference = _section("## Quick Reference", "## Instructions")
    return re.findall(r"^\| `([^`]+)` \|", quick_reference, flags=re.MULTILINE)


def test_skill_keeps_one_representative_command_per_video_entrypoint() -> None:
    commands = _quick_reference_commands()

    assert sum(command.startswith("yt-generate-videos-batch") for command in commands) == 1
    assert sum("generate_videos.sh" in command for command in commands) == 1
    assert "`yt-generate-videos-batch --help`" in SKILL_TEXT
    assert "`generate_videos.sh --help`" in SKILL_TEXT


def test_skill_keeps_master_preview_full_generation_and_state_order() -> None:
    steps = _section("### ステップ", "### 自動検出される要素")

    master = steps.index("2. **マスター音源**")
    preview = steps.index("4. **プレビュー承認**", master)
    full_generation = steps.index("5. **動画生成**", preview)
    state_update = steps.index("6. **完成動画確認とworkflow-state.json更新**", full_generation)

    assert master < preview < full_generation < state_update


def test_skill_keeps_local_generation_and_state_safety_contracts() -> None:
    steps = _section("### ステップ", "### 自動検出される要素")

    assert "AskUserQuestion" not in steps
    assert "承認分岐" not in steps
    assert "全尺生成の成功後だけ" in steps
    assert "プレビューのみでは実行しない" in steps
    assert "master-video-review.md" in steps
    assert "assets.master_video" in steps


def test_skill_keeps_input_overlay_and_long_running_safety_contracts() -> None:
    steps = _section("### ステップ", "### 自動検出される要素")
    overlays = _section("## Overlays", "## 所要時間と完了報告")
    completion = _section("## 所要時間と完了報告", "## オーディオビジュアライザー")

    assert "固定名探索へ fallback せずエラー停止" in steps
    assert "config/channel/youtube.json::overlays" in overlays
    assert "generate_videos.sh" in overlays
    assert "ログ末尾" in completion
    assert "生成された `.mp4` のパス" in completion
