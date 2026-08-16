"""#2416 / #2419-#2422 の無人実行 skip 契約を文書と設定の両側で固定する."""

import yaml

from tests.helpers.paths import REPO_ROOT

ROOT = REPO_ROOT
SKILLS = ROOT / ".claude" / "skills"


def _text(skill: str) -> str:
    skill_dir = SKILLS / skill
    paths = [skill_dir / "SKILL.md"]
    if skill == "wf-new":
        paths.append(skill_dir / "references" / "phase2.md")
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


def _config(skill: str) -> dict:
    if skill == "collection-ideate":
        return yaml.safe_load(
            (SKILLS / "wf-new" / "references" / "collection-ideate.config.default.yaml").read_text(encoding="utf-8")
        )
    return yaml.safe_load((SKILLS / skill / "config.default.yaml").read_text(encoding="utf-8"))


def test_wf_new_auto_selection_is_rank_one_and_excludes_minimal_mode() -> None:
    text = _text("wf-new")

    assert "workflow.wf_new.skip_plan_selection" in text
    assert "推奨順 1 位" in text
    assert "自動選択" in text
    assert "plan_proposals.json" in text
    assert "minimal mode" in text
    assert "blocked" in text


def test_wf_auto_recognizes_explicit_skip_settings() -> None:
    text = (SKILLS / "wf-new" / "references" / "auto.md").read_text(encoding="utf-8")

    assert "workflow.wf_new.skip_plan_selection" in text
    assert "skip_*_approval" in text
    assert "skip_cost_confirm" in text
    assert "明示 opt-in" in text


def test_lyria_skip_preserves_audit_artifact_and_hard_cap() -> None:
    text = (SKILLS / "music" / "references" / "generate.md").read_text(encoding="utf-8")

    assert _config("music")["generate"]["lyria"]["skip_generation_approval"] is False
    assert "skip_generation_approval: true" in text
    assert "lyria-prompt.md" in text
    assert "60 セグメント hard cap" in text


def test_loop_video_skips_are_independent_and_keep_safety_gates() -> None:
    text = (SKILLS / "thumbnail" / "references" / "loop.md").read_text(encoding="utf-8")
    config = _config("thumbnail")["loop"]

    assert config["skip_billing_approval"] is False
    assert config["skip_preview_approval"] is False
    assert "enabled: false" in text
    assert "fail-loud" in text
    assert "-y" in text
    assert "自動再生成" in text


def test_wf_new_ideation_skip_records_generation_conditions_and_calls() -> None:
    text = (SKILLS / "wf-new" / "references" / "ideate.md").read_text(encoding="utf-8")

    assert _config("collection-ideate")["preview"]["skip_cost_confirm"] is False
    assert "preview.skip_cost_confirm" in text
    assert "想定 call 数" in text
    assert "plan_proposals.json" in text
    assert "記録に失敗した場合は画像生成せず停止" in text
