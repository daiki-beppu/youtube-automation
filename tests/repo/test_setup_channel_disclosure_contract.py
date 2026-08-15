"""`/setup --channel` の段階開示・承認・停止契約。"""

from __future__ import annotations

import re
import shutil
from hashlib import sha256
from pathlib import Path

import yaml

from tests.helpers.paths import REPO_ROOT

SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "setup"
SKILL_MD = SKILL_DIR / "references" / "channel-mode.md"
BOOTSTRAP_REFERENCE_MD = SKILL_DIR / "references" / "new-channel-bootstrap.md"
TTP_SEED_DURATION_REFERENCE_MD = SKILL_DIR / "references" / "ttp-seed-and-duration.md"
PERSONA_BRANDING_READINESS_REFERENCE_MD = SKILL_DIR / "references" / "persona-branding-readiness.md"
CHANNEL_NEW_SKILL_MD = REPO_ROOT / ".claude" / "skills" / "channel-new" / "SKILL.md"
CHANNEL_NEW_RESIDUAL_SKILL_SHA256 = "c780775dcd926e0c040b46fcb880a7740da06dd2c76a77556145830716694220"
CHANNEL_NEW_DESCRIPTION_SHA256 = "f6723ead03cbeaa889a3a10a4ef7195468841b049f256289c5795469cd752a9d"
CHANNEL_NEW_ROUTING_SHA256 = "9e66e6cb0b6818436cf215be521fcd67576ed2668927017f05e1af6aebd3adf1"
OPENING_ASSETS = {
    "new-channel-bootstrap.md",
    "ttp-seed-and-duration.md",
    "persona-branding-readiness.md",
    "derive_ttp_duration.py",
    "initial_save_guard.sh",
}
BEFORE_MOVE_SHA256 = {
    "new-channel-bootstrap.md": "dbae6fc0b7bba180d8c7ec3a40667428ca584e50977127e7ab7a21e9391160c4",
    "ttp-seed-and-duration.md": "6be5874c9ea6f71b2158cbb6931d542c3e21493dd2546634d4d95bae97945c93",
    "persona-branding-readiness.md": "f40a2050cd6fbc134651c627e494694b29cc86eda9702825f96b1d8ac3ff0d61",
    "derive_ttp_duration.py": "bed2ac050d67f3974e84815dbd79388809c4b8174bfa246f24a83d858990a132",
    "initial_save_guard.sh": "93e9503da8d1e1c2680f682be25c053988fd0fd45fa3bf193e8272d2dd704ac3",
}

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


def _opening_asset_violations(skills_dir: Path) -> set[str]:
    violations = set()
    for asset in OPENING_ASSETS:
        owners = list(skills_dir.glob(f"*/references/{asset}"))
        if len(owners) != 1 or owners[0].parent.parent.name != "setup":
            violations.add(asset)
    return violations


def _channel_new_opening_routing_violations(markdown: str) -> set[str]:
    frontmatter = yaml.safe_load(markdown.split("---", 2)[1])
    description = frontmatter["description"]
    routing = markdown.split("## モード判別", 1)[1].split("## 外部データの扱い", 1)[0]
    opening_triggers = ("チャンネル追加", "新チャンネル", "新規チャンネル", "チャンネル開設")
    violations = set()
    if sha256(markdown.encode()).hexdigest() != CHANNEL_NEW_RESIDUAL_SKILL_SHA256:
        violations.add("residual skill content")
    if sha256(description.encode()).hexdigest() != CHANNEL_NEW_DESCRIPTION_SHA256:
        violations.add("frontmatter description")
    if sha256(routing.encode()).hexdigest() != CHANNEL_NEW_ROUTING_SHA256:
        violations.add("opening routing content")
    violations.update(f"description trigger:{trigger}" for trigger in opening_triggers if trigger in description)
    violations.update(f"rejection context:{trigger}" for trigger in opening_triggers if trigger not in routing)
    if "`/setup --channel` を案内して停止する" not in routing:
        violations.add("positive setup route")
    if "質問、reference の Read、コマンド実行、ファイルやディレクトリの作成・更新を行わない" not in routing:
        violations.add("no-write stop")
    for marker in (
        "## 完了条件（新規開設モード）",
        "1. **新規開設モード**（Step 1〜10）",
        "## Instructions（新規開設モード）",
        "## TTP 原則",
    ):
        if marker in markdown:
            violations.add(f"opening execution:{marker}")
    for heading in re.findall(r"^#{2,4}\s+(Step\s+(?:[1-9]|10)(?=[:：.\s]).*)$", markdown, re.MULTILINE):
        violations.add(f"opening step:{heading}")
    for command in ("yt-channel-init", "yt-channel-seed", "derive_ttp_duration.py", "initial_save_guard.sh"):
        if re.search(rf"(?m)^\s*(?:uv run )?[^\n`]*{re.escape(command)}(?:\s|`|$)", markdown):
            violations.add(f"opening command:{command}")
    for path in (
        "../setup/references/new-channel-bootstrap.md",
        "../setup/references/ttp-seed-and-duration.md",
        "../setup/references/persona-branding-readiness.md",
        ".claude/skills/setup/references/derive_ttp_duration.py",
        ".claude/skills/setup/references/initial_save_guard.sh",
    ):
        if path in markdown:
            violations.add(f"opening asset:{path}")
    return violations


