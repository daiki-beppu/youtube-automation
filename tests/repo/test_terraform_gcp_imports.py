"""#4929 の GCP import と共有プロジェクト保護の設定契約。"""

import re

from tests.helpers.hcl import extract_block, read_file, strip_hcl_comments
from tests.helpers.paths import REPO_ROOT
from youtube_automation.application.channel_readiness.checks import REQUIRED_APIS

_GCP = REPO_ROOT / "infra/terraform/gcp"


def test_shared_project_manages_billing_with_two_deletion_guards():
    project = extract_block(
        strip_hcl_comments(read_file(_GCP / "main.tf")),
        r'resource\s+"google_project"\s+"this"',
    )
    assert project is not None
    assert re.search(r'deletion_policy\s*=\s*"PREVENT"', project)
    assert re.search(r"billing_account\s*=\s*var\.billing_account\b", project)
    lifecycle = extract_block(project, r"lifecycle")
    assert lifecycle is not None
    assert re.search(r"prevent_destroy\s*=\s*true", lifecycle)
    assert not re.search(r"\b(count|for_each)\s*=", project)


def test_personal_inputs_are_required_and_redacted():
    variables = strip_hcl_comments(read_file(_GCP / "variables.tf"))
    for name in ("billing_account", "adc_email"):
        variable = extract_block(variables, rf'variable\s+"{name}"')
        assert variable is not None
        assert re.search(r"sensitive\s*=\s*true", variable)
        assert not re.search(r"\bdefault\s*=", variable)


def test_managed_apis_cover_doctor_and_the_state_backend():
    apis = extract_block(strip_hcl_comments(read_file(_GCP / "variables.tf")), r'variable\s+"apis"')
    assert apis is not None
    default = re.search(r"default\s*=\s*\[([^]]*)\]", apis)
    assert default is not None
    services = set(re.findall(r'"([^\"]+)"', default.group(1)))
    assert len(services) == 6
    assert services >= set(REQUIRED_APIS) | {"storage.googleapis.com"}


def test_imports_adopt_only_the_eight_existing_resources():
    imports = strip_hcl_comments(read_file(_GCP / "imports.tf"))
    blocks = re.findall(r"\bimport\s*\{(.*?)^\}", imports, re.MULTILINE | re.DOTALL)
    assert len(blocks) == 8
    actual = {}
    for block in blocks:
        target = re.search(r"^\s*to\s*=\s*(.+)$", block, re.MULTILINE)
        identifier = re.search(r'^\s*id\s*=\s*"(.+)"$', block, re.MULTILINE)
        assert target is not None
        assert identifier is not None
        actual[target.group(1).strip()] = identifier.group(1)
    apis = set(REQUIRED_APIS) | {"storage.googleapis.com"}
    expected = {
        "google_project.this": "projects/${var.project_id}",
        "google_project_iam_member.aiplatform_user": ("${var.project_id} roles/aiplatform.user user:${var.adc_email}"),
    }
    expected.update({f'google_project_service.apis["{api}"]': "${var.project_id}/" + api for api in apis})
    assert actual == expected
