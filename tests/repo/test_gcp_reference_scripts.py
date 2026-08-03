"""Executable contracts for distributed GCP bootstrap/apply scripts."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.helpers.paths import REPO_ROOT

ROOT = REPO_ROOT
REFERENCES = ROOT / ".claude" / "skills" / "channel-new" / "references"


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _run(name: str, *args: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", str(REFERENCES / name), *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _gcloud_env(
    tmp_path: Path,
    *,
    project_exists: bool = True,
    authenticated: bool = True,
) -> tuple[dict[str, str], Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "gcloud-calls.txt"
    _write_executable(
        bin_dir / "gcloud",
        """#!/bin/bash
printf '%s\n' "$*" >> "$GCLOUD_CALLS"
case "$*" in
  "--version") echo "Google Cloud SDK fake" ;;
  "auth list"*) [[ "${GCLOUD_AUTH:-1}" == 1 ]] && echo "operator@example.test" ;;
  "projects describe"*) [[ "${PROJECT_EXISTS:-1}" == 1 ]] && echo "$3" || exit 1 ;;
  "services list"*) printf 'youtube.googleapis.com\n' ;;
  "projects get-iam-policy"*) printf '' ;;
esac
""",
    )
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "GCLOUD_CALLS": str(calls),
            "PROJECT_EXISTS": "1" if project_exists else "0",
            "GCLOUD_AUTH": "1" if authenticated else "0",
        }
    )
    return env, calls


def test_gcp_bootstrap_dry_run_observes_auth_billing_api_adc_and_iam_without_mutation(tmp_path: Path) -> None:
    env, calls = _gcloud_env(tmp_path)
    result = _run(
        "gcp-bootstrap.sh",
        "--dry-run",
        "--billing-account",
        "BILLING-1",
        "--adc-email",
        "adc@example.test",
        "project-one",
        cwd=tmp_path,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    output = result.stdout
    assert "gcloud beta billing projects link project-one --billing-account=BILLING-1" in output
    for api in (
        "youtubeanalytics.googleapis.com",
        "aiplatform.googleapis.com",
        "generativelanguage.googleapis.com",
    ):
        assert f"gcloud services enable {api} --project=project-one" in output
    assert "gcloud auth application-default login" in output
    assert "gcloud auth application-default set-quota-project project-one" in output
    assert "gcloud projects add-iam-policy-binding project-one" in output
    call_text = calls.read_text(encoding="utf-8")
    assert "auth list" in call_text
    assert "projects describe project-one" in call_text
    assert "config set project" not in call_text


def test_gcp_bootstrap_rejects_missing_cli_auth_and_project(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    env = os.environ.copy()
    env["PATH"] = str(empty)
    missing_cli = _run("gcp-bootstrap.sh", "--dry-run", "project", cwd=empty, env=env)
    assert missing_cli.returncode == 1
    assert "gcloud CLI" in missing_cli.stderr

    auth_dir = tmp_path / "auth"
    auth_dir.mkdir()
    auth_env, _ = _gcloud_env(auth_dir, authenticated=False)
    missing_auth = _run("gcp-bootstrap.sh", "--dry-run", "project", cwd=auth_dir, env=auth_env)
    assert missing_auth.returncode == 1
    assert "ログインしていません" in missing_auth.stderr

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    project_env, _ = _gcloud_env(project_dir, project_exists=False)
    missing_project = _run("gcp-bootstrap.sh", "--dry-run", "project", cwd=project_dir, env=project_env)
    assert missing_project.returncode == 1
    assert "--create" in missing_project.stderr


def _terraform_env(tmp_path: Path, *, fail_command: str = "") -> tuple[dict[str, str], Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    terraform_calls = tmp_path / "terraform-calls.txt"
    gcloud_calls = tmp_path / "gcloud-calls.txt"
    _write_executable(
        bin_dir / "terraform",
        """#!/bin/bash
printf '%s\n' "$*" >> "$TERRAFORM_CALLS"
[[ "$1" == "$FAIL_COMMAND" ]] && exit 17
if [[ "$*" == "output -raw oauth_console_url" ]]; then
  echo "https://console.example.test/oauth"
elif [[ "$*" == "output -raw project_id" ]]; then
  echo "project-one"
fi
""",
    )
    _write_executable(bin_dir / "gcloud", '#!/bin/bash\nprintf \'%s\\n\' "$*" >> "$GCLOUD_CALLS"\n')
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "TERRAFORM_CALLS": str(terraform_calls),
            "GCLOUD_CALLS": str(gcloud_calls),
            "FAIL_COMMAND": fail_command,
        }
    )
    return env, terraform_calls, gcloud_calls


def test_gcp_terraform_apply_observes_init_apply_outputs_and_adc(tmp_path: Path) -> None:
    tf_dir = tmp_path / "terraform"
    tf_dir.mkdir()
    env, terraform_calls, gcloud_calls = _terraform_env(tmp_path)

    result = _run(
        "gcp-terraform-apply.sh",
        "--tf-dir",
        str(tf_dir),
        "--auto-approve",
        cwd=tmp_path,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert terraform_calls.read_text(encoding="utf-8").splitlines() == [
        "init -upgrade",
        "apply -auto-approve",
        "output -raw oauth_console_url",
        "output -raw project_id",
    ]
    assert gcloud_calls.read_text(encoding="utf-8").strip() == (
        "auth application-default set-quota-project project-one"
    )
    assert "https://console.example.test/oauth" in result.stdout


@pytest.mark.parametrize("command", ["init", "apply"])
def test_gcp_terraform_apply_propagates_each_terraform_failure(tmp_path: Path, command: str) -> None:
    tf_dir = tmp_path / "terraform"
    tf_dir.mkdir()
    env, calls, _ = _terraform_env(tmp_path, fail_command=command)

    result = _run("gcp-terraform-apply.sh", "--tf-dir", str(tf_dir), cwd=tmp_path, env=env)

    assert result.returncode == 17
    lines = calls.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "init -upgrade"
    if command == "init":
        assert lines == ["init -upgrade"]
    else:
        assert lines == ["init -upgrade", "apply"]
