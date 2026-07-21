"""infra/terraform/bootstrap と GCS backend 移行の構造テスト。"""

from __future__ import annotations

import re
from pathlib import Path

from tests.helpers.hcl import extract_block, read_file, strip_hcl_comments

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BOOTSTRAP_DIR = _REPO_ROOT / "infra" / "terraform" / "bootstrap"
_GCP_DIR = _REPO_ROOT / "infra" / "terraform" / "gcp"
_STREAMING_DIR = _REPO_ROOT / "infra" / "terraform" / "streaming"

_BOOTSTRAP_VERSIONS_TF = _BOOTSTRAP_DIR / "versions.tf"
_BOOTSTRAP_VARIABLES_TF = _BOOTSTRAP_DIR / "variables.tf"
_BOOTSTRAP_MAIN_TF = _BOOTSTRAP_DIR / "main.tf"
_BOOTSTRAP_OUTPUTS_TF = _BOOTSTRAP_DIR / "outputs.tf"
_BOOTSTRAP_TFVARS_EXAMPLE = _BOOTSTRAP_DIR / "terraform.tfvars.example"
_GCP_VARIABLES_TF = _GCP_DIR / "variables.tf"
_GCP_VERSIONS_TF = _GCP_DIR / "versions.tf"
_STREAMING_README = _STREAMING_DIR / "README.md"

_GOOGLE_PROVIDER_SOURCE = "hashicorp/google"
_STORAGE_API = "storage.googleapis.com"
_BOOTSTRAP_LOCATION = "asia-northeast1"
_TFSTATE_BUCKET_EXAMPLE = "youtube-automation-tfstate"


def test_google_stacks_use_validated_terraform_and_provider_series():
    for versions_tf in (_BOOTSTRAP_VERSIONS_TF, _GCP_VERSIONS_TF):
        text = strip_hcl_comments(read_file(versions_tf))
        terraform_block = extract_block(text, r"terraform")
        assert terraform_block is not None
        assert re.search(r'required_version\s*=\s*"~>\s*1\.15\.0"', terraform_block)

        google_block = extract_block(terraform_block, r"google")
        assert google_block is not None
        assert re.search(r'version\s*=\s*"~>\s*7\.40"', google_block)


def test_bootstrap_declares_google_provider():
    text = strip_hcl_comments(read_file(_BOOTSTRAP_VERSIONS_TF))
    terraform_block = extract_block(text, r"terraform")
    assert terraform_block is not None, "terraform block が存在しない"

    google_block = extract_block(terraform_block, r"google")
    assert google_block is not None, "required_providers.google が存在しない"
    assert re.search(rf'source\s*=\s*"{re.escape(_GOOGLE_PROVIDER_SOURCE)}"', google_block), (
        "google provider source が hashicorp/google でない"
    )

    provider_block = extract_block(text, r'provider\s+"google"')
    assert provider_block is not None, 'provider "google" が存在しない'
    assert re.search(r"project\s*=\s*var\.project_id", provider_block), (
        "provider.google.project が var.project_id を参照していない"
    )


def test_bootstrap_variables_define_bucket_contract():
    text = strip_hcl_comments(read_file(_BOOTSTRAP_VARIABLES_TF))

    project_block = extract_block(text, r'variable\s+"project_id"')
    assert project_block is not None, 'variable "project_id" が存在しない'
    assert not re.search(r"\bdefault\s*=", project_block), "project_id は必須入力にする"

    bucket_block = extract_block(text, r'variable\s+"bucket_name"')
    assert bucket_block is not None, 'variable "bucket_name" が存在しない'
    assert not re.search(r"\bdefault\s*=", bucket_block), "bucket_name は必須入力にする"

    location_block = extract_block(text, r'variable\s+"location"')
    assert location_block is not None, 'variable "location" が存在しない'
    assert re.search(rf'default\s*=\s*"{re.escape(_BOOTSTRAP_LOCATION)}"', location_block), (
        "location default が asia-northeast1 でない"
    )


def test_bootstrap_bucket_is_hardened_for_tfstate():
    text = strip_hcl_comments(read_file(_BOOTSTRAP_MAIN_TF))
    bucket_block = extract_block(text, r'resource\s+"google_storage_bucket"\s+"tfstate"')
    assert bucket_block is not None, 'resource "google_storage_bucket" "tfstate" が存在しない'

    assert re.search(r"name\s*=\s*var\.bucket_name", bucket_block), "bucket name が var.bucket_name でない"
    assert re.search(r"project\s*=\s*var\.project_id", bucket_block), "bucket project が var.project_id でない"
    assert re.search(r"location\s*=\s*var\.location", bucket_block), "bucket location が var.location でない"
    assert re.search(r"uniform_bucket_level_access\s*=\s*true", bucket_block), (
        "uniform bucket-level access が有効でない"
    )
    assert re.search(r'public_access_prevention\s*=\s*"enforced"', bucket_block), (
        "public access prevention が enforced でない"
    )

    versioning_block = extract_block(bucket_block, r"versioning")
    assert versioning_block is not None, "versioning block が存在しない"
    assert re.search(r"enabled\s*=\s*true", versioning_block), "versioning.enabled が true でない"

    lifecycle_block = extract_block(bucket_block, r"lifecycle_rule")
    assert lifecycle_block is not None, "lifecycle_rule が存在しない"
    assert re.search(r"age\s*=\s*30", lifecycle_block), "古い世代を 30 日で削除する条件が無い"
    assert re.search(r'with_state\s*=\s*"ARCHIVED"', lifecycle_block), "古い object 世代だけを対象にしていない"
    assert re.search(r'type\s*=\s*"Delete"', lifecycle_block), "lifecycle action が Delete でない"


def test_bootstrap_outputs_and_example_expose_bucket_name():
    outputs_text = strip_hcl_comments(read_file(_BOOTSTRAP_OUTPUTS_TF))
    output_block = extract_block(outputs_text, r'output\s+"bucket_name"')
    assert output_block is not None, 'output "bucket_name" が存在しない'
    assert re.search(r"value\s*=\s*google_storage_bucket\.tfstate\.name", output_block), (
        "bucket_name output が google_storage_bucket.tfstate.name でない"
    )

    tfvars_text = read_file(_BOOTSTRAP_TFVARS_EXAMPLE)
    assert f'bucket_name = "{_TFSTATE_BUCKET_EXAMPLE}"' in tfvars_text, (
        "terraform.tfvars.example に tfstate bucket 名の例が無い"
    )
    assert f'location    = "{_BOOTSTRAP_LOCATION}"' in tfvars_text, "terraform.tfvars.example に location 例が無い"


def test_gcp_module_enables_storage_api_for_bootstrap():
    text = read_file(_GCP_VARIABLES_TF)
    assert f'"{_STORAGE_API}"' in text, "gcp module の var.apis に storage.googleapis.com が無い"
    assert "cloudkms.googleapis.com" not in text, "今回の GCS backend は CMEK を使わないため KMS API は不要"


def test_streaming_readme_documents_executable_state_migration_commands():
    streaming_text = read_file(_STREAMING_README)

    assert "cd infra/terraform/bootstrap" in streaming_text, (
        "streaming README に bootstrap stack へ移動する移行コマンドが無い"
    )
    assert 'terraform init -backend-config="bucket=<bucket-name>" -migrate-state' in streaming_text, (
        "streaming README に remote backend への state 移行コマンドが無い"
    )
    assert "rm -f terraform.tfstate terraform.tfstate.backup" in streaming_text, (
        "streaming README にローカル tfstate 削除手順が無い"
    )
