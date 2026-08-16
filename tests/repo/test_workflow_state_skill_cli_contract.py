"""workflow skills の制御面 state 更新を owner CLI に限定する契約。"""

from __future__ import annotations

from tests.helpers.paths import REPO_ROOT
from youtube_automation.domains.skills.inventory import SkillInventory

SKILLS = {name: REPO_ROOT / ".claude" / "skills" / name / "SKILL.md" for name in ("wf-new", "wf-next")}
INVENTORY = SkillInventory(REPO_ROOT)


def _text(skill: str) -> str:
    return SKILLS[skill].read_text(encoding="utf-8")


def test_workflow_skills_route_control_plane_mutations_through_owner_cli() -> None:
    """phase / stage / upload は Edit / Write で直接変更しない。"""
    wf_new = _text("wf-new")
    wf_next = _text("wf-next")

    for text in (wf_new, wf_next):
        assert "制御面キー (`phase` / `stage` / `upload` / `updated_at`)" in text
        assert "Edit / Write で直接変更しない" in text

    assert 'yt-workflow-state --collection "$COLLECTION_DIR" set-phase prepared' in wf_new
    for command in (
        'yt-workflow-state --collection "$COLLECTION_DIR" set-phase publishing',
        'yt-workflow-state --collection "$COLLECTION_DIR" set-stage live',
        'yt-workflow-state --collection "$COLLECTION_DIR" set-phase complete',
        'yt-workflow-state --collection "$COLLECTION_DIR" set-upload --video-id',
    ):
        assert command in wf_next


def test_known_direct_control_plane_instructions_do_not_return() -> None:
    """移行前の具体的な直接更新文言を縮小専用 ratchet として固定する。"""
    wf_new = _text("wf-new")
    wf_next = _text("wf-next")

    assert '`phase = "prepared"` まで更新' not in wf_new
    assert '`phase: "publishing"`、`assets.master_video`' not in wf_next
    assert '`stage: "live"`、`phase: "complete"`、`updated_at` だけを atomic write' not in wf_next


def test_asset_mutations_are_routed_through_owner_cli() -> None:
    """資産系 state を AI の Edit / Write に戻さない。"""
    documents = (path for directory in INVENTORY.skill_directories() for path in directory.rglob("*.md"))
    text = "\n".join(path.read_text(encoding="utf-8") for path in documents)

    for phrase in (
        "資産系キー (`assets.*` / `planning.*`) はこの段では直接更新のまま",
        "`thumbnail.approved = true` を更新する",
        "`description.generated = true` に更新する",
        "成功時だけ `assets.raw_master` を更新して owner CLI の `touch`",
        "`assets.master_video`、`assets.description`、`description.generated` を更新してから",
        "`assets.music_prompts = true`、`planning.music`、`updated_at` を更新する",
    ):
        assert phrase not in text

    assert "set-asset" in text
    assert "set-planning" in text
    assert "set-thumbnail-approved" in text
    assert "set-description-generated" in text


def test_thumbnail_approval_routes_use_only_the_canonical_asset_key() -> None:
    thumbnail_skill = (REPO_ROOT / ".claude" / "skills" / "thumbnail" / "SKILL.md").read_text(encoding="utf-8")
    loop_reference = (REPO_ROOT / ".claude" / "skills" / "thumbnail" / "references" / "loop.md").read_text(
        encoding="utf-8"
    )

    assert "assets.thumbnail" in thumbnail_skill
    assert "thumbnail.approved = true" not in thumbnail_skill
    assert "assets.thumbnail = true" in loop_reference
    assert "owner の `thumbnail_approved` accessor" in loop_reference


def test_description_completion_routes_use_only_the_canonical_asset_key() -> None:
    video_description = (REPO_ROOT / ".claude" / "skills" / "video" / "references" / "describe.md").read_text(
        encoding="utf-8"
    )
    wf_next = _text("wf-next")

    assert "assets.description" in video_description
    assert "description.generated" not in video_description
    assert "assets.description" in wf_next
    assert "description.generated" not in wf_next
    assert wf_next.count("set-description-generated true") == 1


def test_workflow_music_engine_routes_use_the_canonical_planning_key() -> None:
    wf_new = _text("wf-new")
    music_generate = (REPO_ROOT / ".claude" / "skills" / "music" / "references" / "generate.md").read_text(
        encoding="utf-8"
    )

    for text in (wf_new, music_generate):
        assert "planning.music.engine" in text
    assert "workflow-state.json::music_engine" not in wf_new
    assert 'workflow-state.json` の `music_engine = "lyria"' not in music_generate
