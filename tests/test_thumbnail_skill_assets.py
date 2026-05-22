"""thumbnail skill の配布アセット内容を固定化するテスト。"""

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _read_thumbnail_skill() -> str:
    path = _repo_root() / ".claude" / "skills" / "thumbnail" / "SKILL.md"
    return path.read_text(encoding="utf-8")


def _read_thumbnail_default_config() -> str:
    path = _repo_root() / ".claude" / "skills" / "thumbnail" / "config.default.yaml"
    return path.read_text(encoding="utf-8")


def _slice_between(text: str, start_marker: str, end_marker: str) -> str:
    start_idx = text.find(start_marker)
    if start_idx == -1:
        raise AssertionError(f"{start_marker!r} が見つかりません")

    end_idx = text.find(end_marker, start_idx)
    if end_idx == -1:
        raise AssertionError(f"{end_marker!r} が見つかりません")

    return text[start_idx:end_idx]


def test_thumbnail_skill_adds_ttp_preflight_checklist_before_two_phase_section() -> None:
    skill = _read_thumbnail_skill()

    checklist_idx = skill.find("#### TTP プリフライト・チェックリスト")
    recovery_idx = skill.find("#### 失敗時の対処")
    two_phase_idx = skill.find("### Two-Phase モード（従来方式・フォールバック）")

    assert recovery_idx != -1
    assert checklist_idx != -1
    assert two_phase_idx != -1
    assert recovery_idx < checklist_idx < two_phase_idx


def test_ttp_preflight_checklist_covers_required_operational_checks() -> None:
    skill = _read_thumbnail_skill()
    checklist_block = _slice_between(
        skill,
        "#### TTP プリフライト・チェックリスト",
        "### Two-Phase モード（従来方式・フォールバック）",
    )

    assert "reference_images.default" in checklist_block
    assert 'generation_mode: "single_step"' in checklist_block
    assert "diff_prompt_template" in checklist_block
    assert "image_generation.gemini.reference_images.stock.enabled" in checklist_block
    assert "/thumbnail-compare" in checklist_block
    assert "承認**前**" in checklist_block


def test_thumbnail_skill_documents_thumbnail_compare_and_alignment_check_roles() -> None:
    skill = _read_thumbnail_skill()
    quality_idx = skill.find("## 品質チェック")
    role_idx = skill.find("## 視認性検証と整合性監査の役割分担")
    prompt_idx = skill.find("## プロンプト保存")
    role_block = _slice_between(skill, "## 視認性検証と整合性監査の役割分担", "## プロンプト保存")

    assert quality_idx != -1
    assert role_idx != -1
    assert prompt_idx != -1
    assert quality_idx < role_idx < prompt_idx

    assert "/thumbnail-compare" in role_block
    assert "/alignment-check" in role_block
    assert "視認性検証" in role_block
    assert "整合性監査" in role_block
    assert "320px" in role_block
    assert "公開**後**" in role_block


def test_thumbnail_default_config_remains_ttp_aligned() -> None:
    config = _read_thumbnail_default_config()

    assert "generation_mode: single_step" in config
    assert "rotate: true" in config
    assert "variation_clause: |" in config
    assert "style_lock_clause: |" in config
    assert "text_strip_clause: |" in config
    assert "enabled: true" in config
    assert 'source_role: "thumbnail_candidate"' in config
    assert "fallback_when_empty: true" in config
    assert 'diff_prompt_template: ""' in config
