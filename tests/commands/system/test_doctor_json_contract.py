"""yt-doctor --json public contract tests."""

from __future__ import annotations

import json
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


def test_json_should_expose_all_check_ids_and_check_shape(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(doctor, "_run", lambda *args, **kwargs: (127, "", "missing"))

    code = doctor.main(["--json", "--target", str(tmp_path)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert tuple(check["id"] for check in payload["checks"]) == EXPECTED_CHECK_IDS
    for check in payload["checks"]:
        assert set(check) == {"id", "status", "message", "category", "next_action", "data"}
        assert isinstance(check["id"], str)
        assert isinstance(check["status"], str)
        assert isinstance(check["message"], str)

    streaming_check = next(check for check in payload["checks"] if check["id"] == "streaming_vps_state")
    assert streaming_check["data"]["reason"] == "streaming_terraform_module_missing"


def test_json_should_keep_internal_action_fields_out_of_public_contract(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    internal_action = {
        "kind": "ai-exec",
        "cmd": "uv init",
        "argv": ["uv", "init"],
        "auto_apply": False,
    }
    result = doctor.CheckResult(
        id="uv_project",
        status="fail",
        message="uv project missing",
        category=doctor.BOOTSTRAP_CATEGORY,
        next_action=internal_action,
        data={"reason": "uv_project_missing"},
    )
    monkeypatch.setattr(doctor, "run_all_checks", lambda _channel_dir: [result])

    code = doctor.main(["--apply", "--json", "--target", str(tmp_path)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    public_action = {"kind": "ai-exec", "cmd": "uv init"}
    assert payload["checks"] == [
        {
            "id": "uv_project",
            "status": "fail",
            "message": "uv project missing",
            "category": "bootstrap",
            "next_action": public_action,
            "data": {"reason": "uv_project_missing"},
        }
    ]
    assert payload["apply"] == {
        "stop_reason": "human_required",
        "check_id": "uv_project",
        "next_action": public_action,
        "executed": [],
    }
    assert "argv" not in payload["checks"][0]["next_action"]
    assert "auto_apply" not in payload["checks"][0]["next_action"]
    assert "argv" not in payload["apply"]["next_action"]
    assert "auto_apply" not in payload["apply"]["next_action"]
