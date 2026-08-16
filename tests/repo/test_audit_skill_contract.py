"""`/audit --alignment` の公開 skill 契約を検証する。"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from tests.helpers.paths import REPO_ROOT
from youtube_automation.commands.analytics import video_analyze
from youtube_automation.commands.metadata import metadata_audit
from youtube_automation.commands.system.skills_sync import _migrate_config
from youtube_automation.configuration import skills as skill_config
from youtube_automation.domains.skills.inventory import SkillInventory

INVENTORY = SkillInventory(REPO_ROOT)
AUDIT_DIR = INVENTORY.skill_directory("audit")


def test_audit_exposes_alignment_as_an_exclusive_mode() -> None:
    skill_names = {path.name for path in INVENTORY.skill_directories()}
    frontmatter = INVENTORY.frontmatter("audit")
    mode = INVENTORY.section("audit", "## モード判定")

    assert "audit" in skill_names
    assert "alignment-check" not in skill_names
    assert "value-loop-audit" not in skill_names
    assert "video-analyze" not in skill_names
    assert "metadata-audit" not in skill_names
    assert isinstance(frontmatter, dict)
    assert frontmatter["name"] == "audit"
    assert frontmatter["purpose"] == "振り返る"
    assert "--alignment" in frontmatter["description"]
    assert "2 個以上" in mode
    assert "1 個なら" in mode
    assert "0 個なら" in mode
    assert "| `--alignment` | `references/alignment.md` |" in mode
    assert "| `--value-loop` | `references/value-loop.md` |" in mode
    assert "| `--video` | `references/video.md` |" in mode
    assert "| `--metadata` | `references/metadata.md` |" in mode
    assert INVENTORY.reference_exists("audit", "references/alignment.md")
    assert INVENTORY.reference_exists("audit", "references/value-loop.md")
    assert INVENTORY.reference_exists("audit", "references/video.md")
    assert INVENTORY.reference_exists("audit", "references/metadata.md")


def test_alignment_mode_keeps_the_audit_inputs_and_external_read_only_boundary() -> None:
    skill = (AUDIT_DIR / "SKILL.md").read_text(encoding="utf-8")
    alignment = (AUDIT_DIR / "references" / "alignment.md").read_text(encoding="utf-8")
    handoff = INVENTORY.section("audit", "## 前後工程")
    boundary = _section(alignment, "## 読み取り専用境界")

    assert "/channel-strategy --constraints" in handoff
    assert "/thumbnail" in handoff
    assert "/music" in handoff
    assert "docs/plans/alignment-audit.{json,html}" in skill
    for input_path in (
        "collections/<id>/10-assets/thumbnail.jpg",
        "collections/<id>/20-documentation/suno-prompts.md",
        "collections/<id>/workflow-state.json",
    ):
        assert input_path in skill
    for dimension in ("音楽ムード", "サムネ", "タイトル"):
        assert dimension in alignment
    assert "外部サービスへの書き込みを行わない" in boundary
    assert "変更は候補提示まで" in boundary


def _section(text: str, heading: str) -> str:
    start = text.index(f"{heading}\n") + len(heading) + 1
    rest = text[start:]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


def test_alignment_reference_contains_no_external_mutation_command() -> None:
    alignment_path = AUDIT_DIR / "references" / "alignment.md"
    alignment = alignment_path.read_text(encoding="utf-8")

    forbidden_commands = (
        "videos().update",
        "thumbnails().set",
        "channels().update",
        "playlists().insert",
        "playlistItems().insert",
    )
    assert all(command not in alignment for command in forbidden_commands)


def test_value_loop_mode_diagnoses_all_four_integrated_stages_without_writes() -> None:
    value_loop = (AUDIT_DIR / "references" / "value-loop.md").read_text(encoding="utf-8")
    mode = INVENTORY.section("audit", "## モード判定")

    assert "| `--value-loop` | `references/value-loop.md` |" in mode
    for stage in ("シーン定義", "制約翻訳", "公開前ゲート", "指標還流"):
        assert stage in value_loop
    for route in (
        "/channel-strategy --scene",
        "/channel-strategy --constraints",
        "/audit --alignment",
        "/analytics --analyze",
    ):
        assert route in value_loop
    assert "ファイルの作成・変更・削除" in value_loop
    assert "結果はチャット内にだけ表示" in value_loop
    assert "yt-doctor --json --check ttp_wf_new_readiness" in value_loop
    assert "persona の見出しや出典を本 mode で再実装しない" in value_loop


def test_video_mode_keeps_gemini_analysis_outputs_and_external_read_only_boundary() -> None:
    video = (AUDIT_DIR / "references" / "video.md").read_text(encoding="utf-8")

    assert "yt-video-analyze" in video
    assert "Vertex AI" in video
    assert "ADC" in video
    assert "外部サービスの状態は変更しない" in video
    for output_path in (
        "data/video_analysis/<slug>/<video_id>.json",
        "reports/video_analysis/<slug>.json",
        "reports/video_analysis/<slug>.html",
    ):
        assert output_path in video
    for forbidden_command in (
        "videos().update",
        "thumbnails().set",
        "channels().update",
        "playlists().insert",
        "playlistItems().insert",
    ):
        assert forbidden_command not in video


def test_video_config_is_namespaced_and_keeps_legacy_override(tmp_path: Path) -> None:
    defaults = yaml.safe_load((AUDIT_DIR / "config.default.yaml").read_text(encoding="utf-8"))

    assert isinstance(defaults["video"], dict)
    assert defaults["video"]["model"] == "gemini-3.5-flash"
    assert "audit.video" in skill_config.SKILL_CONFIG_KEYS
    assert video_analyze.SKILL_CONFIG_KEY == "audit.video"
    assert skill_config.skill_config_default_relative_path("video-analyze") == Path("audit/config.default.yaml")
    assert _migrate_config.SKILL_CONFIG_MIGRATIONS["video-analyze"] == _migrate_config.SkillConfigMigration(
        "audit", "video"
    )

    config_dir = tmp_path / "config" / "skills"
    config_dir.mkdir(parents=True)
    (config_dir / "video-analyze.yaml").write_text("analysis_window_sec: 300\n", encoding="utf-8")

    loaded = skill_config.load_skill_config("audit.video", use_cache=False, channel_dir=tmp_path)

    assert loaded["analysis_window_sec"] == 300
    assert not os.path.lexists(AUDIT_DIR.parent / "video-analyze")


def test_video_config_reads_canonical_audit_section(tmp_path: Path) -> None:
    config_dir = tmp_path / "config" / "skills"
    config_dir.mkdir(parents=True)
    (config_dir / "audit.yaml").write_text("video:\n  analysis_window_sec: 450\n", encoding="utf-8")

    loaded = skill_config.load_skill_config("audit.video", use_cache=False, channel_dir=tmp_path)

    assert loaded["analysis_window_sec"] == 450


def test_metadata_mode_keeps_local_remote_audit_read_only() -> None:
    metadata = (AUDIT_DIR / "references" / "metadata.md").read_text(encoding="utf-8")

    for command in (
        "yt-metadata-audit",
        "yt-metadata-audit --local",
        "yt-metadata-audit --remote",
        "yt-metadata-audit --strict",
    ):
        assert command in metadata
    assert "読み取り専用" in metadata
    assert "/video --describe" in metadata
    assert "自身では修正しない" in metadata


def test_metadata_config_is_namespaced_and_keeps_legacy_override(tmp_path: Path) -> None:
    defaults = yaml.safe_load((AUDIT_DIR / "config.default.yaml").read_text(encoding="utf-8"))

    assert defaults["metadata"]["chapters"]["remote_max"] == 12
    assert "audit.metadata" in skill_config.SKILL_CONFIG_KEYS
    assert metadata_audit.SKILL_CONFIG_KEY == "audit.metadata"
    assert skill_config.skill_config_default_relative_path("metadata-audit") == Path("audit/config.default.yaml")
    assert _migrate_config.SKILL_CONFIG_MIGRATIONS["metadata-audit"] == _migrate_config.SkillConfigMigration(
        "audit", "metadata"
    )

    config_dir = tmp_path / "config" / "skills"
    config_dir.mkdir(parents=True)
    (config_dir / "metadata-audit.yaml").write_text("chapters:\n  remote_max: 8\n", encoding="utf-8")

    loaded = skill_config.load_skill_config("audit.metadata", use_cache=False, channel_dir=tmp_path)

    assert loaded["chapters"]["remote_max"] == 8


def test_metadata_config_reads_canonical_audit_section(tmp_path: Path) -> None:
    config_dir = tmp_path / "config" / "skills"
    config_dir.mkdir(parents=True)
    (config_dir / "audit.yaml").write_text("metadata:\n  chapters:\n    remote_max: 6\n", encoding="utf-8")

    loaded = skill_config.load_skill_config("audit.metadata", use_cache=False, channel_dir=tmp_path)

    assert loaded["chapters"]["remote_max"] == 6
