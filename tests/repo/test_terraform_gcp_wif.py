"""読み取り専用 drift identity の Terraform 認可契約。"""

from __future__ import annotations

import re

from tests.helpers.hcl import extract_block, read_file
from tests.helpers.paths import REPO_ROOT

_GCP = REPO_ROOT / "infra" / "terraform" / "gcp"


def test_wif_accepts_only_owner_and_exact_main_subject():
    text = read_file(_GCP / "wif.tf")
    provider = extract_block(text, r'resource\s+"google_iam_workload_identity_pool_provider"\s+"github"')
    assert provider is not None
    assert '"google.subject" = "assertion.sub"' in provider
    assert 'assertion.repository_owner_id == \\"${var.github_repository_owner_id}\\"' in provider
    assert 'issuer_uri = "https://token.actions.githubusercontent.com"' in provider
    binding = extract_block(text, r'resource\s+"google_service_account_iam_member"\s+"github_main"')
    assert binding is not None
    assert re.search(r'role\s*=\s*"roles/iam.workloadIdentityUser"', binding)
    assert re.search(
        r'member\s*=\s*"principal://iam.googleapis.com/\$\{google_iam_workload_identity_pool.github.name\}/subject/repo:daiki-beppu/youtube-automation:ref:refs/heads/main"',
        binding,
    )
    assert "principalSet://" not in text


def test_drift_roles_allow_reads_without_broad_or_mutating_permissions():
    text = read_file(_GCP / "wif.tf")
    roles = set(re.findall(r'"(roles/[^"\s]+)"', text))
    assert roles == {
        "roles/iam.workloadIdentityUser",
        "roles/browser",
        "roles/serviceusage.serviceUsageViewer",
        "roles/iam.securityReviewer",
        "roles/iam.workloadIdentityPoolViewer",
    }
    permissions = set(re.findall(r'"(storage\.[^"\s]+)"', text))
    assert permissions == {"storage.objects.get", "storage.objects.list"}
    get_role = extract_block(text, r'resource\s+"google_project_iam_custom_role"\s+"state_get"')
    list_role = extract_block(text, r'resource\s+"google_project_iam_custom_role"\s+"state_list"')
    assert get_role is not None and list_role is not None
    assert re.search(r'permissions\s*=\s*\["storage.objects.get"\]', get_role)
    assert re.search(r'permissions\s*=\s*\["storage.objects.list"\]', list_role)


def test_state_get_is_limited_to_gcp_while_list_has_no_object_reads():
    text = read_file(_GCP / "wif.tf")
    get_binding = extract_block(text, r'resource\s+"google_storage_bucket_iam_member"\s+"drift_state_get"')
    list_binding = extract_block(text, r'resource\s+"google_storage_bucket_iam_member"\s+"drift_state_list"')
    assert get_binding is not None and list_binding is not None
    for binding in (get_binding, list_binding):
        assert re.search(r"bucket\s*=\s*var.tfstate_bucket", binding)
        assert re.search(r"member\s*=\s*google_service_account.drift.member", binding)
    assert re.search(r"role\s*=\s*google_project_iam_custom_role.state_get.name", get_binding)
    assert 'resource.name.startsWith(\\"projects/_/buckets/${var.tfstate_bucket}/objects/gcp/\\")' in get_binding
    assert re.search(r"role\s*=\s*google_project_iam_custom_role.state_list.name", list_binding)
    assert "condition" not in list_binding