def test_skill_dispatches_bootstrap_reference_before_step_2() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    relative_reference = BOOTSTRAP_REFERENCE_MD.relative_to(SKILL_MD.parent).as_posix()

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


def test_bootstrap_setup_gate_owner_link_resolves_to_required_check_contract() -> None:
    reference = BOOTSTRAP_REFERENCE_MD.read_text(encoding="utf-8")
    owner_link = re.search(r"\[channel-mode\.md\]\(([^)]+)\)", reference)
    assert owner_link is not None
    owner = BOOTSTRAP_REFERENCE_MD.parent / owner_link.group(1)
    assert owner.resolve() == SKILL_MD.resolve()
    owner_text = owner.read_text(encoding="utf-8")
    for check_id in (
        "ffmpeg",
        "ffprobe",
        "uv",
        "uv_project",
        "automation_package",
        "skills_synced",
        "gcloud",
        "gcloud_account",
        "gcp_project",
        "billing_linked",
        "apis_enabled",
        "adc",
        "adc_quota_project",
        "iam_aiplatform_user",
        "env_file",
        "client_secrets",
        "oauth_token",
    ):
        assert f"`{check_id}`" in owner_text
    assert "いずれかが `ok` でなければ" in owner_text
    assert "Step 4 以降へ進まない" in owner_text


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
    relative_reference = TTP_SEED_DURATION_REFERENCE_MD.relative_to(SKILL_MD.parent).as_posix()

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
    relative_reference = PERSONA_BRANDING_READINESS_REFERENCE_MD.relative_to(SKILL_MD.parent).as_posix()

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


def test_setup_channel_preserves_all_steps_and_lifecycle_contracts() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    headings = [
        "### Step 1:",
        "### Step 2:",
        "### Step 3:",
        "### Step 4:",
        "### Step 5:",
        "### Step 5.5:",
        "### Step 6:",
        "### Step 7:",
        "### Step 8:",
        "### Step 9:",
        "### Step 10:",
    ]
    positions = [skill.index(heading) for heading in headings]
    assert positions == sorted(positions)
    for contract in (
        "失敗または blocked になった Step で停止",
        "最初の未完了 Step から再開",
        "完了済み成果物を無断で上書きしない",
        "同じ状態での再実行は同じ停止・skip・完了判定",
        "承認 gate より前に実行しない",
        "成功案内を出さない",
    ):
        assert contract in skill


def test_opening_assets_have_exactly_one_setup_owner() -> None:
    assert _opening_asset_violations(REPO_ROOT / ".claude" / "skills") == set()


def test_channel_new_rejects_opening_contexts_without_artifact_ownership_or_writes() -> None:
    channel_new = CHANNEL_NEW_SKILL_MD.read_text(encoding="utf-8")

    assert _channel_new_opening_routing_violations(channel_new) == set()
    for asset in OPENING_ASSETS:
        assert f"channel-new/references/{asset}" not in channel_new


def test_channel_new_opening_rejection_detects_trigger_route_write_and_execution_mutations() -> None:
    source = CHANNEL_NEW_SKILL_MD.read_text(encoding="utf-8")
    mutations = {
        "description trigger:チャンネル追加": source.replace(
            "未作成 channel の初回 bootstrap",
            "チャンネル追加の初回 bootstrap",
            1,
        ),
        "positive setup route": source.replace("`/setup --channel` を案内して停止する", "停止する", 1),
        "no-write stop": source.replace(
            "質問、reference の Read、コマンド実行、ファイルやディレクトリの作成・更新を行わない",
            "",
            1,
        ),
        "opening execution:## Instructions（新規開設モード）": source.replace(
            "## 外部データの扱い",
            "## Instructions（新規開設モード）\n\n## 外部データの扱い",
            1,
        ),
        "opening step:Step 1: TTP ヒアリング": source.replace(
            "## 外部データの扱い",
            "### Step 1: TTP ヒアリング\n\nTTP 対象を確認する。\n\n## 外部データの扱い",
            1,
        ),
        "opening command:yt-channel-init": source.replace(
            "## 外部データの扱い",
            "### Step 4: フルパッケージ config / 初期運用ファイル生成\n\n"
            "```bash\nuv run yt-channel-init\n```\n\n## 外部データの扱い",
            1,
        ),
    }

    for expected, mutated in mutations.items():
        assert expected in _channel_new_opening_routing_violations(mutated)


def test_channel_new_opening_rejection_detects_reviewer_combined_counterexample() -> None:
    source = CHANNEL_NEW_SKILL_MD.read_text(encoding="utf-8")
    mutated = source.replace(
        'description: "Use when ',
        'description: "Use when 新規チャンネルを開設するとき、',
        1,
    ).replace(
        "## 外部データの扱い",
        "### Step 1: TTP ヒアリング\n\n"
        "### Step 4: フルパッケージ config / 初期運用ファイル生成\n\n"
        "```bash\nuv run yt-channel-init\n```\n\n"
        "## 外部データの扱い",
        1,
    )

    assert _channel_new_opening_routing_violations(mutated) >= {
        "description trigger:新規チャンネル",
        "opening step:Step 1: TTP ヒアリング",
        "opening step:Step 4: フルパッケージ config / 初期運用ファイル生成",
        "opening command:yt-channel-init",
    }


