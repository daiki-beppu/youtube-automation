"""Terraform 静的ゲートのバージョン互換性・認証不要契約 (#4930)。"""

from __future__ import annotations

import re

import pytest
import yaml

from tests.helpers.hcl import extract_block, read_file, strip_hcl_comments
from tests.helpers.paths import REPO_ROOT

_WORKFLOW = REPO_ROOT / ".github/workflows/terraform-static.yml"
_STACKS = ("bootstrap", "gcp", "r2", "streaming")


@pytest.mark.parametrize("stack", _STACKS)
def test_workflow_terraform_versions_satisfy_stack_requirement(stack: str) -> None:
    document = yaml.load(read_file(_WORKFLOW), Loader=yaml.BaseLoader)
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
    document = yaml.load(read_file(_WORKFLOW), Loader=yaml.BaseLoader)
    assert document["permissions"] == {"contents": "read"}
    for job in document["jobs"].values():
        if "permissions" in job:
            assert job["permissions"] == {"contents": "read"}
        for line in yaml.dump(job).splitlines():
            assert not re.search(r"\bsecrets\s*[.\[]|\bid-token\b", line, re.IGNORECASE)
    for line in yaml.dump(document.get("env", {})).splitlines():
        assert not re.search(r"\bsecrets\s*[.\[]", line, re.IGNORECASE)
