"""公開 setup 操作と上流 Terraform が channel dotenv を管理しない契約。"""

from __future__ import annotations

import re

from tests.helpers.paths import REPO_ROOT
from youtube_automation.commands.channel.channel_init import main as channel_init_main

ROOT = REPO_ROOT


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
