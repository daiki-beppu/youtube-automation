"""段階開示後の channel-new bootstrap 実行契約。"""

from __future__ import annotations

import re

from tests.helpers.paths import REPO_ROOT

SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "channel-new"
SKILL_MD = SKILL_DIR / "SKILL.md"
BOOTSTRAP_REFERENCE_MD = SKILL_DIR / "references" / "new-channel-bootstrap.md"

BOOTSTRAP_DETAIL_HEADINGS = {
    "Repository initialization details",
    "Setup gate details",
    "Configuration input schema",
    "Initial file generation details",
}


def _headings(markdown: str) -> set[str]:
    return {match.group(1).strip() for match in re.finditer(r"^#{2,4}\s+(.+?)\s*$", markdown, re.MULTILINE)}


def test_skill_dispatches_bootstrap_reference_before_step_2() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    relative_reference = BOOTSTRAP_REFERENCE_MD.relative_to(SKILL_DIR).as_posix()

    dispatch = skill.index(f"]({relative_reference})")
    step_2 = skill.index("### Step 2:")

    assert BOOTSTRAP_REFERENCE_MD.is_file()
    assert dispatch < step_2


def test_bootstrap_detail_sections_have_one_reference_owner() -> None:
    skill_headings = _headings(SKILL_MD.read_text(encoding="utf-8"))
    reference_headings = _headings(BOOTSTRAP_REFERENCE_MD.read_text(encoding="utf-8"))

    assert BOOTSTRAP_DETAIL_HEADINGS <= reference_headings
    assert BOOTSTRAP_DETAIL_HEADINGS.isdisjoint(skill_headings)


def test_approval_precedes_repository_side_effects_and_steps_keep_order() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")

    step_2 = skill.index("### Step 2:")
    approval = skill.index("AskUserQuestion", step_2)
    git_init = skill.index("git init", approval)
    gh_repo_create = skill.index("gh repo create", git_init)
    step_3 = skill.index("### Step 3:", gh_repo_create)
    doctor = skill.index("uv run yt-doctor --json", step_3)
    step_4 = skill.index("### Step 4:", doctor)
    channel_init = skill.index("uv run yt-channel-init", step_4)

    assert step_2 < approval < git_init < gh_repo_create < step_3 < doctor < step_4 < channel_init


def test_reference_owns_setup_gate_check_classification() -> None:
    reference = BOOTSTRAP_REFERENCE_MD.read_text(encoding="utf-8")
    skill = SKILL_MD.read_text(encoding="utf-8")
    bootstrap = skill.split("### Step 2:", 1)[1].split("### Step 5:", 1)[0]

    for detail in (
        "playlist_create_dry_run",
        "initial_setup_readiness",
        "config/skills/suno.yaml` 未転記由来",
        "既存チャンネルの token コピー",
    ):
        assert reference.count(detail) == 1
        assert detail not in bootstrap


def test_reference_owns_configuration_schema_and_initial_file_rules() -> None:
    reference = BOOTSTRAP_REFERENCE_MD.read_text(encoding="utf-8")
    skill = SKILL_MD.read_text(encoding="utf-8")

    for detail in (
        "動画尺は Step 5.5",
        "推測 default では埋めない",
        "setup が作成済みのディレクトリを削除・再生成しない",
        "Step 5 の実データ確認とユーザー承認後",
    ):
        assert reference.count(detail) == 1
        assert detail not in skill


def test_step_4_does_not_confirm_duration_before_step_5_5_derivation() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    reference = BOOTSTRAP_REFERENCE_MD.read_text(encoding="utf-8")

    step_4 = skill.index("### Step 4:")
    step_5 = skill.index("### Step 5:", step_4)
    step_5_5 = skill.index("### Step 5.5:", step_5)
    step_4_confirmation = next(line for line in skill[step_4:step_5].splitlines() if "確認項目は" in line)

    assert "動画尺" not in step_4_confirmation
    assert "手入力" not in step_4_confirmation
    assert "動画尺は Step 5.5" in reference
    assert step_4 < step_5 < step_5_5


def test_skill_keeps_bootstrap_commands_defaults_artifacts_and_stop_conditions() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")

    for command in (
        "git init",
        "gh repo create <repo-name> --private --source . --remote origin",
        "uv run yt-doctor --json",
        "uv run yt-channel-init",
        "--distrokid-enabled",
    ):
        assert command in skill
    for contract in (
        "既存ファイルは `--force` がない限り上書きしない",
        "scheduled_automation",
        "config/channel/{meta,content,youtube,analytics,playlists,workflow,audio}.json",
        "Step 4 以降へ進まない",
        "remote 作成を保留",
    ):
        assert contract in skill
