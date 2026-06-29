"""Skill / repository docs consistency checks for #1173-#1180."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_workflow_schema_reference_points_to_existing_wf_new_schema() -> None:
    """wf-next / wf-status must not point to the removed shared schema path."""
    schema_path = ".claude/skills/wf-new/references/schema.md"
    assert (REPO_ROOT / schema_path).is_file()

    for path in (".claude/skills/wf-next/SKILL.md", ".claude/skills/wf-status/SKILL.md"):
        text = _read(path)
        assert ".claude/references/workflow/schema.md" not in text
        assert schema_path in text


def test_analytics_analyze_uses_split_config_namespace_for_themes() -> None:
    text = _read(".claude/skills/analytics-analyze/SKILL.md")
    script = _read("src/youtube_automation/scripts/theme_compare.py")

    assert "channel_config.tags.themes" not in text
    assert "channel_config.tags.themes" not in script
    assert "config/channel/content.json::tags.themes" in text
    assert "config/channel/content.json::tags.themes" in script
    assert "load_config().content.tags.themes" in text


def test_scene_phrases_docs_use_root_localizations_path() -> None:
    for path in (
        ".claude/skills/wf-new/references/scene_phrases.md",
        "src/youtube_automation/scripts/populate_scene_phrases.py",
    ):
        text = _read(path)
        assert "config/channel/localizations.json::supported_languages" not in text
        assert "config/localizations.json::supported_languages" in text


def test_channel_setup_keeps_upload_settings_inside_schedule_config() -> None:
    text = _read(".claude/skills/channel-setup/SKILL.md")

    assert "`config/upload_settings.json`" not in text
    assert "`config/schedule_config.json`" in text
    assert "`upload_settings`" in text


def test_video_upload_documents_thumbnail_search_order() -> None:
    expected_order = (
        "`10-assets/thumbnail.jpg` → `10-assets/thumbnail.png` → `10-assets/main.jpg` → `10-assets/main.png`"
    )
    for path in (
        ".claude/skills/video-upload/SKILL.md",
        ".claude/skills/video-upload/references/posting-checklist.md",
    ):
        text = _read(path)
        assert expected_order in text


def test_common_docs_list_optional_channel_config_files() -> None:
    required = ("shorts.json", "comments.json", "pinned-comment.json", "distrokid.json")

    for path in ("README.md", "AGENTS.md", "CLAUDE.md"):
        text = _read(path)
        for name in required:
            assert name in text, f"{path} missing {name}"

    readme = _read("README.md")
    assert "community.example.json" in readme
    assert "skill-local raw JSON" in readme


def test_community_post_declares_raw_json_loader_exception() -> None:
    text = _read(".claude/skills/community-post/SKILL.md")

    assert "skill-local raw JSON 例外" in text
    assert "utils.config.load_config()" in text
    assert "`community` section を持たない" in text


def test_collection_lifecycle_uses_mp3_as_common_audio_contract() -> None:
    text = _read(".claude/skills/collection-ideate/references/collection-lifecycle.md")

    assert "02-Individual-music/ # 個別音声ファイル（WAV）" not in text
    assert "01-master/           # マスター音声・動画（master.mp3, *.mp4）" in text
    assert "02-Individual-music/ # 個別音声ファイル（*.mp3）" in text
    assert "WAV は中間成果物" in text
