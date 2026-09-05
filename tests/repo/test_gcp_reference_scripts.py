"""Executable contracts for distributed GCP bootstrap scripts."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tests.helpers.paths import REPO_ROOT

ROOT = REPO_ROOT
REFERENCES = ROOT / ".claude" / "skills" / "setup" / "references"
GCP_ASSET_NAMES = {
    "gcp-bootstrap.md",
    "gcp-bootstrap.sh",
}


def test_setup_owns_the_complete_distributed_gcp_asset_inventory() -> None:
    actual = {
        path.relative_to(REFERENCES).as_posix()
        for path in REFERENCES.rglob("*")
        if path.is_file()
        and (path.name.startswith("gcp-") or path.suffix == ".tf" or path.name.startswith("terraform"))
    }
    owners = {
        path.relative_to(ROOT / ".claude" / "skills").parts[0]
        for path in (ROOT / ".claude" / "skills").rglob("*")
        if path.is_file() and path.name.startswith("gcp-")
    }

    assert actual == GCP_ASSET_NAMES
    assert owners == {"setup"}


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
