"""公開 setup 操作と上流 Terraform が channel dotenv を管理しない契約。"""

from __future__ import annotations

import re
import subprocess

import pytest

from tests.helpers.paths import REPO_ROOT
from youtube_automation.commands.channel.channel_init import main as channel_init_main

ROOT = REPO_ROOT
SETUP_REFERENCES = ROOT / ".claude" / "skills" / "setup" / "references"


def test_channel_init_public_operation_does_not_generate_env(tmp_path) -> None:
    result = channel_init_main(
        [
            "--target",
            str(tmp_path),
            "--short",
            "TEST",
            "--name",
            "Test Channel",
        ]
    )

    assert result == 0
    assert not (tmp_path / ".env").exists()


@pytest.mark.parametrize("script_name", ("gcp-bootstrap.sh",))
def test_gcp_setup_scripts_reject_env_file_without_generating_it(tmp_path, script_name: str) -> None:
    env_file = tmp_path / ".env"
    result = subprocess.run(
        ["bash", str(SETUP_REFERENCES / script_name), "--env-file", str(env_file)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "未知のオプション: --env-file" in result.stderr
    assert not env_file.exists()


def test_terraform_public_schema_has_no_dotenv_output_or_location_input() -> None:
    canonical = ROOT / "infra" / "terraform" / "gcp"
    outputs = set(re.findall(r'(?m)^output\s+"([^"]+)"', (canonical / "outputs.tf").read_text(encoding="utf-8")))
    variables = set(re.findall(r'(?m)^variable\s+"([^"]+)"', (canonical / "variables.tf").read_text(encoding="utf-8")))

    assert outputs == {
        "project_id",
        "oauth_console_url",
        "enabled_apis",
        "wif_provider_name",
        "drift_service_account_email",
    }
    assert variables == {
        "project_id",
        "project_name",
        "billing_account",
        "org_id",
        "folder_id",
        "adc_email",
        "apis",
        "github_repository_owner_id",
        "tfstate_bucket",
    }
