"""Terraform 静的ゲートのバージョン互換性・認証不要契約 (#4930)。"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from tests.helpers.hcl import extract_block, read_file, strip_hcl_comments
from tests.helpers.paths import REPO_ROOT

_WORKFLOW = REPO_ROOT / ".github/workflows/terraform-static.yml"
_DRIFT_WORKFLOW = REPO_ROOT / ".github/workflows/terraform-drift.yml"
_DRIFT_SCRIPT = REPO_ROOT / ".github/scripts/terraform-drift.sh"
_STACKS = ("bootstrap", "gcp", "r2", "streaming")


def _load_workflow(path: Path) -> dict[str, object]:
    return yaml.load(read_file(path), Loader=yaml.BaseLoader)


@pytest.mark.parametrize("stack", _STACKS)
def test_workflow_terraform_versions_satisfy_stack_requirement(stack: str) -> None:
    document = _load_workflow(_WORKFLOW)
    versions = [
        step["with"]["terraform_version"]
        for job in document["jobs"].values()
        for step in job["steps"]
        if step.get("uses", "").startswith("hashicorp/setup-terraform@")
    ]
    assert versions, "Terraform installer が必要"
    terraform = extract_block(
        strip_hcl_comments(read_file(REPO_ROOT / "infra/terraform" / stack / "versions.tf")),
        r"terraform",
    )
    assert terraform is not None
    requirement = re.search(r'required_version\s*=\s*"~>\s*(\d+)\.(\d+)\.(\d+)"', terraform)
    assert requirement is not None, "stack は patch 系列の pessimistic constraint を宣言する"
    minimum = tuple(map(int, requirement.groups()))
    upper = (minimum[0], minimum[1] + 1, 0)
    for version in versions:
        assert re.fullmatch(r"\d+\.\d+\.\d+", version), "patch version を明記する"
        assert minimum <= tuple(map(int, version.split("."))) < upper


def test_static_workflow_requires_no_credentials() -> None:
    document = _load_workflow(_WORKFLOW)
    assert document["permissions"] == {"contents": "read"}
    for job in document["jobs"].values():
        if "permissions" in job:
            assert job["permissions"] == {"contents": "read"}
        for line in yaml.dump(job).splitlines():
            assert not re.search(r"\bsecrets\s*[.\[]|\bid-token\b", line, re.IGNORECASE)
    for line in yaml.dump(document.get("env", {})).splitlines():
        assert not re.search(r"\bsecrets\s*[.\[]", line, re.IGNORECASE)


def test_drift_runs_only_on_main_without_write_permissions() -> None:
    document = _load_workflow(_DRIFT_WORKFLOW)
    assert set(document["on"]) == {"schedule", "workflow_dispatch", "push"}
    assert document["on"]["push"]["branches"] == ["main"]
    assert "infra/terraform/gcp/**" in document["on"]["push"]["paths"]
    assert len(document["on"]["schedule"]) == 1
    assert document["on"]["schedule"][0]["cron"].split()[2:] == ["*", "*", "*"]
    assert document["permissions"] == {"contents": "read", "id-token": "write"}
    assert document["concurrency"]["group"]
    for job in document["jobs"].values():
        assert job["if"] == "github.ref == 'refs/heads/main'"
        assert "permissions" not in job
        for step in job["steps"]:
            assert not re.search(r"\bterraform\s+apply\b", step.get("run", ""))
    assert not re.search(r"\bterraform\s+apply\b", read_file(_DRIFT_SCRIPT))


def test_drift_credentials_are_injected_from_secrets() -> None:
    job = _load_workflow(_DRIFT_WORKFLOW)["jobs"]["drift"]
    variables = read_file(REPO_ROOT / "infra/terraform/gcp/variables.tf")
    for name in re.findall(r'variable "([^"]+)"', variables):
        block = extract_block(variables, rf'variable "{name}"')
        assert block is not None
        if re.search(r"\bdefault\s*=", block):
            continue
        value = job["env"][f"TF_VAR_{name}"]
        assert re.fullmatch(r"\$\{\{ secrets\.\w+ }}", value)
    for name in ("TFSTATE_BUCKET", "DISCORD_WEBHOOK_URL"):
        assert re.fullmatch(r"\$\{\{ secrets\.\w+ }}", job["env"][name])
    auth = next(step for step in job["steps"] if step.get("uses", "").startswith("google-github-actions/auth@"))
    for name in ("workload_identity_provider", "service_account"):
        assert re.fullmatch(r"\$\{\{ secrets\.\w+ }}", auth["with"][name])
