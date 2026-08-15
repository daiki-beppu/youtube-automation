"""yt-doctor の宣言的 check registry 契約。"""

from __future__ import annotations

from pathlib import Path

from youtube_automation.commands.system import doctor

EXPECTED_CHECK_IDS = (
    "ffmpeg",
    "ffprobe",
    "uv",
    "uv_project",
    "automation_package",
    "skills_synced",
    "numbered_duplicates",
    "gcloud",
    "gcloud_account",
    "gcp_project",
    "billing_linked",
    "apis_enabled",
    "adc",
    "adc_quota_project",
    "iam_aiplatform_user",
    "client_secrets",
    "oauth_client_sharing",
    "oauth_token",
    "oauth_token_readonly",
    "reporting_job",
    "streaming_vps_state",
    "channel_config",
    "playlist_config",
    "playlist_create_dry_run",
    "analytics_report",
    "benchmark_data",
    "ttp_wf_new_readiness",
    "wf_new_readiness",
    "initial_setup_readiness",
    "upload_ready",
)


def test_registry_declares_unique_checks_in_execution_order() -> None:
    assert tuple(definition.id for definition in doctor.CHECK_REGISTRY) == EXPECTED_CHECK_IDS
    assert len({definition.id for definition in doctor.CHECK_REGISTRY}) == len(doctor.CHECK_REGISTRY)


def test_registry_categories_are_contiguous() -> None:
    categories = [definition.category for definition in doctor.CHECK_REGISTRY]

    assert list(dict.fromkeys(categories)) == [
        doctor.BOOTSTRAP_CATEGORY,
        doctor.API_CATEGORY,
        doctor.CHANNEL_CATEGORY,
        doctor.DATA_CATEGORY,
        doctor.UPLOAD_CATEGORY,
    ]
    for category in set(categories):
        indexes = [index for index, value in enumerate(categories) if value == category]
        assert indexes == list(range(indexes[0], indexes[-1] + 1))


def test_registry_declares_apply_and_cwd_semantics() -> None:
    definitions = {definition.id: definition for definition in doctor.CHECK_REGISTRY}

    assert definitions["gcp_project"].apply_kind is doctor.ApplyKind.PROJECT
    assert definitions["billing_linked"].apply_kind is doctor.ApplyKind.BILLING
    assert definitions["skills_synced"].apply_kind is doctor.ApplyKind.AI_EXEC
    assert definitions["channel_config"].apply_kind is doctor.ApplyKind.NONE
    assert definitions["skills_synced"].cwd_semantics is doctor.CwdSemantics.BOOTSTRAP_ROOT
    assert definitions["apis_enabled"].cwd_semantics is doctor.CwdSemantics.CHANNEL


def test_new_registry_declaration_drives_run_render_and_apply(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    channel = workspace / "channels" / "alpha"
    (channel / "config" / "channel").mkdir(parents=True)
    diagnoses = iter(("fail", "ok"))

    def check_example(_channel_dir: Path) -> doctor.CheckResult:
        status = next(diagnoses)
        action = doctor._ai_exec_action(["example", "--fix"]) if status == "fail" else None
        return doctor.CheckResult(id="example", status=status, message=status, category="example", next_action=action)

    definition = doctor.CheckDefinition(
        id="example",
        category="example",
        run=check_example,
        apply_kind=doctor.ApplyKind.AI_EXEC,
        cwd_semantics=doctor.CwdSemantics.BOOTSTRAP_ROOT,
    )
    monkeypatch.setattr(doctor, "CHECK_REGISTRY", (definition,))
    commands: list[tuple[list[str], Path]] = []
    monkeypatch.setattr(
        doctor,
        "_run_apply_command",
        lambda argv, cwd: commands.append((argv, cwd)) or (0, "", ""),
    )

    outcome = doctor.run_apply(channel)

    assert [result.id for result in outcome.results] == ["example"]
    assert commands == [(["example", "--fix"], workspace)]
    assert "=== example ===" in doctor.render_table(outcome.results, doctor.summarize(outcome.results), channel)
    assert doctor._check_result_to_dict(outcome.results[0])["category"] == "example"
