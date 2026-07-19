"""yt-doctor --apply の公開 CLI 契約テスト。"""

from __future__ import annotations

import json
import os
import shlex
from pathlib import Path

import pytest

from youtube_automation.cli import doctor


def _result(check_id: str, status: str = "ok", next_action: dict | None = None) -> doctor.CheckResult:
    return doctor.CheckResult(
        id=check_id,
        status=status,
        message=f"{check_id}: {status}",
        next_action=next_action,
    )


def _ai_action(*argv: str) -> dict:
    return {"kind": "ai-exec", "cmd": shlex.join(argv), "argv": list(argv)}


def test_apply_completed_is_idempotent(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(doctor, "run_all_checks", lambda _channel_dir: [_result("ready")])

    code = doctor.main(["--apply", "--json", "--target", str(tmp_path)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["apply"] == {
        "stop_reason": "completed",
        "check_id": None,
        "next_action": None,
        "executed": [],
    }
    assert payload["summary"]["next_check_id"] is None


def test_apply_without_json_flag_still_emits_machine_readable_summary(monkeypatch, tmp_path: Path, capsys) -> None:
    action = {"kind": "human", "instructions": "login yourself"}
    monkeypatch.setattr(
        doctor,
        "run_all_checks",
        lambda _channel_dir: [_result("gcloud_account", "fail", action)],
    )

    code = doctor.main(["--apply", "--target", str(tmp_path)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["apply"]["stop_reason"] == "human_required"
    assert payload["apply"]["next_action"] == action


def test_apply_executes_ai_step_and_rediagnoses(monkeypatch, tmp_path: Path, capsys) -> None:
    diagnoses = iter(
        [
            [_result("skills_synced", "fail", _ai_action("uv", "run", "yt-skills", "sync"))],
            [_result("skills_synced")],
        ]
    )
    commands: list[tuple[list[str], Path]] = []
    monkeypatch.setattr(doctor, "run_all_checks", lambda _channel_dir: next(diagnoses))
    monkeypatch.setattr(
        doctor,
        "_run_apply_command",
        lambda argv, cwd: commands.append((argv, cwd)) or (0, "synced", ""),
        raising=False,
    )

    code = doctor.main(["--apply", "--json", "--target", str(tmp_path)])

    assert code == 0
    assert commands == [(["uv", "run", "yt-skills", "sync"], tmp_path)]
    payload = json.loads(capsys.readouterr().out)
    assert payload["apply"] == {
        "stop_reason": "completed",
        "check_id": None,
        "next_action": None,
        "executed": [
            {
                "check_id": "skills_synced",
                "cmd": "uv run yt-skills sync",
                "returncode": 0,
            }
        ],
    }


def test_apply_never_executes_interactive_auth_even_if_mislabeled(monkeypatch, tmp_path: Path, capsys) -> None:
    action = _ai_action("gcloud", "auth", "application-default", "login")
    monkeypatch.setattr(doctor, "run_all_checks", lambda _channel_dir: [_result("adc", "fail", action)])
    monkeypatch.setattr(
        doctor,
        "_run_apply_command",
        lambda _argv, _cwd: (_ for _ in ()).throw(AssertionError("interactive auth must not run")),
    )

    code = doctor.main(["--apply", "--json", "--target", str(tmp_path)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["apply"]["stop_reason"] == "human_required"
    assert payload["apply"]["check_id"] == "adc"
    assert payload["apply"]["next_action"] == {
        "kind": "ai-exec",
        "cmd": "gcloud auth application-default login",
    }


def test_apply_stops_for_project_decision_without_project_id(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(
        doctor,
        "run_all_checks",
        lambda _channel_dir: [_result("gcp_project", "fail")],
    )

    code = doctor.main(["--apply", "--json", "--target", str(tmp_path)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["apply"]["stop_reason"] == "decision_required"
    assert payload["apply"]["check_id"] == "gcp_project"
    assert payload["apply"]["next_action"] == {
        "kind": "decision",
        "flag": "--project-id",
    }


def test_apply_uses_project_id_then_continues(monkeypatch, tmp_path: Path, capsys) -> None:
    commands: list[tuple[list[str], Path]] = []
    (tmp_path / ".env").write_text("GOOGLE_CLOUD_PROJECT=stale-project\n", encoding="utf-8")
    diagnosis_count = 0

    def diagnose(_channel_dir: Path) -> list[doctor.CheckResult]:
        nonlocal diagnosis_count
        diagnosis_count += 1
        if diagnosis_count == 1:
            assert "GOOGLE_CLOUD_PROJECT" not in os.environ
            assert doctor._project_id_for(tmp_path) == "stale-project"
            return [_result("gcp_project")]
        assert os.environ["GOOGLE_CLOUD_PROJECT"] == "yt-example"
        assert doctor._project_id_for(tmp_path) == "yt-example"
        return [_result("gcp_project")]

    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.setattr(doctor, "run_all_checks", diagnose)
    monkeypatch.setattr(
        doctor,
        "_run_apply_command",
        lambda argv, cwd: commands.append((argv, cwd)) or (0, "", ""),
    )

    code = doctor.main(["--apply", "--json", "--project-id", "yt-example", "--target", str(tmp_path)])

    assert code == 0
    assert commands == [(["gcloud", "config", "set", "project", "yt-example"], tmp_path)]
    assert "GOOGLE_CLOUD_PROJECT" not in os.environ
    payload = json.loads(capsys.readouterr().out)
    assert payload["apply"]["stop_reason"] == "completed"
    assert payload["apply"]["executed"] == [
        {
            "check_id": "gcp_project",
            "cmd": "gcloud config set project yt-example",
            "returncode": 0,
        }
    ]


def test_project_id_waits_for_earlier_human_step(monkeypatch, tmp_path: Path, capsys) -> None:
    human_action = doctor._human_auth_action(
        ["gcloud", "auth", "login"],
        "AI がコマンドを起動し、人間がブラウザ認証する",
    )
    monkeypatch.setattr(
        doctor,
        "run_all_checks",
        lambda _channel_dir: [
            _result("gcloud_account", "fail", human_action),
            _result("gcp_project", "fail"),
        ],
    )
    monkeypatch.setattr(
        doctor,
        "_run_apply_command",
        lambda _argv, _cwd: (_ for _ in ()).throw(AssertionError("project must wait")),
    )

    code = doctor.main(["--apply", "--project-id", "yt-example", "--target", str(tmp_path)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["apply"]["stop_reason"] == "human_required"
    assert payload["apply"]["check_id"] == "gcloud_account"
    assert payload["apply"]["next_action"] == {
        "kind": "human",
        "reason": "authentication",
        "cmd": "gcloud auth login",
        "execution_owner": "ai-or-setup",
        "human_role": "browser-authentication",
        "instructions": "AI がコマンドを起動し、人間がブラウザ認証する",
    }
    assert payload["apply"]["executed"] == []


def test_project_id_does_not_mutate_when_project_check_is_already_ok(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "yt-example")
    monkeypatch.setattr(
        doctor,
        "run_all_checks",
        lambda _channel_dir: [_result("gcp_project")],
    )
    monkeypatch.setattr(
        doctor,
        "_run_apply_command",
        lambda _argv, _cwd: (_ for _ in ()).throw(AssertionError("idempotent apply must not mutate")),
    )

    code = doctor.main(["--apply", "--project-id", "yt-example", "--target", str(tmp_path)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["apply"]["stop_reason"] == "completed"
    assert payload["apply"]["executed"] == []


def test_apply_stops_for_billing_decision_without_account(monkeypatch, tmp_path: Path, capsys) -> None:
    action = {
        "kind": "ai-exec",
        "cmd": "gcloud beta billing projects link yt-example --billing-account=<ID>",
    }
    monkeypatch.setattr(
        doctor,
        "run_all_checks",
        lambda _channel_dir: [_result("billing_linked", "fail", action)],
    )
    monkeypatch.setattr(
        doctor,
        "_run_apply_command",
        lambda _argv, _cwd: (_ for _ in ()).throw(AssertionError("billing decision must not run")),
    )

    code = doctor.main(["--apply", "--json", "--target", str(tmp_path)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["apply"]["stop_reason"] == "decision_required"
    assert payload["apply"]["check_id"] == "billing_linked"
    assert payload["apply"]["next_action"] == {
        "kind": "decision",
        "flag": "--billing-account",
    }


def test_apply_uses_billing_account_then_continues(monkeypatch, tmp_path: Path, capsys) -> None:
    action = {
        "kind": "ai-exec",
        "cmd": "gcloud beta billing projects link yt-example --billing-account=<ID>",
    }
    diagnoses = iter(
        [
            [_result("billing_linked", "fail", action)],
            [_result("billing_linked")],
        ]
    )
    commands: list[tuple[list[str], Path]] = []
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "yt-example")
    monkeypatch.setattr(doctor, "run_all_checks", lambda _channel_dir: next(diagnoses))
    monkeypatch.setattr(
        doctor,
        "_run_apply_command",
        lambda argv, cwd: commands.append((argv, cwd)) or (0, "", ""),
    )

    code = doctor.main(
        [
            "--apply",
            "--json",
            "--billing-account",
            "ABCDEF-123456-ABCDEF",
            "--target",
            str(tmp_path),
        ]
    )

    assert code == 0
    assert commands == [
        (
            [
                "gcloud",
                "beta",
                "billing",
                "projects",
                "link",
                "yt-example",
                "--billing-account=ABCDEF-123456-ABCDEF",
            ],
            tmp_path,
        )
    ]
    payload = json.loads(capsys.readouterr().out)
    assert payload["apply"]["stop_reason"] == "completed"
    assert payload["apply"]["executed"][0]["cmd"] == (
        "gcloud beta billing projects link yt-example --billing-account=ABCDEF-123456-ABCDEF"
    )


def test_apply_stops_with_failed_command_details(monkeypatch, tmp_path: Path, capsys) -> None:
    action = _ai_action("gcloud", "services", "enable", "example.googleapis.com")
    monkeypatch.setattr(
        doctor,
        "run_all_checks",
        lambda _channel_dir: [_result("apis_enabled", "fail", action)],
    )
    monkeypatch.setattr(
        doctor,
        "_run_apply_command",
        lambda _argv, _cwd: (9, "", "permission denied"),
    )

    code = doctor.main(["--apply", "--json", "--target", str(tmp_path)])

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["apply"]["stop_reason"] == "command_failed"
    assert payload["apply"]["check_id"] == "apis_enabled"
    assert payload["apply"]["cmd"] == action["cmd"]
    assert payload["apply"]["stderr"] == "permission denied"


def test_apply_treats_oauth_browser_flow_as_human_step(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(
        doctor,
        "run_all_checks",
        lambda channel_dir: [doctor.check_oauth_token(channel_dir)],
    )
    monkeypatch.setattr(
        doctor,
        "_run_apply_command",
        lambda _argv, _cwd: (_ for _ in ()).throw(AssertionError("OAuth browser flow must not run")),
    )

    code = doctor.main(["--apply", "--json", "--target", str(tmp_path)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["apply"]["stop_reason"] == "human_required"
    assert payload["apply"]["check_id"] == "oauth_token"
    assert payload["apply"]["next_action"]["kind"] == "human"


def test_apply_stops_when_successful_command_makes_no_progress(monkeypatch, tmp_path: Path, capsys) -> None:
    action = _ai_action("uv", "run", "yt-skills", "sync")
    monkeypatch.setattr(
        doctor,
        "run_all_checks",
        lambda _channel_dir: [_result("skills_synced", "fail", action)],
    )
    attempts = 0

    def run_once(_argv: list[str], _cwd: Path) -> tuple[int, str, str]:
        nonlocal attempts
        attempts += 1
        if attempts > 1:
            raise AssertionError("unchanged command must not be repeated")
        return 0, "", ""

    monkeypatch.setattr(doctor, "_run_apply_command", run_once)

    code = doctor.main(["--apply", "--json", "--target", str(tmp_path)])

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["apply"]["stop_reason"] == "command_failed"
    assert payload["apply"]["check_id"] == "skills_synced"
    assert "再診断後も未解決" in payload["apply"]["stderr"]


def test_apply_does_not_execute_legacy_prose_command(monkeypatch, tmp_path: Path, capsys) -> None:
    action = {
        "kind": "ai-exec",
        "cmd": ".claude/skills/channel-new/references/gcp-bootstrap.sh <project-id> を実行する",
    }
    monkeypatch.setattr(
        doctor,
        "run_all_checks",
        lambda _channel_dir: [_result("env_file", "fail", action)],
    )
    monkeypatch.setattr(
        doctor,
        "_run_apply_command",
        lambda _argv, _cwd: (_ for _ in ()).throw(AssertionError("prose must not run")),
    )

    code = doctor.main(["--apply", "--json", "--target", str(tmp_path)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["apply"]["stop_reason"] == "human_required"
    assert payload["apply"]["check_id"] == "env_file"


def test_apply_creates_missing_env_defaults_and_rediagnoses(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(
        doctor,
        "run_all_checks",
        lambda channel_dir: [doctor.check_env_file(channel_dir)],
    )

    def run_env_action(argv: list[str], cwd: Path) -> tuple[int, str, str]:
        assert argv == [
            "uv",
            "run",
            "yt-doctor",
            "--write-env-defaults",
            "--target",
            ".",
        ]
        return doctor.write_env_defaults(cwd), "", ""

    monkeypatch.setattr(doctor, "_run_apply_command", run_env_action)

    code = doctor.main(["--apply", "--json", "--target", str(tmp_path)])

    assert code == 0
    assert (tmp_path / ".env").read_text(encoding="utf-8") == (
        "GOOGLE_CLOUD_LOCATION=us-central1\nGOOGLE_GENAI_USE_VERTEXAI=true\n"
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["apply"]["stop_reason"] == "completed"
    assert payload["apply"]["executed"][0]["cmd"] == ("uv run yt-doctor --write-env-defaults --target .")


def test_apply_keeps_pre_install_bootstrap_out_of_scope(monkeypatch, tmp_path: Path, capsys) -> None:
    action = _ai_action("uv", "init")
    action["auto_apply"] = False
    monkeypatch.setattr(
        doctor,
        "run_all_checks",
        lambda _channel_dir: [_result("uv_project", "fail", action)],
    )
    monkeypatch.setattr(
        doctor,
        "_run_apply_command",
        lambda _argv, _cwd: (_ for _ in ()).throw(AssertionError("bootstrap must stay in skill")),
    )

    code = doctor.main(["--apply", "--json", "--target", str(tmp_path)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["apply"]["stop_reason"] == "human_required"
    assert payload["apply"]["check_id"] == "uv_project"


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--project-id", "--quiet"),
        ("--project-id", "INVALID_PROJECT"),
        ("--billing-account", "account;rm"),
    ],
)
def test_apply_rejects_invalid_decision_values(monkeypatch, flag: str, value: str) -> None:
    monkeypatch.setattr(
        doctor,
        "_run_apply_command",
        lambda _argv, _cwd: (_ for _ in ()).throw(AssertionError("invalid value must not run")),
    )
    with pytest.raises(SystemExit) as error:
        doctor.main(["--apply", flag, value])

    assert error.value.code == 2
