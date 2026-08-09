"""段階開示後の channel-new bootstrap 実行契約。"""

from __future__ import annotations

import re

from tests.helpers.paths import REPO_ROOT

SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "channel-new"
SKILL_MD = SKILL_DIR / "SKILL.md"
BOOTSTRAP_REFERENCE_MD = SKILL_DIR / "references" / "new-channel-bootstrap.md"
TTP_SEED_DURATION_REFERENCE_MD = SKILL_DIR / "references" / "ttp-seed-and-duration.md"
PERSONA_BRANDING_READINESS_REFERENCE_MD = SKILL_DIR / "references" / "persona-branding-readiness.md"

BOOTSTRAP_DETAIL_HEADINGS = {
    "Repository initialization details",
    "Setup gate details",
    "Configuration input schema",
    "Initial file generation details",
}
TTP_SEED_DURATION_DETAIL_HEADINGS = {
    "Seed preview and approval evidence",
    "Branding snapshot schema",
    "Thumbnail reference schema",
    "Duration derivation schema",
    "Duration evidence and exceptions",
}
PERSONA_BRANDING_READINESS_DETAIL_HEADINGS = {
    "Optional research delegation details",
    "Prelaunch persona chain details",
    "Branding generation and review details",
    "Readiness matrix details",
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


def test_skill_dispatches_ttp_reference_before_step_5_actions() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    relative_reference = TTP_SEED_DURATION_REFERENCE_MD.relative_to(SKILL_DIR).as_posix()

    dispatch = skill.index(f"]({relative_reference})")
    step_5 = skill.index("### Step 5:")
    seed_preview = skill.index("uv run yt-channel-seed", step_5)

    assert TTP_SEED_DURATION_REFERENCE_MD.is_file()
    assert step_5 < dispatch < seed_preview


def test_ttp_seed_duration_detail_sections_have_one_reference_owner() -> None:
    skill_headings = _headings(SKILL_MD.read_text(encoding="utf-8"))
    reference_headings = _headings(TTP_SEED_DURATION_REFERENCE_MD.read_text(encoding="utf-8"))

    assert TTP_SEED_DURATION_DETAIL_HEADINGS <= reference_headings
    assert TTP_SEED_DURATION_DETAIL_HEADINGS.isdisjoint(skill_headings)


def test_seed_approval_precedes_benchmark_and_branding_side_effects() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    step_5 = skill.index("### Step 5:")

    seed_preview = skill.index("--no-write-benchmark", step_5)
    approval = skill.index("AskUserQuestion", seed_preview)
    benchmark_write = skill.index("--relationship", approval)
    branding_snapshot = skill.index("fetch_branding_snapshot.py", benchmark_write)

    assert seed_preview < approval < benchmark_write < branding_snapshot


def test_skill_keeps_duration_input_approval_output_and_stop_contract() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    step_5_5 = skill.index("### Step 5.5:")

    benchmark_input = skill.index("data/benchmark_*.json", step_5_5)
    dry_run = skill.index("derive_ttp_duration.py", benchmark_input)
    approval = skill.index("明示承認", dry_run)
    apply = skill.index("--apply", approval)
    audio_output = skill.index("config/channel/audio.json", apply)

    assert benchmark_input < dry_run < approval < apply < audio_output
    for contract in (
        "status: insufficient",
        "status: error",
        "推測で補完せず",
        "duration selected video",
        "ユーザー承認済み例外: duration",
    ):
        assert contract in skill


def test_reference_owns_ttp_seed_branding_and_duration_schema_details() -> None:
    reference = TTP_SEED_DURATION_REFERENCE_MD.read_text(encoding="utf-8")
    skill = SKILL_MD.read_text(encoding="utf-8")
    step_5_details = skill.split("### Step 5:", 1)[1].split("### Step 6:", 1)[0]

    for detail in (
        "uploads playlist ID",
        "brandingSettings.channel.defaultLanguage",
        "channel_image_references[0].banner[0]",
        "TTP_VIDEO_ANALYZE_TOP_N = 5",
        "duration excluded video: <video id>",
    ):
        assert reference.count(detail) == 1
        assert detail not in step_5_details


def test_skill_dispatches_persona_branding_readiness_reference_before_step_6_actions() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    relative_reference = PERSONA_BRANDING_READINESS_REFERENCE_MD.relative_to(SKILL_DIR).as_posix()

    step_6 = skill.index("### Step 6:")
    dispatch = skill.index(f"]({relative_reference})", step_6)
    first_delegation = skill.index("/discover-competitors", dispatch)

    assert PERSONA_BRANDING_READINESS_REFERENCE_MD.is_file()
    assert step_6 < dispatch < first_delegation


def test_persona_branding_readiness_detail_sections_have_one_reference_owner() -> None:
    skill_headings = _headings(SKILL_MD.read_text(encoding="utf-8"))
    reference_headings = _headings(PERSONA_BRANDING_READINESS_REFERENCE_MD.read_text(encoding="utf-8"))

    assert PERSONA_BRANDING_READINESS_DETAIL_HEADINGS <= reference_headings
    assert PERSONA_BRANDING_READINESS_DETAIL_HEADINGS.isdisjoint(skill_headings)


def test_persona_branding_readiness_and_wf_new_handoff_keep_order() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")

    persona = skill.index("/viewer-voice` → `/audience-persona-design` → `/viewing-scene`")
    branding = skill.index("### Step 8:", persona)
    image_approval = skill.index("ユーザーに提示して承認", branding)
    branding_apply = skill.index("yt-channel-settings push --apply", image_approval)
    readiness = skill.index("### Step 9:", branding_apply)
    doctor = skill.index("uv run yt-doctor --json", readiness)
    wf_new = skill.index("/wf-new", doctor)

    assert persona < branding < image_approval < branding_apply < readiness < doctor < wf_new


def test_skill_keeps_persona_branding_readiness_artifacts_and_stop_contracts() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")

    for artifact in (
        "docs/plans/viewer-voice-analysis.md",
        "docs/channel/personas/persona-definition.md",
        "docs/plans/viewing-scene-matrix.md",
        "branding/icon.png",
        "branding/banner.png",
    ):
        assert artifact in skill
    for contract in (
        "Step 8 へ進まない",
        "承認前に YouTube 側へ反映しない",
        "ttp_wf_new_readiness",
        "成功案内を出さない",
        "Step 1/5 に戻って候補を再確認",
    ):
        assert contract in skill