def test_channel_new_opening_rejection_detects_new_channel_creation_description() -> None:
    source = CHANNEL_NEW_SKILL_MD.read_text(encoding="utf-8")
    mutated = source.replace(
        'description: "Use when ',
        'description: "Use when 新しいチャンネルを作るとき、',
        1,
    )

    assert "residual skill content" in _channel_new_opening_routing_violations(mutated)


def test_channel_new_opening_rejection_detects_channel_establishment_description() -> None:
    source = CHANNEL_NEW_SKILL_MD.read_text(encoding="utf-8")
    mutated = source.replace(
        'description: "Use when ',
        'description: "Use when YouTube チャンネルを新設するとき、',
        1,
    )

    assert "residual skill content" in _channel_new_opening_routing_violations(mutated)


def test_channel_new_opening_rejection_detects_prose_execution_reintroduction() -> None:
    source = CHANNEL_NEW_SKILL_MD.read_text(encoding="utf-8")
    mutated = source.replace(
        "## 外部データの扱い",
        "TTP 対象を聞き、config/channel/*.json を生成して branding を反映する。\n\n## 外部データの扱い",
        1,
    )

    assert "residual skill content" in _channel_new_opening_routing_violations(mutated)


def test_opening_asset_inventory_detects_real_removal_and_duplicate(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    setup_references = skills_dir / "setup" / "references"
    setup_references.mkdir(parents=True)
    for asset in OPENING_ASSETS:
        shutil.copy2(SKILL_DIR / "references" / asset, setup_references / asset)

    (setup_references / "derive_ttp_duration.py").unlink()
    duplicate = skills_dir / "channel-new" / "references"
    duplicate.mkdir(parents=True)
    shutil.copy2(setup_references / "initial_save_guard.sh", duplicate / "initial_save_guard.sh")

    assert _opening_asset_violations(skills_dir) == {"derive_ttp_duration.py", "initial_save_guard.sh"}


def test_moved_opening_assets_preserve_pre_move_bytes_or_owner_only_semantics() -> None:
    canonical_pointer_rewrites = {
        "new-channel-bootstrap.md": (
            "[channel-mode.md](channel-mode.md) を正とし、必ず `/setup --channel` の dispatch から",
            "`../SKILL.md` を正とし、必ず本体の dispatch から",
        ),
        "ttp-seed-and-duration.md": (
            "[channel-mode.md](channel-mode.md) を正とする",
            "`../SKILL.md` を正とする",
        ),
        "persona-branding-readiness.md": (
            "[channel-mode.md](channel-mode.md) を正とし",
            "`../SKILL.md` を正とし",
        ),
    }
    for asset, expected in BEFORE_MOVE_SHA256.items():
        payload = (SKILL_DIR / "references" / asset).read_bytes()
        if asset in canonical_pointer_rewrites:
            current, original = canonical_pointer_rewrites[asset]
            text = payload.decode()
            assert current in text
            payload = text.replace(current, original, 1).encode()
        if asset == "new-channel-bootstrap.md":
            payload = payload.replace(
                b"[channel-mode.md](channel-mode.md) \xe3\x81\xab\xe7\xbd\xae\xe3\x81\x8f",
                b"`../SKILL.md` \xe3\x81\xab\xe6\xae\x8b\xe3\x81\x99",
                1,
            )
        if asset == "ttp-seed-and-duration.md":
            payload = payload.replace(b".claude/skills/setup/references/", b".claude/skills/channel-new/references/")
        assert sha256(payload).hexdigest() == expected


def test_channel_new_keeps_shared_assets_without_opening_asset_duplicates() -> None:
    references = CHANNEL_NEW_SKILL_MD.parent / "references"
    for shared in ("fetch_branding_snapshot.py", "config-generation-rules.md", "verification.md"):
        assert (references / shared).is_file()
    for opening in OPENING_ASSETS:
        assert not (references / opening).exists()


def test_initial_save_cleanup_keeps_guarded_mutation_order() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    step_10 = skill.index("### Step 10:")

    porcelain_before = skill.index("git status --porcelain", step_10)
    git_add = skill.index("git add -A", porcelain_before)
    staged_review = skill.index("git diff --cached --name-only", git_add)
    secret_guard = skill.index("initial_save_guard.sh || exit 1", staged_review)
    commit = skill.index('git commit -m "chore: 初回チャンネル設定を保存"', secret_guard)
    porcelain_after = skill.index("git status --porcelain", commit)

    assert porcelain_before < git_add < staged_review < secret_guard < commit < porcelain_after


def test_skill_keeps_initial_save_artifacts_and_failure_stop_contracts() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")

    for contract in (
        "secret-like file staged; unstaged before commit",
        "保存未完了として",
        "成功案内は出さない",
    ):
        assert contract in skill
