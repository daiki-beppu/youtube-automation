"""infra/terraform/streaming の Terraform 構成のスペック準拠テスト。

issue #123 / #124 の order.md と plan.md に基づき、以下を検証する:

- ``versions.tf``: ``vultr/vultr`` provider 宣言と provider ブロック
- ``variables.tf``: 5 変数の型/default/sensitive
- ``main.tf``: ``vultr_ssh_key`` + ``vultr_instance`` の構造と紐付け、
  ``user_data`` の templatefile 連鎖（#124）
- ``outputs.tf``: ``instance_ip`` / ``instance_id`` の expose
- ``terraform.tfvars.example``: secret を平文で含まない
- ルート ``.gitignore``: Terraform 系の ignore エントリ
- ``cloud-init.yaml``: package_update / packages / runcmd / write_files / daemon-reload (#124)
- ``templates/youtube-stream.service.tftpl``: 11h+1h 断続制御を含む systemd unit (#124)

terraform バイナリに依存せず、``.tf`` / ``.yaml`` / ``.tftpl`` ファイルのテキストを
正規表現で構造検証する。実 ``terraform validate`` / ``apply`` は手動検証。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from tests.helpers.hcl import extract_block, read_file, strip_hcl_comments

# ---------- パス定数 ----------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_STREAMING_DIR = _REPO_ROOT / "infra" / "terraform" / "streaming"

_VERSIONS_TF = _STREAMING_DIR / "versions.tf"
_VARIABLES_TF = _STREAMING_DIR / "variables.tf"
_MAIN_TF = _STREAMING_DIR / "main.tf"
_OUTPUTS_TF = _STREAMING_DIR / "outputs.tf"
_TFVARS_EXAMPLE = _STREAMING_DIR / "terraform.tfvars.example"
_ROOT_GITIGNORE = _REPO_ROOT / ".gitignore"
_CLOUD_INIT_YAML = _STREAMING_DIR / "cloud-init.yaml"
_SYSTEMD_TFTPL = _STREAMING_DIR / "templates" / "youtube-stream.service.tftpl"
_ENV_TFTPL = _STREAMING_DIR / "templates" / "youtube-stream.env.tftpl"
_STREAMING_README = _STREAMING_DIR / "README.md"
_STREAMING_SKILL = _REPO_ROOT / ".claude" / "skills" / "streaming" / "SKILL.md"

_SCRIPTS_STREAMING_DIR = _REPO_ROOT / ".claude" / "skills" / "streaming" / "references"
_SWAP_VIDEO_SCRIPT = _SCRIPTS_STREAMING_DIR / "swap_video.sh"
_RUN_FFMPEG_SCRIPT = _SCRIPTS_STREAMING_DIR / "run-ffmpeg.sh"

_TFSTATE_BACKEND_BUCKET = "youtube-automation-tfstate"
_TFSTATE_BACKEND_KEY = "streaming/terraform.tfstate"
_TFSTATE_BACKEND_REGION = "ap-northeast-1"
_TFSTATE_BACKEND_KMS_KEY_ID = "alias/tfstate"
_TFSTATE_BACKEND_LOCK_TABLE = "tfstate-lock"


# ---------- ヘルパー ----------


def _extract_yaml_packages_block(text: str) -> str | None:
    """``packages:`` キー直下のリストブロック（インデント行の連続）を 1 つ抜き出す。

    ``packages:`` 行から、次のトップレベルキー（インデント無し行）または EOF までを
    1 つのテキストとして返す。`cloud-init.yaml` の `- ffmpeg` / `- unattended-upgrades`
    などのアイテム判定に使う。マッチしない場合は ``None``。
    """
    match = re.search(
        r"^packages:\s*\n((?:[ \t]+.*\n)+)",
        text,
        flags=re.MULTILINE,
    )
    return match.group(1) if match else None


# ============================================================================
# versions.tf
# ============================================================================


class TestVersionsTf:
    """``versions.tf`` の terraform / required_providers / provider 宣言。"""

    def test_required_version_is_at_least_1_5(self):
        """Given versions.tf
        When terraform ブロックを読む
        Then required_version は ">= 1.5" を含む（既存 gcp/versions.tf と同じ最低保証）。
        """
        text = strip_hcl_comments(read_file(_VERSIONS_TF))
        terraform_block = extract_block(text, r"terraform")
        assert terraform_block is not None, "terraform { ... } ブロックが存在しない"
        assert re.search(r'required_version\s*=\s*"[^"]*>=\s*1\.5', terraform_block), (
            "required_version が >= 1.5 を含んでいない"
        )

    def test_backend_uses_encrypted_s3_remote_state(self):
        """Given versions.tf
        When terraform backend を読む
        Then S3 backend は KMS 暗号化と DynamoDB lock を宣言している。
        """
        text = strip_hcl_comments(read_file(_VERSIONS_TF))
        terraform_block = extract_block(text, r"terraform")
        assert terraform_block is not None, "terraform { ... } ブロックが存在しない"
        backend_block = extract_block(terraform_block, r'backend\s+"s3"')
        assert backend_block is not None, 'backend "s3" ブロックが存在しない'
        assert re.search(rf'bucket\s*=\s*"{re.escape(_TFSTATE_BACKEND_BUCKET)}"', backend_block), (
            "S3 backend bucket が tfstate 専用 bucket でない"
        )
        assert re.search(rf'key\s*=\s*"{re.escape(_TFSTATE_BACKEND_KEY)}"', backend_block), (
            "S3 backend key が streaming/terraform.tfstate でない"
        )
        assert re.search(rf'region\s*=\s*"{re.escape(_TFSTATE_BACKEND_REGION)}"', backend_block), (
            "S3 backend region が ap-northeast-1 でない"
        )
        assert re.search(r'encrypt\s*=\s*true', backend_block), "S3 backend encrypt = true が宣言されていない"
        assert re.search(rf'kms_key_id\s*=\s*"{re.escape(_TFSTATE_BACKEND_KMS_KEY_ID)}"', backend_block), (
            "S3 backend kms_key_id が alias/tfstate でない"
        )
        assert re.search(rf'dynamodb_table\s*=\s*"{re.escape(_TFSTATE_BACKEND_LOCK_TABLE)}"', backend_block), (
            "S3 backend dynamodb_table が tfstate-lock でない"
        )

    def test_required_providers_declares_vultr_source(self):
        """Given versions.tf
        When required_providers ブロックを読む
        Then vultr.source = "vultr/vultr" が宣言されている。
        """
        text = strip_hcl_comments(read_file(_VERSIONS_TF))
        terraform_block = extract_block(text, r"terraform")
        assert terraform_block is not None
        rp_block = extract_block(terraform_block, r"required_providers")
        assert rp_block is not None, "required_providers ブロックが存在しない"
        vultr_block = extract_block(rp_block, r"vultr")
        assert vultr_block is not None, "required_providers.vultr が宣言されていない"
        assert re.search(r'source\s*=\s*"vultr/vultr"', vultr_block), (
            'required_providers.vultr.source が "vultr/vultr" でない'
        )

    def test_required_providers_vultr_version_at_least_2(self):
        """Given versions.tf
        When required_providers.vultr.version を読む
        Then ">= 2" を含む制約が宣言されている（order.md「>= 2.x」）。
        """
        text = strip_hcl_comments(read_file(_VERSIONS_TF))
        terraform_block = extract_block(text, r"terraform")
        assert terraform_block is not None
        rp_block = extract_block(terraform_block, r"required_providers")
        assert rp_block is not None
        vultr_block = extract_block(rp_block, r"vultr")
        assert vultr_block is not None
        assert re.search(r'version\s*=\s*"[^"]*>=\s*2', vultr_block), (
            "required_providers.vultr.version が >= 2 を満たしていない"
        )

    def test_provider_vultr_block_uses_var_api_key(self):
        """Given versions.tf
        When provider "vultr" ブロックを読む
        Then api_key = var.vultr_api_key が結線されている。

        secret を hardcode せず変数経由で受け取る最重要要件。
        """
        text = strip_hcl_comments(read_file(_VERSIONS_TF))
        provider_block = extract_block(text, r'provider\s+"vultr"')
        assert provider_block is not None, 'provider "vultr" ブロックが存在しない'
        assert re.search(r"api_key\s*=\s*var\.vultr_api_key", provider_block), (
            "provider.vultr.api_key が var.vultr_api_key を参照していない"
        )


# ============================================================================
# variables.tf
# ============================================================================


class TestVariablesTf:
    """``variables.tf`` の 5 変数定義。"""

    def test_vultr_api_key_is_sensitive_and_has_no_default(self):
        """Given variables.tf
        When vultr_api_key 変数定義を読む
        Then sensitive = true でかつ default は宣言されていない（Fail Fast）。
        """
        text = strip_hcl_comments(read_file(_VARIABLES_TF))
        block = extract_block(text, r'variable\s+"vultr_api_key"')
        assert block is not None, 'variable "vultr_api_key" が存在しない'
        assert re.search(r"type\s*=\s*string", block), "vultr_api_key.type が string でない"
        assert re.search(r"sensitive\s*=\s*true", block), "vultr_api_key.sensitive = true が無い"
        assert re.search(r"description\s*=", block), "vultr_api_key.description が無い"
        assert not re.search(r"\bdefault\s*=", block), (
            "vultr_api_key には default を設定してはならない（Fail Fast 原則）"
        )

    def test_ssh_pub_key_path_default_is_yt_stream_key_pub(self):
        """Given variables.tf
        When ssh_pub_key_path 変数定義を読む
        Then default が "~/.ssh/yt_stream_key.pub"。
        """
        text = strip_hcl_comments(read_file(_VARIABLES_TF))
        block = extract_block(text, r'variable\s+"ssh_pub_key_path"')
        assert block is not None, 'variable "ssh_pub_key_path" が存在しない'
        assert re.search(r"type\s*=\s*string", block), "ssh_pub_key_path.type が string でない"
        assert re.search(r'default\s*=\s*"~/\.ssh/yt_stream_key\.pub"', block), (
            'ssh_pub_key_path.default が "~/.ssh/yt_stream_key.pub" でない'
        )
        assert re.search(r"description\s*=", block), "ssh_pub_key_path.description が無い"

    def test_region_default_is_nrt(self):
        """Given variables.tf
        When region 変数定義を読む
        Then default が "nrt"（東京）。
        """
        text = strip_hcl_comments(read_file(_VARIABLES_TF))
        block = extract_block(text, r'variable\s+"region"')
        assert block is not None, 'variable "region" が存在しない'
        assert re.search(r"type\s*=\s*string", block), "region.type が string でない"
        assert re.search(r'default\s*=\s*"nrt"', block), 'region.default が "nrt" でない'
        assert re.search(r"description\s*=", block), "region.description が無い"

    def test_plan_default_is_vc2_1c_2gb(self):
        """Given variables.tf
        When plan 変数定義を読む
        Then default が "vc2-1c-2gb"（$10/月、2GB RAM）。
        """
        text = strip_hcl_comments(read_file(_VARIABLES_TF))
        block = extract_block(text, r'variable\s+"plan"')
        assert block is not None, 'variable "plan" が存在しない'
        assert re.search(r"type\s*=\s*string", block), "plan.type が string でない"
        assert re.search(r'default\s*=\s*"vc2-1c-2gb"', block), 'plan.default が "vc2-1c-2gb" でない'
        assert re.search(r"description\s*=", block), "plan.description が無い"

    def test_os_id_is_number_type_with_ubuntu_24_04_default(self):
        """Given variables.tf
        When os_id 変数定義を読む
        Then type が number でかつ default が 2284（Ubuntu 24.04 LTS x64 の Vultr OS ID）。
        """
        text = strip_hcl_comments(read_file(_VARIABLES_TF))
        block = extract_block(text, r'variable\s+"os_id"')
        assert block is not None, 'variable "os_id" が存在しない'
        assert re.search(r"type\s*=\s*number", block), "os_id.type が number でない（API は integer）"
        assert re.search(r"default\s*=\s*2284\b", block), "os_id.default が 2284 でない"
        assert re.search(r"description\s*=", block), "os_id.description が無い（マジックナンバー禁止）"


# ============================================================================
# main.tf
# ============================================================================


class TestMainTf:
    """``main.tf`` の vultr_ssh_key + vultr_instance 定義。"""

    def test_vultr_ssh_key_resource_uses_pathexpand(self):
        """Given main.tf
        When vultr_ssh_key.this を読む
        Then ssh_key = file(pathexpand(var.ssh_pub_key_path))。

        ``~`` 展開のため file() の前段に pathexpand() を必ず噛ませる必要がある。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"vultr_ssh_key"\s+"this"')
        assert block is not None, 'resource "vultr_ssh_key" "this" が存在しない'
        assert re.search(
            r"ssh_key\s*=\s*file\(\s*pathexpand\(\s*var\.ssh_pub_key_path\s*\)\s*\)",
            block,
        ), "ssh_key が file(pathexpand(var.ssh_pub_key_path)) でない（~ 未展開のリスク）"

    def test_vultr_instance_resource_exists(self):
        """Given main.tf
        When vultr_instance.this を探す
        Then 定義されている。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"vultr_instance"\s+"this"')
        assert block is not None, 'resource "vultr_instance" "this" が存在しない'

    def test_vultr_instance_references_variables(self):
        """Given main.tf
        When vultr_instance.this の region/plan/os_id を読む
        Then すべて var.* で結線されている（ハードコード禁止）。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"vultr_instance"\s+"this"')
        assert block is not None
        assert re.search(r"region\s*=\s*var\.region", block), "instance.region が var.region でない"
        assert re.search(r"plan\s*=\s*var\.plan", block), "instance.plan が var.plan でない"
        assert re.search(r"os_id\s*=\s*var\.os_id", block), "instance.os_id が var.os_id でない"

    def test_vultr_instance_ssh_key_ids_links_ssh_key_resource(self):
        """Given main.tf
        When vultr_instance.this.ssh_key_ids を読む
        Then [vultr_ssh_key.this.id] で SSH 鍵リソースに結線されている。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"vultr_instance"\s+"this"')
        assert block is not None
        assert re.search(
            r"ssh_key_ids\s*=\s*\[\s*vultr_ssh_key\.this\.id\s*\]",
            block,
        ), "ssh_key_ids が [vultr_ssh_key.this.id] でない（SSH 鍵未紐付け）"

    def test_vultr_instance_uses_plural_tags_not_deprecated_tag(self):
        """Given main.tf
        When vultr_instance.this を読む
        Then 単数 tag ではなく複数 tags を使い、"youtube-stream" を含む。

        Vultr provider v2.x で単数 tag は非推奨。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"vultr_instance"\s+"this"')
        assert block is not None
        assert re.search(r"\btags\s*=\s*\[", block), "tags 属性（複数形）が無い"
        assert re.search(r'tags\s*=\s*\[\s*"youtube-stream"\s*\]', block), 'tags = ["youtube-stream"] の形式でない'
        # 旧属性 `tag = "..."`（単一文字列）を使っていないこと
        assert not re.search(r'(?<!s)\btag\s*=\s*"', block), "旧形式の単数 tag を使っている（Vultr v2.x で非推奨）"

    def test_vultr_instance_label_is_youtube_stream(self):
        """Given main.tf
        When vultr_instance.this.label を読む
        Then "youtube-stream" が設定されている（運用識別用）。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"vultr_instance"\s+"this"')
        assert block is not None
        assert re.search(r'label\s*=\s*"youtube-stream"', block), 'label = "youtube-stream" が設定されていない'

    def test_vultr_instance_hostname_is_youtube_stream(self):
        """Given main.tf
        When vultr_instance.this.hostname を読む
        Then "youtube-stream" が設定されている（運用識別用、label/tags と網羅対称）。

        plan §実装アプローチ 4 / coder-decisions §3 で確定された運用識別子であり、
        誤って削除・改変された場合のリグレッションを検出する。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"vultr_instance"\s+"this"')
        assert block is not None
        assert re.search(r'hostname\s*=\s*"youtube-stream"', block), 'hostname = "youtube-stream" が設定されていない'


# ============================================================================
# outputs.tf
# ============================================================================


class TestOutputsTf:
    """``outputs.tf`` の instance_ip / instance_id expose。"""

    def test_instance_ip_outputs_main_ip_with_description(self):
        """Given outputs.tf
        When output "instance_ip" を読む
        Then value = vultr_instance.this.main_ip でかつ description が付いている。
        """
        text = strip_hcl_comments(read_file(_OUTPUTS_TF))
        block = extract_block(text, r'output\s+"instance_ip"')
        assert block is not None, 'output "instance_ip" が存在しない'
        assert re.search(r"value\s*=\s*vultr_instance\.this\.main_ip", block), (
            "instance_ip.value が vultr_instance.this.main_ip でない"
        )
        assert re.search(r"description\s*=", block), "instance_ip.description が無い"

    def test_instance_id_outputs_instance_id_with_description(self):
        """Given outputs.tf
        When output "instance_id" を読む
        Then value = vultr_instance.this.id でかつ description が付いている。
        """
        text = strip_hcl_comments(read_file(_OUTPUTS_TF))
        block = extract_block(text, r'output\s+"instance_id"')
        assert block is not None, 'output "instance_id" が存在しない'
        assert re.search(r"value\s*=\s*vultr_instance\.this\.id\b", block), (
            "instance_id.value が vultr_instance.this.id でない"
        )
        assert re.search(r"description\s*=", block), "instance_id.description が無い"


# ============================================================================
# terraform.tfvars.example
# ============================================================================


class TestTfvarsExample:
    """``terraform.tfvars.example`` の secret 漏洩防止。"""

    def test_example_file_exists(self):
        """Given infra/terraform/streaming/
        When terraform.tfvars.example を探す
        Then 存在する（cp して使うサンプル）。
        """
        assert _TFVARS_EXAMPLE.exists(), "terraform.tfvars.example が存在しない"

    def test_does_not_contain_vultr_api_key_assignment(self):
        """Given terraform.tfvars.example
        When ファイル内容を読む
        Then ``vultr_api_key = "..."`` の代入が（コメントを除いて）存在しない。

        secret は TF_VAR_vultr_api_key 経由で渡す前提で、サンプルにも値を書かない。
        """
        text = strip_hcl_comments(read_file(_TFVARS_EXAMPLE))
        # コメント除去後に `vultr_api_key = ...` が残っていないこと
        assert not re.search(r"^\s*vultr_api_key\s*=", text, flags=re.MULTILINE), (
            "vultr_api_key の代入がアクティブ行に存在する（secret 漏洩リスク）"
        )

    def test_mentions_tf_var_vultr_api_key_in_comments(self):
        """Given terraform.tfvars.example
        When ファイル内容（コメント込み）を読む
        Then TF_VAR_vultr_api_key の使い方がコメントに記載されている。
        """
        raw = read_file(_TFVARS_EXAMPLE)
        assert "TF_VAR_vultr_api_key" in raw, (
            "TF_VAR_vultr_api_key の案内コメントが無い（運用者が secret 注入方法を発見できない）"
        )


# ============================================================================
# ルート .gitignore
# ============================================================================


class TestRootGitignoreTerraformEntries:
    """ルート ``.gitignore`` に Terraform 系の ignore エントリ。"""

    @pytest.fixture
    def gitignore_lines(self) -> list[str]:
        """空白除去・空行除外した非コメント行のリスト。"""
        text = read_file(_ROOT_GITIGNORE)
        return [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]

    def test_ignores_terraform_tfvars(self, gitignore_lines: list[str]):
        """Given root .gitignore
        When 行を走査する
        Then terraform.tfvars が ignore 対象。
        """
        assert "terraform.tfvars" in gitignore_lines, (
            "terraform.tfvars が .gitignore に追加されていない（secret 漏洩リスク）"
        )

    def test_ignores_tfstate_files(self, gitignore_lines: list[str]):
        """Given root .gitignore
        When 行を走査する
        Then *.tfstate / *.tfstate.* （または *.tfstate*）が ignore 対象。

        state には secret が含まれうるためコミット禁止。
        """
        # 「*.tfstate*」（wildcard 末尾）または個別に「*.tfstate」+「*.tfstate.*」のどちらでも可
        has_wildcard = "*.tfstate*" in gitignore_lines
        has_split = "*.tfstate" in gitignore_lines and "*.tfstate.*" in gitignore_lines
        assert has_wildcard or has_split, "*.tfstate / *.tfstate.* が .gitignore に追加されていない"

    def test_ignores_terraform_dot_dir(self, gitignore_lines: list[str]):
        """Given root .gitignore
        When 行を走査する
        Then .terraform/ が ignore 対象。

        provider バイナリ・cache をコミットしない。
        """
        assert ".terraform/" in gitignore_lines, ".terraform/ が .gitignore に追加されていない"

    def test_ignores_tfplan_files(self, gitignore_lines: list[str]):
        """Given root .gitignore
        When 行を走査する
        Then *.tfplan が ignore 対象。

        `terraform plan -out=` で生成される binary plan ファイルの誤コミット防止
        （defense-in-depth: #154 で採用した ssh-agent 切替の fallback layer）。
        """
        assert "*.tfplan" in gitignore_lines, (
            "*.tfplan が .gitignore に追加されていない（terraform plan -out= ファイルの誤コミット保護が外れている）"
        )


# ============================================================================
# cloud-init.yaml (#124)
# ============================================================================


class TestCloudInitYaml:
    """``cloud-init.yaml`` の構造（#124: プロビジョニング起動 YAML）。

    行構造・キー存在を正規表現で直接検証するため、YAML パーサーで読み込まず
    テキストベースで構造検証する。
    """

    def test_file_exists_with_cloud_config_header(self):
        """Given infra/terraform/streaming/
        When cloud-init.yaml を探す
        Then 存在し、先頭が ``#cloud-config`` で始まる（cloud-init 必須ヘッダー）。
        """
        assert _CLOUD_INIT_YAML.exists(), "cloud-init.yaml が存在しない"
        text = read_file(_CLOUD_INIT_YAML)
        first_line = text.splitlines()[0] if text.splitlines() else ""
        assert first_line.strip() == "#cloud-config", (
            f"先頭行が #cloud-config でない: {first_line!r}（cloud-init が認識しない）"
        )

    def test_package_update_is_true(self):
        """Given cloud-init.yaml
        When ``package_update`` キーを読む
        Then ``true`` が設定されている (R1、R-172-IMP-2: hardening 編集後も維持)。

        新規 ``package_upgrade: true`` 追記時に既存 ``package_update`` を誤って書換・削除して
        いないことも本テストで保証する。
        """
        text = read_file(_CLOUD_INIT_YAML)
        assert re.search(r"^package_update:\s*true\b", text, flags=re.MULTILINE), (
            "package_update: true が宣言されていない（apt update が走らない）"
        )

    def test_packages_list_includes_ffmpeg(self):
        """Given cloud-init.yaml
        When ``packages:`` リストを読む
        Then ``ffmpeg`` が含まれている (R2、R-172-IMP-2-b: hardening 編集後も維持)。

        streaming systemd unit で動画変換に必須の前提パッケージ。
        #172 hardening の ``# ...`` 省略表記による誤削除リグレッションも本テストで担保する。
        """
        text = read_file(_CLOUD_INIT_YAML)
        packages_block = _extract_yaml_packages_block(text)
        assert packages_block is not None, "packages: リストブロックが存在しない"
        assert re.search(r"^\s*-\s*ffmpeg\b", packages_block, flags=re.MULTILINE), (
            "packages リストに ffmpeg が含まれていない"
        )

    def test_runcmd_creates_videos_dir_with_root_owner_and_0755(self):
        """Given cloud-init.yaml
        When runcmd を読む
        Then ``/opt/youtube-stream/videos`` を root:root, 0755 で作成するコマンドがある (R3)。

        ``install -d -m 0755 -o root -g root <path>`` 形式でパーミッションと所有者を明示する。
        """
        text = read_file(_CLOUD_INIT_YAML)
        assert re.search(
            r"install\s+-d\s+-m\s+0755\s+-o\s+root\s+-g\s+root\s+/opt/youtube-stream/videos\b",
            text,
        ), "/opt/youtube-stream/videos を root:root 0755 で作成する install コマンドが無い"

    def test_runcmd_creates_logs_dir_with_root_owner_and_0755(self):
        """Given cloud-init.yaml
        When runcmd を読む
        Then ``/opt/youtube-stream/logs`` を root:root, 0755 で作成するコマンドがある (R4)。
        """
        text = read_file(_CLOUD_INIT_YAML)
        assert re.search(
            r"install\s+-d\s+-m\s+0755\s+-o\s+root\s+-g\s+root\s+/opt/youtube-stream/logs\b",
            text,
        ), "/opt/youtube-stream/logs を root:root 0755 で作成する install コマンドが無い"

    def test_cloud_init_yaml_no_longer_bakes_systemd_unit(self):
        """Given cloud-init.yaml
        When 全文を読む
        Then ``write_files:`` ブロック・``systemd_unit`` テンプレート変数・
             ``/etc/systemd/system/youtube-stream.service`` パスのいずれも含まれない (#212)。

        systemd unit は ``null_resource.deploy`` の ``provisioner "file"`` で SCP 配信するように
        統一されたため、cloud-init 側の焼き付け経路を残してはならない。残骸を残すと
        「設定したのに使われない」混乱と、初回 apply 時の二重配置リスクを招く。
        """
        text = read_file(_CLOUD_INIT_YAML)
        assert not re.search(r"^write_files:", text, flags=re.MULTILINE), (
            "write_files: ブロックが残っている（unit 配置は null_resource 経路に統一）"
        )
        assert "systemd_unit" not in text, (
            "cloud-init.yaml に systemd_unit テンプレート変数が残っている"
            "（user_data の内側 templatefile 結線が撤去されたため未定義変数になる）"
        )
        assert not re.search(r"/etc/systemd/system/youtube-stream\.service", text), (
            "cloud-init.yaml に /etc/systemd/system/youtube-stream.service の配置宣言が残っている"
        )

    def test_runcmd_does_not_invoke_systemctl_daemon_reload(self):
        """Given cloud-init.yaml
        When runcmd を読む
        Then ``systemctl daemon-reload`` を含まない (#212)。

        cloud-init 側の write_files から unit を撤去したため、ここでの reload は呼ぶ対象が無い。
        unit の登録・反映は ``null_resource.deploy`` の ``provisioner "remote-exec"`` 内
        ``systemctl daemon-reload`` が担う。
        """
        text = read_file(_CLOUD_INIT_YAML)
        assert not re.search(r"\bsystemctl\s+daemon-reload\b", text), (
            "systemctl daemon-reload が cloud-init.yaml に残っている"
            "（unit は null_resource 経路で配置されるため、ここで reload する対象が存在しない）"
        )

    def test_does_not_enable_or_start_service(self):
        """Given cloud-init.yaml
        When 全文を読む
        Then ``systemctl enable`` も ``systemctl start`` も実行しない (R7)。

        order.md cloud-init §4「``enable --now`` は #125 で対応」のスコープ越境を防ぐ。
        """
        text = read_file(_CLOUD_INIT_YAML)
        assert not re.search(r"\bsystemctl\s+enable\b", text), (
            "systemctl enable を実行してはならない（#125 の責務、ここで起動すると .env 不在で失敗する）"
        )
        assert not re.search(r"\bsystemctl\s+start\b", text), "systemctl start を実行してはならない（#125 の責務）"
        # `--now` 単独でも enable と組み合わせる意図のため検出
        assert not re.search(r"\bsystemctl\s+\S+\s+--now\b", text), (
            "systemctl ... --now を実行してはならない（実質 enable+start の越境）"
        )

    def test_does_not_contain_plaintext_secrets(self):
        """Given cloud-init.yaml
        When 全文を読む
        Then 動画パス・RTMP URL・stream key の直書きが無い (R19)。

        `user_data` に含めると Vultr API 経由で漏洩するため、ここに secret を書かない。
        """
        text = read_file(_CLOUD_INIT_YAML)
        # ありがちな漏洩パターン（YAML 値として `=` ではなく `:` を使うが念のため両対応）
        assert not re.search(r"\brtmp://[^\s'\"]+", text), "rtmp:// URL が直書きされている（secret 漏洩リスク）"
        assert not re.search(r"\bRTMP_URL\s*[:=]\s*['\"]?rtmp", text), (
            "RTMP_URL に rtmp:// 値が直書きされている（secret 漏洩リスク）"
        )
        # YAML key/value としての VIDEO 直書き
        # （`write_files` content 内の `$VIDEO` は許容するため key 形式に限定）
        assert not re.search(
            r"^\s*VIDEO\s*[:=]\s*['\"]?/[\w./-]+\.(mp4|mkv|mov|webm)\b",
            text,
            flags=re.MULTILINE | re.IGNORECASE,
        ), "VIDEO に動画パスが直書きされている（secret/構成 漏洩リスク、.env で渡すべき）"

    # ------------------------------------------------------------------
    # Issue #172 hardening: ssh_pwauth / package_upgrade / unattended-upgrades
    # ------------------------------------------------------------------

    def test_declares_ssh_pwauth_false(self):
        """Given cloud-init.yaml
        When トップレベルキーを読む
        Then ``ssh_pwauth: false`` が宣言されている (R-172-1)。

        cloud-init レイヤで SSH パスワード認証を無効化し、
        Vultr/Ubuntu イメージの初期デフォルトへの依存を解消する。
        """
        text = read_file(_CLOUD_INIT_YAML)
        assert re.search(r"^ssh_pwauth:\s*false\b", text, flags=re.MULTILINE), (
            "ssh_pwauth: false がトップレベルで宣言されていない"
            "（cloud-init レイヤの SSH パスワード認証無効化が欠落、初期デフォルト依存）"
        )

    def test_package_upgrade_is_true(self):
        """Given cloud-init.yaml
        When トップレベルキーを読む
        Then ``package_upgrade: true`` が宣言されている (R-172-2)。

        初期構築時のセキュリティパッチ適用を保証する。
        """
        text = read_file(_CLOUD_INIT_YAML)
        assert re.search(r"^package_upgrade:\s*true\b", text, flags=re.MULTILINE), (
            "package_upgrade: true がトップレベルで宣言されていない（初期構築時のセキュリティパッチが未適用になる）"
        )

    def test_packages_list_includes_unattended_upgrades(self):
        """Given cloud-init.yaml
        When ``packages:`` リストを読む
        Then ``unattended-upgrades`` が含まれている (R-172-3)。

        運用中の自動セキュリティパッチ適用パッケージを導入する。
        """
        text = read_file(_CLOUD_INIT_YAML)
        packages_block = _extract_yaml_packages_block(text)
        assert packages_block is not None, "packages: リストブロックが存在しない"
        assert re.search(r"^\s*-\s*unattended-upgrades\b", packages_block, flags=re.MULTILINE), (
            "packages リストに unattended-upgrades が含まれていない（運用中の自動パッチ適用が無効）"
        )

    def test_runcmd_disables_password_authentication_in_sshd_config(self):
        """Given cloud-init.yaml
        When runcmd を読む
        Then ``sed`` で ``/etc/ssh/sshd_config`` の ``PasswordAuthentication`` を
             ``no`` に固定するコマンドがある (R-172-4)。

        cloud-init の ``ssh_pwauth: false`` と二重防御で、
        コメント有/無・既存値に関わらず冪等に ``no`` を強制する。
        """
        text = read_file(_CLOUD_INIT_YAML)
        # 同一行に sed / `^#\?PasswordAuthentication` パターン / `PasswordAuthentication no`
        # / sshd_config パスが揃う。正規表現でリテラル `\?` を表すには `\\` (literal バックスラッシュ)
        # + `\?` (escaped 疑問符) で `\\\?` と書く必要がある。
        sed_line_pattern = (
            r"sed\s+-i\s+.*\^#\\\?PasswordAuthentication.*"
            r"PasswordAuthentication\s+no.*?/etc/ssh/sshd_config"
        )
        assert re.search(sed_line_pattern, text), (
            "sed -i で /etc/ssh/sshd_config の PasswordAuthentication を no に書き換える runcmd が無い"
            "（sshd_config レイヤの二重防御欠落）"
        )

    def test_runcmd_reloads_ssh_with_sshd_fallback(self):
        """Given cloud-init.yaml
        When runcmd を読む
        Then ``systemctl reload ssh || systemctl reload sshd`` の OR フォールバックが実行される (R-172-5)。

        Ubuntu のサービス名差異（``ssh`` vs ``sshd``）を OR で吸収する。片寄せ禁止。
        """
        text = read_file(_CLOUD_INIT_YAML)
        assert re.search(
            r"systemctl\s+reload\s+ssh\s*\|\|\s*systemctl\s+reload\s+sshd",
            text,
        ), (
            "systemctl reload ssh || systemctl reload sshd の OR フォールバックが runcmd に無い"
            "（Ubuntu サービス名差異吸収が欠落）"
        )

    def test_runcmd_reconfigures_unattended_upgrades(self):
        """Given cloud-init.yaml
        When runcmd を読む
        Then ``dpkg-reconfigure --priority=low unattended-upgrades`` が実行される (R-172-6)。

        ``unattended-upgrades`` パッケージのインストール後アクティベートを保証する。
        """
        text = read_file(_CLOUD_INIT_YAML)
        assert re.search(
            r"dpkg-reconfigure\s+--priority=low\s+unattended-upgrades\b",
            text,
        ), (
            "dpkg-reconfigure --priority=low unattended-upgrades が runcmd に無い"
            "（unattended-upgrades のアクティベートが欠落）"
        )

    def test_hardening_runcmd_runs_before_install_d(self):
        """Given cloud-init.yaml
        When runcmd の出現順序を読む
        Then hardening 3 行（``sed`` / ``systemctl reload ssh`` / ``dpkg-reconfigure``）が
             既存の ``install -d ... /opt/youtube-stream/videos`` より前に配置されている (R-172-IMP-1)。

        早期 hardening の意図に従い、issue 推奨形どおり 3 行を runcmd 先頭に挿入する。
        """
        text = read_file(_CLOUD_INIT_YAML)
        sed_idx = text.find("sed -i")
        reload_idx = text.find("systemctl reload ssh")
        reconfigure_idx = text.find("dpkg-reconfigure")
        install_videos_idx = text.find("install -d -m 0755 -o root -g root /opt/youtube-stream/videos")
        assert sed_idx != -1, "sed -i 行が cloud-init.yaml に見つからない（前段確認）"
        assert reload_idx != -1, "systemctl reload ssh 行が cloud-init.yaml に見つからない（前段確認）"
        assert reconfigure_idx != -1, "dpkg-reconfigure 行が cloud-init.yaml に見つからない（前段確認）"
        assert install_videos_idx != -1, (
            "install -d ... /opt/youtube-stream/videos 行が cloud-init.yaml に見つからない（前段確認）"
        )
        assert sed_idx < reload_idx < reconfigure_idx < install_videos_idx, (
            "hardening 3 行（sed → systemctl reload ssh → dpkg-reconfigure）が "
            "install -d ... /opt/youtube-stream/videos より前に並んでいない"
            f"（順序: sed={sed_idx}, reload={reload_idx}, "
            f"reconfigure={reconfigure_idx}, install_videos={install_videos_idx}）"
        )

    def test_packages_list_retains_cron(self):
        """Given hardening 反映後の cloud-init.yaml
        When ``packages:`` リストを読む
        Then ``cron`` が引き続き含まれている (R-172-IMP-2)。

        ``main.tf`` の ``null_resource.deploy`` が ``/etc/cron.d/youtube-stream-healthcheck`` を
        配置する前提で必須のパッケージ。issue 推奨形の ``# ...`` 省略表記による誤削除リグレッションを捕捉する。
        """
        text = read_file(_CLOUD_INIT_YAML)
        packages_block = _extract_yaml_packages_block(text)
        assert packages_block is not None, "packages: リストブロックが存在しない"
        assert re.search(r"^\s*-\s*cron\b", packages_block, flags=re.MULTILINE), (
            "packages リストから cron が消えている"
            "（healthcheck cron の前提が崩れる: main.tf の /etc/cron.d/youtube-stream-healthcheck が動かない）"
        )

    def test_runcmd_sed_entry_has_no_outer_double_quotes(self):
        """Given cloud-init.yaml
        When runcmd の sed 行を読む
        Then ``- "sed ..."`` のように外側を二重引用符で囲んでいない。

        plan 実装ガイドラインに従い、既存 ``install -d ...`` と同じ裸書きスタイルを維持する。
        外側クォートを付けると YAML 文字列としての挙動が変わり、issue 推奨形からの逸脱になる。
        """
        text = read_file(_CLOUD_INIT_YAML)
        assert not re.search(r'^\s*-\s*"sed', text, flags=re.MULTILINE), (
            'runcmd の sed 行が外側を二重引用符で囲まれている（- "sed ..." 形式）'
            "。既存慣習どおりクォートなしの裸書きにすること"
        )

    def test_runcmd_retains_install_d_bin(self):
        """Given hardening 反映後の cloud-init.yaml
        When runcmd を読む
        Then 既存の ``install -d ... /opt/youtube-stream/bin`` 行が保持されている (R-172-IMP-2)。

        ``/opt/youtube-stream/bin`` は terraform の ``provisioner "file"`` がスクリプトを
        upload する宛先（既存コメント参照）。新規 hardening 3 行先頭挿入時に
        誤って削除されていないことを保証する。
        """
        text = read_file(_CLOUD_INIT_YAML)
        assert re.search(
            r"install\s+-d\s+-m\s+0755\s+-o\s+root\s+-g\s+root\s+/opt/youtube-stream/bin\b",
            text,
        ), (
            "/opt/youtube-stream/bin を root:root 0755 で作成する install コマンドが消えている"
            '（terraform provisioner "file" のスクリプト upload 先が失われる）'
        )

    def test_cloud_init_yaml_is_valid_yaml(self):
        """Given cloud-init.yaml
        When ``yaml.safe_load`` で読み込む
        Then 例外を投げず ``dict`` を返す (I-1)。

        cloud-init に渡す前段の構文ガード。インデント崩れ・タブ混入・キー重複等を
        regex ベースの個別テストでは捕捉できないため、YAML パーサで包括的に検証する。
        ``yaml.YAMLError`` は明示 try/except せず pytest トレースに伝播させる。
        """
        loaded = yaml.safe_load(read_file(_CLOUD_INIT_YAML))
        assert isinstance(loaded, dict), (
            f"cloud-init.yaml が dict としてロードできない（型: {type(loaded).__name__}）"
            "。トップレベルが空・list 化・スカラー化など構文不備の可能性"
        )

    def test_ssh_pwauth_declared_exactly_once(self):
        """Given hardening 反映後の cloud-init.yaml
        When 行頭 ``ssh_pwauth:`` の出現件数を数える
        Then 宣言は **ちょうど 1 件** である。

        Red 段階では「宣言 0 件」、Green 段階では「重複宣言 ≥ 2 件」の双方を捕捉する
        dual-purpose ガード。既存の ``re.search`` 系テストは最初の 1 件にマッチして
        重複を見逃すため、件数チェックで補完する。
        """
        text = read_file(_CLOUD_INIT_YAML)
        matches = re.findall(r"^ssh_pwauth:", text, flags=re.MULTILINE)
        assert len(matches) == 1, f"ssh_pwauth が {len(matches)} 回宣言されている（重複編集 or 欠落リグレッション）"

    def test_package_upgrade_declared_exactly_once(self):
        """Given hardening 反映後の cloud-init.yaml
        When 行頭 ``package_upgrade:`` の出現件数を数える
        Then 宣言は **ちょうど 1 件** である。

        ``package_update``（既存）と紛らわしいため行頭 + コロン込みでアンカーし、
        ``package_upgrade`` 単独の重複/欠落を検知する dual-purpose ガード。
        """
        text = read_file(_CLOUD_INIT_YAML)
        matches = re.findall(r"^package_upgrade:", text, flags=re.MULTILINE)
        assert len(matches) == 1, (
            f"package_upgrade が {len(matches)} 回宣言されている（重複編集 or 欠落リグレッション）"
        )


# ============================================================================
# templates/youtube-stream.service.tftpl (#124)
# ============================================================================


class TestSystemdUnitTemplate:
    """``templates/youtube-stream.service.tftpl`` の systemd unit 内容（#124）。

    INI 風だが ``configparser`` は systemd の独自構文で fail することがあるため、
    セクションごとにテキストを切り出し、key=value を正規表現で検証する。
    """

    @staticmethod
    def _section(text: str, name: str) -> str | None:
        """``[Name]`` セクションを次の ``[Other]`` 直前まで抜き出す。"""
        match = re.search(
            rf"^\[{re.escape(name)}\]\s*\n(.*?)(?=^\[|\Z)",
            text,
            flags=re.MULTILINE | re.DOTALL,
        )
        return match.group(1) if match else None

    def _assert_service_directive(self, pattern: str, message: str) -> None:
        """[Service] セクションに directive が 1 行で存在することを検証する。"""
        text = read_file(_SYSTEMD_TFTPL)
        service = self._section(text, "Service")
        assert service is not None
        assert re.search(pattern, service, flags=re.MULTILINE), message

    def test_file_exists(self):
        """Given infra/terraform/streaming/templates/
        When youtube-stream.service.tftpl を探す
        Then 存在する。
        """
        assert _SYSTEMD_TFTPL.exists(), "templates/youtube-stream.service.tftpl が存在しない"

    def test_unit_section_has_description(self):
        """Given .tftpl
        When [Unit] セクションを読む
        Then ``Description=`` が宣言されている (R8)。
        """
        text = read_file(_SYSTEMD_TFTPL)
        unit = self._section(text, "Unit")
        assert unit is not None, "[Unit] セクションが存在しない"
        assert re.search(r"^Description=\S", unit, flags=re.MULTILINE), (
            "[Unit].Description= が空または無い（systemctl status の表示に必須）"
        )

    def test_unit_section_after_network_online_target(self):
        """Given .tftpl
        When [Unit] セクションを読む
        Then ``After=network-online.target`` が宣言されている (R9)。
        """
        text = read_file(_SYSTEMD_TFTPL)
        unit = self._section(text, "Unit")
        assert unit is not None
        assert re.search(r"^After=network-online\.target\s*$", unit, flags=re.MULTILINE), (
            "[Unit].After=network-online.target が無い（ネットワーク準備前に ffmpeg 起動するリスク）"
        )

    def test_service_type_simple(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``Type=simple`` が宣言されている (R10)。
        """
        text = read_file(_SYSTEMD_TFTPL)
        service = self._section(text, "Service")
        assert service is not None, "[Service] セクションが存在しない"
        assert re.search(r"^Type=simple\s*$", service, flags=re.MULTILINE), "[Service].Type=simple が無い"

    def test_service_environment_file_path(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``EnvironmentFile=/etc/youtube-stream.env`` が宣言されている (R11)。

        secret 隔離の核。VIDEO/RTMP_URL を unit 内に直書きせず .env から読む経路を強制する。
        """
        text = read_file(_SYSTEMD_TFTPL)
        service = self._section(text, "Service")
        assert service is not None
        assert re.search(
            r"^EnvironmentFile=/etc/youtube-stream\.env\s*$",
            service,
            flags=re.MULTILINE,
        ), "[Service].EnvironmentFile=/etc/youtube-stream.env が無い（secret 隔離が破綻）"

    def test_service_exec_start_invokes_wrapper_without_env_expansion(self):
        """Given .tftpl
        When [Service].ExecStart を読む
        Then ラッパー ``/opt/youtube-stream/bin/run-ffmpeg.sh`` のみを呼び、
        ``$RTMP_URL`` 等の env 参照を unit 行に残さない (#160)。

        旧仕様（#185）では ``ExecStart=/usr/bin/ffmpeg -re -stream_loop -1 -i $VIDEO
        -c:v copy -c:a copy -f flv $RTMP_URL`` のように systemd が ``$RTMP_URL`` を
        argv 展開していたため、``systemctl show youtube-stream`` /
        ``/proc/<pid>/cmdline`` の unit レベル経路から stream_key を含む RTMP URL が
        平文露出していた。#160 で ``ExecStart`` をラッパーに差し替え、ffmpeg 引数構築は
        ``scripts/streaming/run-ffmpeg.sh`` 側へ移送した。
        """
        text = read_file(_SYSTEMD_TFTPL)
        service = self._section(text, "Service")
        assert service is not None
        expected = r"^ExecStart=/opt/youtube-stream/bin/run-ffmpeg\.sh\s*$"
        assert re.search(expected, service, flags=re.MULTILINE), (
            "[Service].ExecStart が /opt/youtube-stream/bin/run-ffmpeg.sh のみを呼ぶラッパー化形式（#160）と一致しない"
        )

        # ラッパー化の核は unit 行に env 参照 ($RTMP_URL / $VIDEO) を残さないこと。
        # 念のため [Service] セクション内に $RTMP_URL / $VIDEO が現れないことも検証する。
        exec_lines = [line for line in service.splitlines() if line.lstrip().startswith("ExecStart=")]
        assert exec_lines, "[Service] に ExecStart= 行が無い"
        for line in exec_lines:
            assert "$RTMP_URL" not in line and "${RTMP_URL}" not in line, (
                f"ExecStart に $RTMP_URL が残っている（#160 で argv 経路を遮断する hardening）: {line!r}"
            )
            assert "$VIDEO" not in line and "${VIDEO}" not in line, (
                f"ExecStart に $VIDEO が残っている（#160 でラッパー側に移送）: {line!r}"
            )

    def test_service_runtime_max_sec_11h(self):
        """Given .tftpl
        When [Service] を読む
        Then ``RuntimeMaxSec=11h`` が宣言されている (R13)。

        12h 以上で配信するとアーカイブされない YouTube 仕様の回避策。
        """
        text = read_file(_SYSTEMD_TFTPL)
        service = self._section(text, "Service")
        assert service is not None
        assert re.search(r"^RuntimeMaxSec=11h\s*$", service, flags=re.MULTILINE), (
            "[Service].RuntimeMaxSec=11h が無い（11h で停止しないとアーカイブされない）"
        )

    def test_service_restart_always(self):
        """Given .tftpl
        When [Service] を読む
        Then ``Restart=always`` が宣言されている (R14)。
        """
        text = read_file(_SYSTEMD_TFTPL)
        service = self._section(text, "Service")
        assert service is not None
        assert re.search(r"^Restart=always\s*$", service, flags=re.MULTILINE), (
            "[Service].Restart=always が無い（11h 停止後に自動再開しない）"
        )

    def test_service_restart_sec_1h(self):
        """Given .tftpl
        When [Service] を読む
        Then ``RestartSec=1h`` が宣言されている (R15)。
        """
        text = read_file(_SYSTEMD_TFTPL)
        service = self._section(text, "Service")
        assert service is not None
        assert re.search(r"^RestartSec=1h\s*$", service, flags=re.MULTILINE), (
            "[Service].RestartSec=1h が無い（11h+1h サイクルが成立しない）"
        )

    def test_install_section_wanted_by_multi_user(self):
        """Given .tftpl
        When [Install] セクションを読む
        Then ``WantedBy=multi-user.target`` が宣言されている (R16)。
        """
        text = read_file(_SYSTEMD_TFTPL)
        install = self._section(text, "Install")
        assert install is not None, "[Install] セクションが存在しない"
        assert re.search(r"^WantedBy=multi-user\.target\s*$", install, flags=re.MULTILINE), (
            "[Install].WantedBy=multi-user.target が無い（systemctl enable で起動対象にならない）"
        )

    def test_service_dynamic_user_yes(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``DynamicUser=yes`` が宣言されている (#159 R1)。

        root 実行 → 動的非特権ユーザ実行への切り替え。demuxer CVE
        （CVE-2023-49502 等）から root RCE への到達経路を遮断する hardening の核。
        """
        text = read_file(_SYSTEMD_TFTPL)
        service = self._section(text, "Service")
        assert service is not None
        assert re.search(r"^DynamicUser=yes\s*$", service, flags=re.MULTILINE), (
            "[Service].DynamicUser=yes が無い（root 実行のままだと CVE 経路が塞がらない）"
        )

    def test_service_no_new_privileges(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``NoNewPrivileges=true`` が宣言されている (#159 R2)。

        setuid バイナリによる権限昇格を遮断する hardening の核。
        """
        text = read_file(_SYSTEMD_TFTPL)
        service = self._section(text, "Service")
        assert service is not None
        assert re.search(r"^NoNewPrivileges=true\s*$", service, flags=re.MULTILINE), (
            "[Service].NoNewPrivileges=true が無い（setuid 経由の権限昇格を許す）"
        )

    def test_service_protect_system_strict(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``ProtectSystem=strict`` が宣言されている (#159 R3)。

        ``/`` ``/usr`` ``/boot`` ``/etc`` を read-only にする hardening の核。
        """
        text = read_file(_SYSTEMD_TFTPL)
        service = self._section(text, "Service")
        assert service is not None
        assert re.search(r"^ProtectSystem=strict\s*$", service, flags=re.MULTILINE), (
            "[Service].ProtectSystem=strict が無い（/usr などへの書き込みが防げない）"
        )

    def test_service_protect_home_true(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``ProtectHome=true`` が宣言されている (#159 R4)。

        ``/home`` の不可視化による secret 漏洩経路の遮断。
        """
        text = read_file(_SYSTEMD_TFTPL)
        service = self._section(text, "Service")
        assert service is not None
        assert re.search(r"^ProtectHome=true\s*$", service, flags=re.MULTILINE), (
            "[Service].ProtectHome=true が無い（/home からの secret 漏洩経路が残る）"
        )

    def test_service_private_tmp(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``PrivateTmp=true`` が宣言されている (#159 R5)。

        ``/tmp`` を namespace で隔離し他プロセスとの共有を遮断する。
        """
        text = read_file(_SYSTEMD_TFTPL)
        service = self._section(text, "Service")
        assert service is not None
        assert re.search(r"^PrivateTmp=true\s*$", service, flags=re.MULTILINE), (
            "[Service].PrivateTmp=true が無い（/tmp 経由の干渉が防げない）"
        )

    def test_service_private_devices(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``PrivateDevices=true`` が宣言されている (#159 R6)。

        ``/dev`` を最小サブセット化し物理デバイスへの直接アクセスを遮断する。
        """
        text = read_file(_SYSTEMD_TFTPL)
        service = self._section(text, "Service")
        assert service is not None
        assert re.search(r"^PrivateDevices=true\s*$", service, flags=re.MULTILINE), (
            "[Service].PrivateDevices=true が無い（/dev 経由の物理デバイス露出が残る）"
        )

    def test_service_capability_bounding_set_empty(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``CapabilityBoundingSet=`` が空値で宣言されている (#159 R7)。

        全 capability 剥奪は root RCE 経路の最終遮断。空値 (``=`` の後ろが空) を
        ``\\s*$`` のマッチと ``\\S`` の非マッチで双方向に検証する。
        """
        text = read_file(_SYSTEMD_TFTPL)
        service = self._section(text, "Service")
        assert service is not None
        assert re.search(r"^CapabilityBoundingSet=\s*$", service, flags=re.MULTILINE), (
            "[Service].CapabilityBoundingSet= (空値) が無い（全 capability 剥奪が効かない）"
        )
        assert not re.search(r"^CapabilityBoundingSet=\S", service, flags=re.MULTILINE), (
            "[Service].CapabilityBoundingSet= に値が指定されている（空でないと全剥奪にならない）"
        )

    def test_service_ambient_capabilities_empty(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``AmbientCapabilities=`` が空値で宣言されている (#159 R8)。

        子プロセスへの capability 引き継ぎ遮断。空値検証は CapabilityBoundingSet と同形式。
        """
        text = read_file(_SYSTEMD_TFTPL)
        service = self._section(text, "Service")
        assert service is not None
        assert re.search(r"^AmbientCapabilities=\s*$", service, flags=re.MULTILINE), (
            "[Service].AmbientCapabilities= (空値) が無い（子プロセスへ capability が引き継がれる）"
        )
        assert not re.search(r"^AmbientCapabilities=\S", service, flags=re.MULTILINE), (
            "[Service].AmbientCapabilities= に値が指定されている（空でないと引き継ぎ遮断にならない）"
        )

    def test_service_read_only_paths_videos(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``ReadOnlyPaths=/opt/youtube-stream/videos`` が宣言されている (#159 R9)。

        動画ファイルの書き換え防止。``ProtectSystem=strict`` と組み合わせて
        書き込み可能領域を最小化する。
        """
        text = read_file(_SYSTEMD_TFTPL)
        service = self._section(text, "Service")
        assert service is not None
        assert re.search(
            r"^ReadOnlyPaths=/opt/youtube-stream/videos\s*$",
            service,
            flags=re.MULTILINE,
        ), "[Service].ReadOnlyPaths=/opt/youtube-stream/videos が無い（動画ファイルの書き換え防止が効かない）"

    def test_service_read_write_paths_logs(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``ReadWritePaths=/opt/youtube-stream/logs`` が宣言されている (#159 R10)。

        logrotate 対象パスの書き込み許可（spec 指示）。``ProtectSystem=strict`` 下で
        書き込みが必要な領域を明示する。
        """
        text = read_file(_SYSTEMD_TFTPL)
        service = self._section(text, "Service")
        assert service is not None
        assert re.search(
            r"^ReadWritePaths=/opt/youtube-stream/logs\s*$",
            service,
            flags=re.MULTILINE,
        ), "[Service].ReadWritePaths=/opt/youtube-stream/logs が無い（logs ディレクトリへの書き込み経路が破綻）"

    def test_no_terraform_interpolation_remains(self):
        """Given .tftpl
        When 全文を読む
        Then ``${...}`` 形式の Terraform 補間が残っていない (R20 の片側)。

        ``$VIDEO`` ``$RTMP_URL`` は systemd の env 参照（波括弧なし）であり terraform は素通しする。
        ``${...}`` を書くと terraform templatefile 評価時に未定義変数で fail する。
        """
        text = read_file(_SYSTEMD_TFTPL)
        assert not re.search(r"\$\{[^}]+\}", text), (
            "${...} 形式の補間が残っている（systemd で参照したい場合は $NAME と書く / "
            "terraform で渡したい場合は templatefile() の variables map に追加する）"
        )

    def test_no_plaintext_secrets_in_unit(self):
        """Given .tftpl
        When 全文を読む
        Then RTMP URL・stream key・動画パスが直書きされていない (R19/R20)。
        """
        text = read_file(_SYSTEMD_TFTPL)
        assert not re.search(r"rtmp://[^\s$]+", text), (
            "rtmp:// が直書きされている（secret 漏洩リスク、$RTMP_URL を使うこと）"
        )
        # 動画パスっぽいリテラル（拡張子付き絶対パス）
        assert not re.search(
            r"-i\s+(?!\$)[/\w.-]+\.(mp4|mkv|mov|webm)\b",
            text,
            flags=re.IGNORECASE,
        ), "ffmpeg -i に動画パスが直書きされている（$VIDEO を使うこと）"

    def test_unit_section_start_limit_interval_sec_zero(self):
        """Given .tftpl
        When [Unit] セクションを読む
        Then ``StartLimitIntervalSec=0`` が宣言されている (#214)。

        起動失敗カウントの時間窓を無効化し、``Restart=always`` + ``RestartSec=1h``
        サイクルが ``StartLimitHit`` で永続停止する経路を遮断する。
        """
        text = read_file(_SYSTEMD_TFTPL)
        unit = self._section(text, "Unit")
        assert unit is not None
        assert re.search(r"^StartLimitIntervalSec=0\s*$", unit, flags=re.MULTILINE), (
            "[Unit].StartLimitIntervalSec=0 が無い（起動失敗連発で StartLimitHit 永続停止する余地が残る）"
        )

    def test_service_success_exit_status_sigterm_143(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``SuccessExitStatus=143 SIGTERM`` が宣言されている (#214)。

        ``RuntimeMaxSec=11h`` 到達時の SIGTERM 終了を明示的に success 扱いに揃え、
        healthcheck の anomaly 誤判定経路を遮断する。
        """
        text = read_file(_SYSTEMD_TFTPL)
        service = self._section(text, "Service")
        assert service is not None
        assert re.search(r"^SuccessExitStatus=143\s+SIGTERM\s*$", service, flags=re.MULTILINE), (
            "[Service].SuccessExitStatus=143 SIGTERM が無い（SIGTERM 終了を anomaly 誤判定する余地が残る）"
        )

    def test_service_timeout_stop_sec_30s(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``TimeoutStopSec=30s`` が宣言されている (#214)。

        SIGTERM → SIGKILL 待機を 90s から 30s に短縮し、ffmpeg flush の現実的時間に揃える。
        """
        text = read_file(_SYSTEMD_TFTPL)
        service = self._section(text, "Service")
        assert service is not None
        assert re.search(r"^TimeoutStopSec=30s\s*$", service, flags=re.MULTILINE), (
            "[Service].TimeoutStopSec=30s が無い（停止待機がデフォルト 90s のままになる）"
        )

    def test_service_restrict_address_families_af_unix_inet_inet6(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6`` が宣言されている (#196 R21)。

        ffmpeg は RTMP TCP (AF_INET/AF_INET6) と journald (AF_UNIX) のみで動作するため、
        他の AF (AF_PACKET / AF_NETLINK 等) を遮断して攻撃面を最小化する。順序はリテラル固定。
        """
        self._assert_service_directive(
            r"^RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6\s*$",
            ("[Service].RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 が無い（不要な AF 経由の攻撃面が残る）"),
        )

    def test_service_lock_personality_yes(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``LockPersonality=yes`` が宣言されている (#196 R22)。

        ``personality(2)`` syscall を遮断し、古い ABI（PER_LINUX32 等）経由の
        exploit 経路を塞ぐ hardening。
        """
        self._assert_service_directive(
            r"^LockPersonality=yes\s*$",
            ("[Service].LockPersonality=yes が無い（personality(2) 経由の ABI 切替 exploit が残る）"),
        )

    def test_service_memory_deny_write_execute_yes(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``MemoryDenyWriteExecute=yes`` が宣言されている (#196 R23)。

        書き込み + 実行可能 (W+X) メモリページを禁止。``run-ffmpeg.sh`` が
        ``-c:v copy -c:a copy`` 固定で JIT を呼ばない現状仕様で静的に安全。
        """
        self._assert_service_directive(
            r"^MemoryDenyWriteExecute=yes\s*$",
            ("[Service].MemoryDenyWriteExecute=yes が無い（W+X メモリ経由の shellcode 注入が残る）"),
        )

    def test_service_restrict_suid_sgid_yes(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``RestrictSUIDSGID=yes`` が宣言されている (#196 R24)。

        setuid/setgid 付きファイルの新規作成を禁止し、特権ファイル経由の
        持続化経路を遮断する。directive 名の大小文字（SUIDSGID）も仕様の一部。
        """
        self._assert_service_directive(
            r"^RestrictSUIDSGID=yes\s*$",
            ("[Service].RestrictSUIDSGID=yes が無い（setuid/setgid ファイル作成による持続化経路が残る）"),
        )

    def test_service_restrict_namespaces_yes(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``RestrictNamespaces=yes`` が宣言されている (#196 R25)。

        新規 namespace（mount/pid/net/user 等）作成を禁止し、namespace 経由の
        sandbox 逸脱経路を遮断する。
        """
        self._assert_service_directive(
            r"^RestrictNamespaces=yes\s*$",
            ("[Service].RestrictNamespaces=yes が無い（新規 namespace 作成経由の sandbox 逸脱が残る）"),
        )

    def test_service_restrict_realtime_yes(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``RestrictRealtime=yes`` が宣言されている (#196 R26)。

        ``SCHED_FIFO`` / ``SCHED_RR`` 等のリアルタイムスケジューリングを禁止し、
        CPU 占有による DoS 経路を遮断する。
        """
        self._assert_service_directive(
            r"^RestrictRealtime=yes\s*$",
            ("[Service].RestrictRealtime=yes が無い（リアルタイムスケジューリングによる CPU 占有経路が残る）"),
        )

    def test_service_system_call_filter_system_service(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``SystemCallFilter=@system-service`` が宣言されている (#196 R27)。

        systemd 既定の ``@system-service`` セットを syscall whitelist として適用。
        ``@`` プレフィックス + セット名をリテラル固定し、任意 syscall 列を許容しない。
        """
        self._assert_service_directive(
            r"^SystemCallFilter=@system-service\s*$",
            ("[Service].SystemCallFilter=@system-service が無い（syscall whitelist が無いと攻撃面が最大化する）"),
        )

    def test_service_system_call_architectures_native(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``SystemCallArchitectures=native`` が宣言されている (#196 R28)。

        ホスト arch 以外の syscall ABI（32-bit on 64-bit 等）を遮断し、
        arch 切替 exploit 経路を塞ぐ。
        """
        self._assert_service_directive(
            r"^SystemCallArchitectures=native\s*$",
            ("[Service].SystemCallArchitectures=native が無い（非ネイティブ arch syscall 経由の exploit 経路が残る）"),
        )

    def test_service_protect_kernel_tunables_yes(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``ProtectKernelTunables=yes`` が宣言されている (#196 R29)。

        ``/proc/sys`` / ``/sys`` 配下の kernel tunable への書き込みを禁止し、
        ランタイムでの kernel パラメータ改竄経路を遮断する。
        """
        self._assert_service_directive(
            r"^ProtectKernelTunables=yes\s*$",
            ("[Service].ProtectKernelTunables=yes が無い（/proc/sys 経由の kernel 改竄が残る）"),
        )

    def test_service_protect_kernel_modules_yes(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``ProtectKernelModules=yes`` が宣言されている (#196 R30)。

        ``modprobe`` 等によるカーネルモジュール load/unload を遮断し、
        rootkit 系モジュール挿入の経路を塞ぐ。
        """
        self._assert_service_directive(
            r"^ProtectKernelModules=yes\s*$",
            ("[Service].ProtectKernelModules=yes が無い（kernel module load 経由の rootkit 経路が残る）"),
        )

    def test_service_protect_kernel_logs_yes(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``ProtectKernelLogs=yes`` が宣言されている (#196 R31)。

        ``/dev/kmsg`` 等のカーネルログへのアクセスを禁止し、
        dmesg 経由の情報漏洩（KASLR offset 等）を遮断する。
        """
        self._assert_service_directive(
            r"^ProtectKernelLogs=yes\s*$",
            ("[Service].ProtectKernelLogs=yes が無い（/dev/kmsg 経由の kernel 情報漏洩が残る）"),
        )

    def test_service_protect_control_groups_yes(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``ProtectControlGroups=yes`` が宣言されている (#196 R32)。

        ``/sys/fs/cgroup`` を read-only にし、cgroup 構成の改竄による
        resource 隔離迂回経路を遮断する。
        """
        self._assert_service_directive(
            r"^ProtectControlGroups=yes\s*$",
            ("[Service].ProtectControlGroups=yes が無い（cgroup 改竄による resource 隔離迂回が残る）"),
        )

    def test_service_remove_ipc_yes(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``RemoveIPC=yes`` が宣言されている (#196 R33)。

        ``DynamicUser=yes`` 連動でサービス終了時に IPC オブジェクト（SysV shm/sem/msg、
        POSIX shm）を掃除し、UID 再利用時の残骸経由のリークを遮断する。
        """
        self._assert_service_directive(
            r"^RemoveIPC=yes\s*$",
            ("[Service].RemoveIPC=yes が無い（DynamicUser 連動の IPC 掃除が効かず残骸が残る）"),
        )


# ============================================================================
# main.tf user_data (#124)
# ============================================================================


class TestMainTfUserData:
    """``main.tf`` の ``vultr_instance.this.user_data`` 結線（#124）。"""

    def test_user_data_attribute_exists(self):
        """Given main.tf
        When vultr_instance.this を読む
        Then ``user_data`` 属性が宣言されている (R17)。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"vultr_instance"\s+"this"')
        assert block is not None
        assert re.search(r"^\s*user_data\s*=", block, flags=re.MULTILINE), (
            "vultr_instance.this.user_data が宣言されていない"
        )

    def test_user_data_is_not_double_base64_encoded(self):
        """Given main.tf
        When vultr_instance.this.user_data の右辺を読む
        Then ``base64encode(...)`` でラップされていない (R18 改訂)。

        terraform-provider-vultr v2.31.0 は ``user_data`` の値を内部で base64 エンコード
        してから Vultr API に渡す。HCL 側で重ねて ``base64encode`` を呼ぶと
        double-encoding になり、VPS 側の cloud-init が
        ``Unhandled non-multipart (text/x-not-multipart) userdata`` 警告を出して
        userdata を無視する（実証: 初回 apply 後に ``cloud-init status --long``）。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"vultr_instance"\s+"this"')
        assert block is not None
        assert not re.search(r"base64encode\s*\(", block), (
            "user_data に base64encode(...) が残っている（provider が auto-encode するため二重になる）"
        )

    def test_user_data_loads_cloud_init_yaml_via_templatefile(self):
        """Given main.tf
        When user_data の右辺を読む
        Then 外側 ``templatefile("${path.module}/cloud-init.yaml", {...})`` が使われている。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"vultr_instance"\s+"this"')
        assert block is not None
        assert re.search(
            r'templatefile\(\s*"\$\{path\.module\}/cloud-init\.yaml"',
            block,
        ), 'user_data が templatefile("${path.module}/cloud-init.yaml", ...) を呼んでいない'

    def test_user_data_template_no_longer_passes_systemd_unit(self):
        """Given main.tf
        When vultr_instance.this.user_data の右辺を読む
        Then ``systemd_unit = ...`` も内側 ``templatefile(...service.tftpl...)`` の
             呼び出しも残っていない (#212)。

        unit 配置は ``null_resource.deploy`` の ``provisioner "file"`` に統一されたため、
        user_data の templatefile 第 2 引数は空 map ``{}`` でなければならない。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"vultr_instance"\s+"this"')
        assert block is not None
        assert not re.search(r"\bsystemd_unit\s*=", block), (
            "vultr_instance.this.user_data に systemd_unit = ... が残っている"
            "（unit は null_resource 経路に統一されたため cloud-init には渡さない）"
        )
        assert not re.search(
            r"youtube-stream\.service\.tftpl",
            block,
        ), "vultr_instance.this 内に service.tftpl への参照が残っている（user_data の内側 templatefile 撤去漏れ）"

    def test_user_data_does_not_contain_plaintext_secrets(self):
        """Given main.tf
        When user_data 全体を読む
        Then RTMP URL や動画パスのリテラルが含まれていない (R19)。

        secret は #125 の `.env` 経由で systemd に渡す責務分離を守る。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"vultr_instance"\s+"this"')
        assert block is not None
        assert not re.search(r"rtmp://", block), "main.tf に rtmp:// が直書きされている"
        assert not re.search(
            r'"[^"]*\.(mp4|mkv|mov|webm)"',
            block,
            flags=re.IGNORECASE,
        ), "main.tf に動画ファイルパスが直書きされている"


# ============================================================================
# variables.tf — #125 追加変数（video_path / stream_key）
# ============================================================================


class TestVariablesTfNullResource:
    """``variables.tf`` の #125 で追加される変数定義（#154 で ssh_priv_key_path を撤去）。

    order.md 構成表:
      - ``video_path`` (string, default なし)
      - ``stream_key`` (string, sensitive=true, default なし)
    """

    def test_video_path_is_required_string_with_no_default(self):
        """Given variables.tf
        When video_path 変数定義を読む
        Then type=string, description あり, default は宣言されていない（必須項目 / Fail Fast）。

        動画パスはローカル環境ごとに異なるため、デフォルトを持たせず利用者に明示指定させる。
        """
        text = strip_hcl_comments(read_file(_VARIABLES_TF))
        block = extract_block(text, r'variable\s+"video_path"')
        assert block is not None, 'variable "video_path" が存在しない'
        assert re.search(r"type\s*=\s*string", block), "video_path.type が string でない"
        assert re.search(r"description\s*=", block), "video_path.description が無い"
        assert not re.search(r"\bdefault\s*=", block), (
            "video_path には default を設定してはならない（環境依存・必須項目）"
        )

    def test_stream_key_is_sensitive_string_with_no_default(self):
        """Given variables.tf
        When stream_key 変数定義を読む
        Then type=string, sensitive=true, description あり, default は宣言されていない。

        secret は ``vultr_api_key`` と同様 Fail Fast。tfstate に sensitive 扱いで残ることを保証する。
        """
        text = strip_hcl_comments(read_file(_VARIABLES_TF))
        block = extract_block(text, r'variable\s+"stream_key"')
        assert block is not None, 'variable "stream_key" が存在しない'
        assert re.search(r"type\s*=\s*string", block), "stream_key.type が string でない"
        assert re.search(r"sensitive\s*=\s*true", block), (
            "stream_key.sensitive = true が無い（tfstate に平文で残るリスク）"
        )
        assert re.search(r"description\s*=", block), "stream_key.description が無い"
        assert not re.search(r"\bdefault\s*=", block), (
            "stream_key には default を設定してはならない（Fail Fast / secret はランタイム注入）"
        )

    def test_ssh_priv_key_path_variable_does_not_exist(self):
        """Given variables.tf
        When ``ssh_priv_key_path`` の variable 定義を探す
        Then 定義が存在しない（issue #154 / order.md R2 で ssh-agent 経由に切替）。

        connection で ``private_key`` を使わなくなり、変数自体が未使用化したため撤去する。
        残骸として残すと「設定したのに使われない」混乱を招くため、関連テスト D1 と一対で削除する。
        """
        text = strip_hcl_comments(read_file(_VARIABLES_TF))
        block = extract_block(text, r'variable\s+"ssh_priv_key_path"')
        assert block is None, (
            'variable "ssh_priv_key_path" が残っている（issue #154: ssh-agent 切替で未使用化したため削除する）'
        )


# ============================================================================
# variables.tf — #153 で追加される allowed_ssh_cidr 変数（firewall）
# ============================================================================


class TestVariablesTfFirewall:
    """``variables.tf`` の #153 で追加される ``allowed_ssh_cidr`` 変数定義（firewall）。

    order.md 推奨対応:
      - ``variable "allowed_ssh_cidr"`` (type=list(string), default=[], description あり)
      - ``validation { length(var.allowed_ssh_cidr) > 0 }`` で空入力を fail-fast
    """

    def test_allowed_ssh_cidr_is_list_of_string_with_empty_default(self):
        """Given variables.tf
        When allowed_ssh_cidr 変数定義を読む
        Then type=list(string), default=[], description あり (R1, H1)。

        order.md スニペット通り `default = []` を保ち、空入力は別途 validation で拒否する。
        """
        text = strip_hcl_comments(read_file(_VARIABLES_TF))
        block = extract_block(text, r'variable\s+"allowed_ssh_cidr"')
        assert block is not None, 'variable "allowed_ssh_cidr" が存在しない'
        assert re.search(r"type\s*=\s*list\(\s*string\s*\)", block), "allowed_ssh_cidr.type が list(string) でない"
        # default は空リスト固定
        assert re.search(r"default\s*=\s*\[\s*\]", block), (
            "allowed_ssh_cidr.default が [] でない（必須入力扱いのため空リストが既定）"
        )
        assert re.search(r"description\s*=", block), "allowed_ssh_cidr.description が無い"

    def test_allowed_ssh_cidr_validation_rejects_empty_list(self):
        """Given variables.tf
        When allowed_ssh_cidr 変数定義の validation ブロックを読む
        Then condition が ``length(var.allowed_ssh_cidr) > 0`` で error_message が宣言されている (R5, H2)。

        空リストでの apply を fail-fast で拒否する経路（plan §到達経路 (c)）。
        """
        text = strip_hcl_comments(read_file(_VARIABLES_TF))
        block = extract_block(text, r'variable\s+"allowed_ssh_cidr"')
        assert block is not None
        validation = extract_block(block, r"validation")
        assert validation is not None, (
            "allowed_ssh_cidr.validation ブロックが存在しない（空入力を fail-fast で拒否できない）"
        )
        assert re.search(
            r"condition\s*=\s*length\(\s*var\.allowed_ssh_cidr\s*\)\s*>\s*0",
            validation,
        ), "validation.condition が length(var.allowed_ssh_cidr) > 0 でない"
        assert re.search(r"error_message\s*=\s*\"", validation), "validation.error_message が宣言されていない"

    def test_allowed_ssh_cidr_default_does_not_open_world(self):
        """Given variables.tf
        When allowed_ssh_cidr 変数定義の default を読む
        Then ``0.0.0.0/0`` 等の全世界開放 CIDR が含まれていない (E1)。

        plan §検討したアプローチ「default = ["0.0.0.0/0"] で全開放」は不採用。
        """
        text = strip_hcl_comments(read_file(_VARIABLES_TF))
        block = extract_block(text, r'variable\s+"allowed_ssh_cidr"')
        assert block is not None
        # default 値の中身を抽出
        default_match = re.search(r"default\s*=\s*(\[[^\]]*\])", block)
        assert default_match is not None, "allowed_ssh_cidr.default が宣言されていない"
        default_value = default_match.group(1)
        assert "0.0.0.0/0" not in default_value, (
            "allowed_ssh_cidr.default に 0.0.0.0/0 が含まれている（issue 目的の攻撃面縮小が無効化される）"
        )
        assert "::/0" not in default_value, "allowed_ssh_cidr.default に ::/0 が含まれている（IPv6 全世界開放）"

    def test_allowed_ssh_cidr_is_not_sensitive(self):
        """Given variables.tf
        When allowed_ssh_cidr 変数定義を読む
        Then ``sensitive = true`` が宣言されていない (E2)。

        plan §secret 漏洩リスク確定: CIDR は secret ではない。tfstate に平文で残ってよい。
        ``vultr_api_key`` / ``stream_key`` の sensitive 必須検証の対称形。
        """
        text = strip_hcl_comments(read_file(_VARIABLES_TF))
        block = extract_block(text, r'variable\s+"allowed_ssh_cidr"')
        assert block is not None
        assert not re.search(r"sensitive\s*=\s*true", block), (
            "allowed_ssh_cidr に sensitive = true が宣言されている（CIDR は secret ではない、YAGNI）"
        )

    def test_allowed_ssh_cidr_validation_error_message_includes_operational_hint(self):
        """Given variables.tf
        When allowed_ssh_cidr.validation.error_message を読む
        Then 運用ヒント語句（``curl`` / ``ifconfig.me`` / ``/32``）のいずれかを含む (E5)。

        plan §到達経路 (c) actionable な fail-fast 文言の担保。
        operator が空入力で plan が落ちた時、error_message から具体的対処を読み取れる必要がある。
        """
        text = strip_hcl_comments(read_file(_VARIABLES_TF))
        block = extract_block(text, r'variable\s+"allowed_ssh_cidr"')
        assert block is not None
        validation = extract_block(block, r"validation")
        assert validation is not None
        msg_match = re.search(r'error_message\s*=\s*"([^"]*)"', validation)
        assert msg_match is not None, "validation.error_message が文字列リテラルで宣言されていない"
        msg = msg_match.group(1)
        assert msg.strip() != "", "validation.error_message が空文字列"
        has_hint = any(hint in msg for hint in ("curl", "ifconfig.me", "/32"))
        assert has_hint, (
            "validation.error_message に運用ヒント（curl / ifconfig.me / /32）が含まれていない"
            "（operator が空入力で詰まっても具体的対処を辿れない）"
        )

    def test_allowed_ssh_cidr_does_not_use_yagni_attributes(self):
        """Given variables.tf
        When allowed_ssh_cidr 変数定義を読む
        Then order.md 非掲載属性（``nullable`` / ``ephemeral``）が宣言されていない (X5)。

        order.md スニペットに無い属性は YAGNI として追加しない（plan §確認したアプローチ参照）。
        """
        text = strip_hcl_comments(read_file(_VARIABLES_TF))
        block = extract_block(text, r'variable\s+"allowed_ssh_cidr"')
        assert block is not None
        assert not re.search(r"\bnullable\s*=", block), (
            "allowed_ssh_cidr に nullable 属性が宣言されている（order.md スコープ外、YAGNI）"
        )
        assert not re.search(r"\bephemeral\s*=", block), (
            "allowed_ssh_cidr に ephemeral 属性が宣言されている（order.md スコープ外、YAGNI）"
        )


# ============================================================================
# versions.tf — #125 で追加される null provider 宣言
# ============================================================================


class TestVersionsTfNullProvider:
    """``versions.tf`` の ``required_providers.null`` 宣言（#125）。

    ``null_resource`` 利用には provider 宣言が必須。terraform 1.5+ では deprecation warning を回避する。
    """

    def test_required_providers_declares_null_source(self):
        """Given versions.tf
        When required_providers.null を読む
        Then source = "hashicorp/null" が宣言されている。
        """
        text = strip_hcl_comments(read_file(_VERSIONS_TF))
        terraform_block = extract_block(text, r"terraform")
        assert terraform_block is not None
        rp_block = extract_block(terraform_block, r"required_providers")
        assert rp_block is not None, "required_providers ブロックが存在しない"
        null_block = extract_block(rp_block, r"null")
        assert null_block is not None, "required_providers.null が宣言されていない"
        assert re.search(r'source\s*=\s*"hashicorp/null"', null_block), (
            'required_providers.null.source が "hashicorp/null" でない'
        )

    def test_required_providers_null_version_at_least_3_2(self):
        """Given versions.tf
        When required_providers.null.version を読む
        Then ">= 3.2" を含む制約が宣言されている（plan §2.2）。
        """
        text = strip_hcl_comments(read_file(_VERSIONS_TF))
        terraform_block = extract_block(text, r"terraform")
        assert terraform_block is not None
        rp_block = extract_block(terraform_block, r"required_providers")
        assert rp_block is not None
        null_block = extract_block(rp_block, r"null")
        assert null_block is not None
        assert re.search(r'version\s*=\s*"[^"]*>=\s*3\.2', null_block), (
            "required_providers.null.version が >= 3.2 を満たしていない"
        )


# ============================================================================
# main.tf — #125 で追加される null_resource.deploy
# ============================================================================


class TestMainTfNullResource:
    """``main.tf`` の ``null_resource.deploy`` 構造（#125 起点、#109 / #212 拡張）。

    triggers / connection / 複数の ``provisioner "file"``（video / env / healthcheck env /
    systemd unit / healthcheck.sh / notify.sh / logrotate.conf / cron.d）/
    ``provisioner "remote-exec"`` の各構造を検証する。
    """

    def test_null_resource_deploy_exists(self):
        """Given main.tf
        When null_resource.deploy を探す
        Then 定義されている（terraform apply 最終ステップの起点）。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None, 'resource "null_resource" "deploy" が存在しない'

    def test_triggers_block_has_three_keys(self):
        """Given main.tf
        When null_resource.deploy.triggers を読む
        Then instance_id / video_hash / stream_key の 3 キーが宣言されている。

        - instance_id = vultr_instance.this.id（VPS 再作成時の再 deploy）
        - video_hash = filemd5(var.video_path)（動画差分での再 deploy）
        - stream_key（sha256 ハッシュ。stream key 差分での再 deploy）
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None
        triggers = extract_block(block, r"triggers")
        assert triggers is not None, "null_resource.deploy.triggers ブロックが存在しない"
        assert re.search(r"instance_id\s*=\s*vultr_instance\.this\.id", triggers), (
            "triggers.instance_id が vultr_instance.this.id でない"
        )
        assert re.search(r"video_hash\s*=\s*filemd5\(\s*var\.video_path\s*\)", triggers), (
            "triggers.video_hash が filemd5(var.video_path) でない"
        )
        assert re.search(r"\bstream_key\s*=", triggers), "triggers.stream_key が無い"

    def test_triggers_systemd_unit_hashes_service_tftpl(self):
        """Given main.tf
        When null_resource.deploy.triggers を読む
        Then ``systemd_unit = filemd5("${path.module}/templates/youtube-stream.service.tftpl")``
             が宣言されている (#212)。

        tftpl の変更で ``null_resource.deploy`` のみが replace されるよう、unit ファイルの
        md5 を triggers map に含める。これにより ``vultr_instance`` 再構築（VPS 再作成 +
        動画再 SCP）を伴わずに新 unit を反映できる。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None
        triggers = extract_block(block, r"triggers")
        assert triggers is not None, "null_resource.deploy.triggers ブロックが存在しない"
        assert re.search(
            r"systemd_unit\s*=\s*filemd5\(\s*"
            r'"\$\{path\.module\}/templates/youtube-stream\.service\.tftpl"\s*\)',
            triggers,
        ), (
            "triggers.systemd_unit が "
            'filemd5("${path.module}/templates/youtube-stream.service.tftpl") '
            "で宣言されていない（tftpl 変更時に null_resource.deploy が replace されない）"
        )

    def test_provisioner_file_uploads_systemd_unit_to_canonical_path(self):
        """Given main.tf
        When ``null_resource.deploy`` 内の ``provisioner "file"`` を読む
        Then ``content = templatefile("${path.module}/templates/youtube-stream.service.tftpl", {})``
             と ``destination = "/etc/systemd/system/youtube-stream.service"`` のペアが
             同一 provisioner 内に宣言されている (#212)。

        unit 配置は cloud-init の write_files から ``null_resource.deploy`` に移管された。
        既存 video / env と同じ source/destination 順序非依存マッチパターンで検証する。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None
        content_pattern = (
            r"content\s*=\s*templatefile\(\s*"
            r'"\$\{path\.module\}/templates/youtube-stream\.service\.tftpl"\s*,\s*\{\s*\}\s*\)'
        )
        destination_pattern = r'destination\s*=\s*"/etc/systemd/system/youtube-stream\.service"'
        match = re.search(
            r'provisioner\s+"file"\s*\{[^}]*?' + content_pattern + r"[^}]*?" + destination_pattern + r"[^}]*?\}",
            block,
            flags=re.DOTALL,
        )
        match_alt = re.search(
            r'provisioner\s+"file"\s*\{[^}]*?' + destination_pattern + r"[^}]*?" + content_pattern + r"[^}]*?\}",
            block,
            flags=re.DOTALL,
        )
        assert match or match_alt, (
            'provisioner "file" で content=templatefile("${path.module}/templates/'
            'youtube-stream.service.tftpl", {}) → '
            "/etc/systemd/system/youtube-stream.service への配信が宣言されていない"
        )

    def test_triggers_stream_key_is_wrapped_with_nonsensitive(self):
        """Given main.tf
        When triggers.stream_key の右辺を読む
        Then ``nonsensitive(sha256(var.stream_key))`` のように nonsensitive() でラップされている。

        terraform 1.5+ は sensitive 値の派生も sensitive 扱いするため、triggers map に
        直接 ``sha256(var.stream_key)`` を置くと「Output refers to sensitive values」でエラー。
        SHA256 は不可逆なので nonsensitive() で剥がす運用判断（plan §2.4）。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None
        triggers = extract_block(block, r"triggers")
        assert triggers is not None
        # nonsensitive(sha256(var.stream_key)) 形式（空白許容）
        assert re.search(
            r"stream_key\s*=\s*nonsensitive\(\s*sha256\(\s*var\.stream_key\s*\)\s*\)",
            triggers,
        ), (
            "triggers.stream_key が nonsensitive(sha256(var.stream_key)) でラップされていない "
            "（terraform 1.5+ で sensitive 派生エラーになる）"
        )

    def test_connection_block_declares_agent_true(self):
        """Given main.tf
        When null_resource.deploy.connection を読む
        Then ``agent = true`` が宣言されている。

        SSH 秘密鍵 PEM を Terraform graph (plan / state / debug log) に取り込まない経路。
        ssh-agent 経由で鍵を渡すため、Terraform 自身は鍵に触れない。
        （issue #154 / order.md 推奨対応 R2）
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None
        connection = extract_block(block, r"connection")
        assert connection is not None, "null_resource.deploy.connection ブロックが存在しない"
        assert re.search(r"\bagent\s*=\s*true\b", connection), (
            "connection.agent = true が無い（ssh-agent 経由経路が宣言されていない）"
        )

    def test_connection_block_retains_ssh_type_and_root_user_and_host(self):
        """Given main.tf
        When null_resource.deploy.connection を読む
        Then ``type = "ssh"`` / ``user = "root"`` / ``host = vultr_instance.this.main_ip`` が維持されている。

        connection ブロック書き換え（#154）で接続先・プロトコル・ユーザーまで誤って削除しないことの保証。
        order.md 推奨対応の HCL スニペット参照。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None
        connection = extract_block(block, r"connection")
        assert connection is not None, "null_resource.deploy.connection ブロックが存在しない"
        assert re.search(r'type\s*=\s*"ssh"', connection), 'connection.type が "ssh" でない'
        assert re.search(r'user\s*=\s*"root"', connection), 'connection.user が "root" でない'
        assert re.search(r"host\s*=\s*vultr_instance\.this\.main_ip", connection), (
            "connection.host が vultr_instance.this.main_ip でない"
        )

    def test_connection_block_does_not_contain_private_key(self):
        """Given main.tf
        When null_resource.deploy.connection を読む
        Then ``private_key`` 属性が宣言されていない。

        **クリティカルなリグレッション保証**。``private_key = ...`` が混入すると、たとえ
        ``agent = true`` も併記されていても PEM 全文が Terraform graph に取り込まれてしまう
        （plan / state / TF_LOG=DEBUG に平文残存）。
        単語境界 ``\\b`` で ``vultr_ssh_key.this.ssh_key`` などの誤マッチを避ける。
        （issue #154 / order.md 概要・推奨対応 R2）
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None
        connection = extract_block(block, r"connection")
        assert connection is not None, "null_resource.deploy.connection ブロックが存在しない"
        assert not re.search(r"\bprivate_key\s*=", connection), (
            "connection.private_key が残っている（PEM 全文が Terraform graph / plan / state に取り込まれる漏洩経路）"
        )

    def test_connection_block_does_not_reference_ssh_priv_key_path_var(self):
        """Given main.tf
        When null_resource.deploy.connection を読む
        Then ``var.ssh_priv_key_path`` への参照が含まれていない。

        撤去変数（#154 で variables.tf から削除）への参照復活を防ぐ。connection ブロックに
        スコープを絞って検証することで、コメント行や別箇所の影響を排除する。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None
        connection = extract_block(block, r"connection")
        assert connection is not None, "null_resource.deploy.connection ブロックが存在しない"
        assert "ssh_priv_key_path" not in connection, (
            "connection ブロック内に var.ssh_priv_key_path 参照が残っている（撤去済み変数への参照復活）"
        )

    def test_provisioner_file_uploads_video_to_canonical_path(self):
        """Given main.tf
        When 1 つ目の ``provisioner "file"`` を読む
        Then source=var.video_path, destination=/opt/youtube-stream/videos/current.mp4。

        cloud-init で作成済みの ``/opt/youtube-stream/videos/`` （cloud-init.yaml:14）に固定名で配置。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None
        # 動画アップロード provisioner は source=var.video_path で識別
        # ブロック内に「source = var.video_path」と「destination = "/opt/.../current.mp4"」が
        # 同じ provisioner "file" 内にあることを検証（順序は問わない）
        match = re.search(
            r'provisioner\s+"file"\s*\{[^}]*?source\s*=\s*var\.video_path[^}]*?'
            r'destination\s*=\s*"/opt/youtube-stream/videos/current\.mp4"[^}]*?\}',
            block,
            flags=re.DOTALL,
        )
        match_alt = re.search(
            r'provisioner\s+"file"\s*\{[^}]*?'
            r'destination\s*=\s*"/opt/youtube-stream/videos/current\.mp4"[^}]*?'
            r"source\s*=\s*var\.video_path[^}]*?\}",
            block,
            flags=re.DOTALL,
        )
        assert match or match_alt, (
            'provisioner "file" で source=var.video_path → '
            "/opt/youtube-stream/videos/current.mp4 へのアップロードが宣言されていない"
        )

    def test_provisioner_file_places_env_via_templatefile(self):
        """Given main.tf
        When 2 つ目の ``provisioner "file"`` を読む
        Then content=templatefile(...), destination=/tmp/youtube-stream.env.tmp。

        templatefile は ``${path.module}/templates/youtube-stream.env.tftpl`` を読む。
        secret を tfstate に残さず provisioner 経由で配信する経路。
        最終配置先 ``/etc/youtube-stream.env`` は remote-exec の
        ``install -m 0600 -o root -g root`` で原子移送される（race window 閉鎖）。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None
        # templatefile を引数に取る provisioner "file" を抽出（destination=/tmp/youtube-stream.env.tmp）
        assert re.search(
            r'destination\s*=\s*"/tmp/youtube-stream\.env\.tmp"',
            block,
        ), 'provisioner "file" の destination が "/tmp/youtube-stream.env.tmp" でない'
        assert re.search(
            r'templatefile\(\s*"\$\{path\.module\}/templates/youtube-stream\.env\.tftpl"',
            block,
        ), (
            'env を配置する provisioner で templatefile("${path.module}/templates/'
            'youtube-stream.env.tftpl", ...) が呼ばれていない'
        )

    def test_env_templatefile_passes_video_and_rtmp_url_variables(self):
        """Given main.tf
        When env を配置する templatefile() の variables map を読む
        Then ``video = "/opt/youtube-stream/videos/current.mp4"`` と
             ``rtmp_url = "rtmp://a.rtmp.youtube.com/live2/${var.stream_key}"`` が渡されている。

        コメント除去ヘルパーは URL 内の ``//`` を削るため、この検証は raw text で行う。
        """
        text = read_file(_MAIN_TF)  # raw（rtmp:// の // を保持するためコメント除去しない）
        # video 変数（リテラル文字列）
        assert re.search(
            r'video\s*=\s*"/opt/youtube-stream/videos/current\.mp4"',
            text,
        ), 'templatefile に video = "/opt/youtube-stream/videos/current.mp4" が渡されていない'
        # rtmp_url 変数（${var.stream_key} 補間を含む）
        assert re.search(
            r'rtmp_url\s*=\s*"rtmp://a\.rtmp\.youtube\.com/live2/\$\{var\.stream_key\}"',
            text,
        ), 'templatefile に rtmp_url = "rtmp://a.rtmp.youtube.com/live2/${var.stream_key}" が渡されていない'

    def test_provisioner_remote_exec_inline_includes_required_commands(self):
        """Given main.tf
        When ``provisioner "remote-exec"`` の inline を読む
        Then 仕様通りのコマンドがすべて含まれている。

        - install -m 0600 -o root -g root /tmp/youtube-stream.env.tmp /etc/youtube-stream.env
          （0600 / root 所有を原子移送で確定。race window 閉鎖）
        - systemctl daemon-reload  （新 unit / .env 反映）
        - systemctl enable --now youtube-stream  （初回起動）
        - systemctl restart youtube-stream  （再 apply 時に .env 再読込）

        order.md 完了条件「0600 / root 所有」「11h+1h サイクル開始」を満たす。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None
        remote_exec = re.search(
            r'provisioner\s+"remote-exec"\s*\{(.*?)\n\s*\}',
            block,
            flags=re.DOTALL,
        )
        assert remote_exec is not None, 'provisioner "remote-exec" ブロックが見つからない'
        inline = remote_exec.group(1)
        for command, hint in [
            (r"umask\s+0077", "umask 0077 (defense-in-depth)"),
            (
                r"install\s+-m\s+0600\s+-o\s+root\s+-g\s+root\s+/tmp/youtube-stream\.env\.tmp\s+/etc/youtube-stream\.env",
                "install -m 0600 -o root -g root .../etc/youtube-stream.env",
            ),
            (
                r"rm\s+-f\s+/tmp/youtube-stream\.env\.tmp",
                "rm -f /tmp/youtube-stream.env.tmp (tmp secret cleanup)",
            ),
            (r"systemctl\s+daemon-reload", "daemon-reload"),
            (r"systemctl\s+enable\s+--now\s+youtube-stream", "enable --now youtube-stream"),
            (r"systemctl\s+restart\s+youtube-stream", "restart youtube-stream"),
        ]:
            assert re.search(command, inline), f"remote-exec の inline に '{hint}' コマンドが無い"

    def test_no_explicit_depends_on_for_null_resource(self):
        """Given main.tf
        When null_resource.deploy ブロック直下を読む
        Then 明示的な ``depends_on = [...]`` を持たない。

        triggers / connection で ``vultr_instance.this`` を参照することで暗黙の依存が成立しており、
        plan §「特に注意すべきアンチパターン」#10 で「冗長な depends_on を書かない」と明示。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None
        # 内側ブロック（connection 等）の depends_on は本テストの対象外なので、
        # 「行頭からインデント込みで `depends_on = [`」が現れる箇所が無いことを検証
        assert not re.search(r"^\s*depends_on\s*=\s*\[", block, flags=re.MULTILINE), (
            "null_resource.deploy に明示的な depends_on を書いてはならない "
            "（plan アンチパターン #10、参照で暗黙依存が成立する）"
        )

    def test_no_extra_provisioner_attributes_added(self):
        """Given main.tf
        When null_resource.deploy 内の provisioner を読む
        Then ``on_failure`` / ``timeout`` 等、order.md に無い属性を勝手に追加していない。

        plan §「特に注意すべきアンチパターン」#7 のスコープ越境チェック。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None
        assert not re.search(r"\bon_failure\s*=", block), (
            "provisioner に on_failure 属性が追加されている（order.md スコープ外）"
        )
        assert not re.search(r"\btimeout\s*=", block), (
            "provisioner に timeout 属性が追加されている（order.md スコープ外）"
        )


# ============================================================================
# main.tf — #157 で追加される locals.scripts_dir（DRY 化リファクタリング）
# ============================================================================


class TestMainTfLocalsScriptsDir:
    """``main.tf`` の ``locals.scripts_dir``（#157）構造とその参照経路を検証する。

    Issue #157: ``${path.module}/../../../.claude/skills/streaming/references/`` の
    ハードコードが triggers の ``filemd5`` 4 件 + provisioner ``source`` 4 件 = 8 箇所に
    散在し、scripts 移動時に triggers/source 不整合が検知困難になる構造的リスクを解消する。
    Issue #229 で旧パス ``scripts/streaming/`` から ``.claude/skills/streaming/references/``
    へ移動済み（skill の自己完結性確保のため）。

    検証観点:
      - ``locals { scripts_dir = "..." }`` の宣言と値
      - triggers の 4 つの filemd5 が ``${local.scripts_dir}/...`` を参照
      - provisioner ``"file"`` の 4 つの source が ``${local.scripts_dir}/...`` を参照
        （対応する destination とのペアリング保証）
      - ``../../../.claude/skills/streaming/references`` リテラルが locals 内に
        **1 度だけ**出現する DRY 不変条件
      - locals ブロックを除いた残部に旧形式
        ``${path.module}/../../../.claude/skills/streaming/references/`` が残っていない
        （置換漏れ検知）
    """

    def test_locals_block_declares_scripts_dir(self):
        """Given main.tf
        When トップレベルに ``locals`` ブロックを探す
        Then 宣言されており、内部に ``scripts_dir`` キーが存在する。

        新構造の起点。R1（Plan 要件）の存在保証。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))

        block = extract_block(text, r"^\s*locals")

        assert block is not None, "main.tf にトップレベル locals ブロックが宣言されていない"
        assert re.search(r"\bscripts_dir\s*=", block), "locals ブロック内に scripts_dir キーが存在しない"

    def test_locals_scripts_dir_value_is_canonical_relative_path(self):
        """Given main.tf
        When ``locals.scripts_dir`` の右辺リテラルを読む
        Then ``"${path.module}/../../../.claude/skills/streaming/references"`` と一致する。

        集約先の値が誤ると 8 箇所すべての参照先が壊れる。リグレッション影響大。
        Issue #229: skill 配布対象に入れるため
        ``scripts/streaming/`` → ``.claude/skills/streaming/references/`` に移動済み。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r"^\s*locals")
        assert block is not None

        match = re.search(
            r'scripts_dir\s*=\s*"\$\{path\.module\}/\.\./\.\./\.\./\.claude/skills/streaming/references"',
            block,
        )

        assert match is not None, (
            'locals.scripts_dir が "${path.module}/../../../.claude/skills/streaming/references" でない '
            "（値が誤ると 8 箇所の参照先が壊れる）"
        )

    def test_triggers_healthcheck_sh_uses_local_scripts_dir(self):
        """Given main.tf
        When ``null_resource.deploy.triggers.healthcheck_sh`` を読む
        Then ``filemd5("${local.scripts_dir}/healthcheck.sh")`` で参照している。

        triggers/source 不整合（issue #157 の動機）の直接的リグレッション保証。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None
        triggers = extract_block(block, r"triggers")
        assert triggers is not None

        match = re.search(
            r'healthcheck_sh\s*=\s*filemd5\(\s*"\$\{local\.scripts_dir\}/healthcheck\.sh"\s*\)',
            triggers,
        )

        assert match is not None, 'triggers.healthcheck_sh が filemd5("${local.scripts_dir}/healthcheck.sh") でない'

    def test_triggers_notify_sh_uses_local_scripts_dir(self):
        """Given main.tf
        When ``null_resource.deploy.triggers.notify_sh`` を読む
        Then ``filemd5("${local.scripts_dir}/notify.sh")`` で参照している。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None
        triggers = extract_block(block, r"triggers")
        assert triggers is not None

        match = re.search(
            r'notify_sh\s*=\s*filemd5\(\s*"\$\{local\.scripts_dir\}/notify\.sh"\s*\)',
            triggers,
        )

        assert match is not None, 'triggers.notify_sh が filemd5("${local.scripts_dir}/notify.sh") でない'

    def test_triggers_logrotate_conf_uses_local_scripts_dir(self):
        """Given main.tf
        When ``null_resource.deploy.triggers.logrotate_conf`` を読む
        Then ``filemd5("${local.scripts_dir}/logrotate.conf")`` で参照している。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None
        triggers = extract_block(block, r"triggers")
        assert triggers is not None

        match = re.search(
            r'logrotate_conf\s*=\s*filemd5\(\s*"\$\{local\.scripts_dir\}/logrotate\.conf"\s*\)',
            triggers,
        )

        assert match is not None, 'triggers.logrotate_conf が filemd5("${local.scripts_dir}/logrotate.conf") でない'

    def test_triggers_cron_d_uses_local_scripts_dir(self):
        """Given main.tf
        When ``null_resource.deploy.triggers.cron_d`` を読む
        Then ``filemd5("${local.scripts_dir}/cron.d")`` で参照している。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None
        triggers = extract_block(block, r"triggers")
        assert triggers is not None

        match = re.search(
            r'cron_d\s*=\s*filemd5\(\s*"\$\{local\.scripts_dir\}/cron\.d"\s*\)',
            triggers,
        )

        assert match is not None, 'triggers.cron_d が filemd5("${local.scripts_dir}/cron.d") でない'

    def test_provisioner_file_healthcheck_sh_sources_local_scripts_dir(self):
        """Given main.tf
        When healthcheck.sh を /opt/youtube-stream/bin/healthcheck.sh に配置する provisioner を読む
        Then ``source = "${local.scripts_dir}/healthcheck.sh"`` で参照している。

        refactor で source 4 つの取り違え（並べ替えバグ）を防止するため、
        source/destination のペアリングを順序非依存で検証する。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None

        match = re.search(
            r'provisioner\s+"file"\s*\{[^}]*?'
            r'source\s*=\s*"\$\{local\.scripts_dir\}/healthcheck\.sh"[^}]*?'
            r'destination\s*=\s*"/opt/youtube-stream/bin/healthcheck\.sh"[^}]*?\}',
            block,
            flags=re.DOTALL,
        )
        match_alt = re.search(
            r'provisioner\s+"file"\s*\{[^}]*?'
            r'destination\s*=\s*"/opt/youtube-stream/bin/healthcheck\.sh"[^}]*?'
            r'source\s*=\s*"\$\{local\.scripts_dir\}/healthcheck\.sh"[^}]*?\}',
            block,
            flags=re.DOTALL,
        )

        assert match or match_alt, (
            'provisioner "file" で source="${local.scripts_dir}/healthcheck.sh" → '
            "/opt/youtube-stream/bin/healthcheck.sh のアップロードが宣言されていない"
        )

    def test_provisioner_file_notify_sh_sources_local_scripts_dir(self):
        """Given main.tf
        When notify.sh を /opt/youtube-stream/bin/notify.sh に配置する provisioner を読む
        Then ``source = "${local.scripts_dir}/notify.sh"`` で参照している。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None

        match = re.search(
            r'provisioner\s+"file"\s*\{[^}]*?'
            r'source\s*=\s*"\$\{local\.scripts_dir\}/notify\.sh"[^}]*?'
            r'destination\s*=\s*"/opt/youtube-stream/bin/notify\.sh"[^}]*?\}',
            block,
            flags=re.DOTALL,
        )
        match_alt = re.search(
            r'provisioner\s+"file"\s*\{[^}]*?'
            r'destination\s*=\s*"/opt/youtube-stream/bin/notify\.sh"[^}]*?'
            r'source\s*=\s*"\$\{local\.scripts_dir\}/notify\.sh"[^}]*?\}',
            block,
            flags=re.DOTALL,
        )

        assert match or match_alt, (
            'provisioner "file" で source="${local.scripts_dir}/notify.sh" → '
            "/opt/youtube-stream/bin/notify.sh のアップロードが宣言されていない"
        )

    def test_provisioner_file_logrotate_conf_sources_local_scripts_dir(self):
        """Given main.tf
        When logrotate.conf を /etc/logrotate.d/youtube-stream に配置する provisioner を読む
        Then ``source = "${local.scripts_dir}/logrotate.conf"`` で参照している。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None

        match = re.search(
            r'provisioner\s+"file"\s*\{[^}]*?'
            r'source\s*=\s*"\$\{local\.scripts_dir\}/logrotate\.conf"[^}]*?'
            r'destination\s*=\s*"/etc/logrotate\.d/youtube-stream"[^}]*?\}',
            block,
            flags=re.DOTALL,
        )
        match_alt = re.search(
            r'provisioner\s+"file"\s*\{[^}]*?'
            r'destination\s*=\s*"/etc/logrotate\.d/youtube-stream"[^}]*?'
            r'source\s*=\s*"\$\{local\.scripts_dir\}/logrotate\.conf"[^}]*?\}',
            block,
            flags=re.DOTALL,
        )

        assert match or match_alt, (
            'provisioner "file" で source="${local.scripts_dir}/logrotate.conf" → '
            "/etc/logrotate.d/youtube-stream のアップロードが宣言されていない"
        )

    def test_provisioner_file_cron_d_sources_local_scripts_dir(self):
        """Given main.tf
        When cron.d を /etc/cron.d/youtube-stream-healthcheck に配置する provisioner を読む
        Then ``source = "${local.scripts_dir}/cron.d"`` で参照している。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None

        match = re.search(
            r'provisioner\s+"file"\s*\{[^}]*?'
            r'source\s*=\s*"\$\{local\.scripts_dir\}/cron\.d"[^}]*?'
            r'destination\s*=\s*"/etc/cron\.d/youtube-stream-healthcheck"[^}]*?\}',
            block,
            flags=re.DOTALL,
        )
        match_alt = re.search(
            r'provisioner\s+"file"\s*\{[^}]*?'
            r'destination\s*=\s*"/etc/cron\.d/youtube-stream-healthcheck"[^}]*?'
            r'source\s*=\s*"\$\{local\.scripts_dir\}/cron\.d"[^}]*?\}',
            block,
            flags=re.DOTALL,
        )

        assert match or match_alt, (
            'provisioner "file" で source="${local.scripts_dir}/cron.d" → '
            "/etc/cron.d/youtube-stream-healthcheck のアップロードが宣言されていない"
        )

    def test_canonical_relative_path_literal_appears_exactly_once(self):
        """Given main.tf 全体（コメント除去前の生テキスト）
        When ``../../../.claude/skills/streaming/references`` リテラルの出現回数を数える
        Then 1 回だけ出現する（locals.scripts_dir の右辺のみ）。

        DRY 不変条件のリグレッション保証。Issue #157 の根本動機（triggers vs source
        不整合検知困難）を構造的に解決する。8 箇所の重複が局在化されていることを保証。
        """
        text = read_file(_MAIN_TF)

        occurrences = text.count("../../../.claude/skills/streaming/references")

        assert occurrences == 1, (
            f"main.tf に ../../../.claude/skills/streaming/references リテラルが {occurrences} 回出現している "
            "（locals に集約後、リテラルは locals 内 1 箇所のみであるべき）"
        )

    def test_no_hardcoded_path_module_scripts_streaming_outside_locals(self):
        """Given main.tf からコメントを除去し、さらに locals ブロックを除いた残部
        When ``${path.module}/../../../.claude/skills/streaming/references/`` パターンを探す
        Then 一切ヒットしない（locals 外に旧形式の path.module 直書きが残っていない）。

        旧形式の置換漏れ検知。``${path.module}/cloud-init.yaml`` 等を誤検出しないよう、
        パターンは ``/.claude/skills/streaming/references/`` まで含めた完全形に限定する。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))

        # locals ブロックを抽出して残部を作る
        locals_match = re.search(r"^\s*locals\s*\{", text, flags=re.MULTILINE)
        assert locals_match is not None, "locals ブロックが見つからない"
        block_start = locals_match.start()
        # ネストカウントで locals ブロック終了位置を探す
        depth = 0
        i = locals_match.end() - 1  # `{` の位置
        block_end: int | None = None
        while i < len(text):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    block_end = i + 1
                    break
            i += 1
        assert block_end is not None, "locals ブロックの終端が見つからない"

        remainder = text[:block_start] + text[block_end:]

        match = re.search(
            r"\$\{path\.module\}/\.\./\.\./\.\./\.claude/skills/streaming/references/",
            remainder,
        )

        assert match is None, (
            "locals ブロックの外側に "
            "${path.module}/../../../.claude/skills/streaming/references/ "
            "の旧形式リテラルが残っている（locals.scripts_dir への置換漏れ）"
        )


# ============================================================================
# main.tf — #153 で追加される vultr_firewall_group / vultr_firewall_rule
# ============================================================================


class TestMainTfFirewall:
    """``main.tf`` の #153 で追加される firewall リソース構造（22/tcp 限定）。

    order.md 推奨対応:
      - ``vultr_firewall_group "stream"`` (description あり)
      - ``vultr_firewall_rule "ssh"``（``for_each = toset(var.allowed_ssh_cidr)`` /
        protocol=tcp / ip_type=v4 / port=22 / subnet+subnet_size を CIDR 分解で算出）
      - ``vultr_instance.this`` に ``firewall_group_id = vultr_firewall_group.stream.id``
    """

    def test_vultr_firewall_group_stream_exists_with_description(self):
        """Given main.tf
        When vultr_firewall_group.stream を探す
        Then 定義されており description 行を持つ (R2, H3)。

        firewall 適用の親リソース。欠ければ rule が孤立する。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"vultr_firewall_group"\s+"stream"')
        assert block is not None, 'resource "vultr_firewall_group" "stream" が存在しない'
        assert re.search(r"description\s*=", block), "vultr_firewall_group.stream.description が無い"

    def test_vultr_firewall_rule_ssh_uses_for_each_toset(self):
        """Given main.tf
        When vultr_firewall_rule.ssh の for_each を読む
        Then ``for_each = toset(var.allowed_ssh_cidr)`` が宣言されている (R3, H4, E3)。

        toset() で安定アドレス化することで、中間要素削除時の index ズレ事故（誤 replace）を防ぐ
        （plan §検討したアプローチ参照）。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"vultr_firewall_rule"\s+"ssh"')
        assert block is not None, 'resource "vultr_firewall_rule" "ssh" が存在しない'
        assert re.search(
            r"for_each\s*=\s*toset\(\s*var\.allowed_ssh_cidr\s*\)",
            block,
        ), (
            "vultr_firewall_rule.ssh.for_each が toset(var.allowed_ssh_cidr) でない"
            "（list 直渡しは index ズレ事故の原因になる）"
        )

    def test_vultr_firewall_rule_ssh_links_firewall_group(self):
        """Given main.tf
        When vultr_firewall_rule.ssh の firewall_group_id を読む
        Then ``firewall_group_id = vultr_firewall_group.stream.id`` で親リソースに結線されている
        (R3a, H5)。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"vultr_firewall_rule"\s+"ssh"')
        assert block is not None
        assert re.search(
            r"firewall_group_id\s*=\s*vultr_firewall_group\.stream\.id",
            block,
        ), (
            "vultr_firewall_rule.ssh.firewall_group_id が vultr_firewall_group.stream.id でない"
            "（rule が親 group に紐付かない）"
        )

    def test_vultr_firewall_rule_ssh_uses_tcp_v4_port_22(self):
        """Given main.tf
        When vultr_firewall_rule.ssh の protocol / ip_type / port を読む
        Then ``protocol="tcp"`` / ``ip_type="v4"`` / ``port="22"`` (R3b, H6)。

        SSH 22/tcp 限定の核。order.md スコープ通りに IPv4 の 22/tcp のみ。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"vultr_firewall_rule"\s+"ssh"')
        assert block is not None
        assert re.search(r'protocol\s*=\s*"tcp"', block), 'vultr_firewall_rule.ssh.protocol が "tcp" でない'
        assert re.search(r'ip_type\s*=\s*"v4"', block), 'vultr_firewall_rule.ssh.ip_type が "v4" でない'
        assert re.search(r'port\s*=\s*"22"', block), 'vultr_firewall_rule.ssh.port が "22" でない'

    def test_vultr_firewall_rule_ssh_decomposes_cidr_into_subnet_and_size(self):
        """Given main.tf
        When vultr_firewall_rule.ssh の subnet / subnet_size を読む
        Then ``subnet = split("/", each.value)[0]`` /
             ``subnet_size = tonumber(split("/", each.value)[1])`` (R3c, H7)。

        Vultr API は CIDR ではなく subnet+subnet_size の 2 値で要求するため、
        each.value（"203.0.113.5/32" 形式）を split で分解する必要がある。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"vultr_firewall_rule"\s+"ssh"')
        assert block is not None
        assert re.search(
            r'subnet\s*=\s*split\(\s*"/"\s*,\s*each\.value\s*\)\[\s*0\s*\]',
            block,
        ), 'subnet が split("/", each.value)[0] でない'
        assert re.search(
            r'subnet_size\s*=\s*tonumber\(\s*split\(\s*"/"\s*,\s*each\.value\s*\)\[\s*1\s*\]\s*\)',
            block,
        ), 'subnet_size が tonumber(split("/", each.value)[1]) でない'

    def test_vultr_firewall_rule_ssh_subnet_is_not_literal(self):
        """Given main.tf
        When vultr_firewall_rule.ssh の subnet を読む
        Then ``0.0.0.0`` 等のリテラル直書きでない (X3)。

        plan アンチパターン「全開放リテラル直書き」防止。subnet は each.value 由来であるべき。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"vultr_firewall_rule"\s+"ssh"')
        assert block is not None
        assert not re.search(r'subnet\s*=\s*"0\.0\.0\.0"', block), (
            'vultr_firewall_rule.ssh.subnet が "0.0.0.0" リテラル（全開放）'
        )
        # 任意の IPv4 リテラル直書きを禁止（subnet は split(...) 由来であるべき）
        assert not re.search(r'subnet\s*=\s*"\d+\.\d+\.\d+\.\d+"', block), (
            "vultr_firewall_rule.ssh.subnet に IPv4 リテラルが直書きされている（CIDR は each.value 由来であるべき）"
        )

    def test_vultr_firewall_rule_ssh_does_not_use_other_ports(self):
        """Given main.tf
        When vultr_firewall_rule.ssh の port 属性を全件走査する
        Then ``"22"`` 以外の ``port = "..."`` リテラルが存在しない (X1)。

        スコープ越境防止: order.md は SSH 22 のみ、80/443 等の追加ポートは別 issue。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"vultr_firewall_rule"\s+"ssh"')
        assert block is not None
        # port = "<value>" の <value> が "22" 以外の値を取っていないこと
        ports = re.findall(r'port\s*=\s*"([^"]*)"', block)
        non_22 = [p for p in ports if p != "22"]
        assert not non_22, (
            f"vultr_firewall_rule.ssh に 22 以外の port リテラルが存在: {non_22}"
            "（order.md スコープ外。80/443 等は別 issue）"
        )

    def test_vultr_firewall_rule_ssh_does_not_use_ip_type_v6(self):
        """Given main.tf
        When vultr_firewall_rule.ssh を読む
        Then ``ip_type = "v6"`` が存在しない (X2)。

        order.md は IPv4 のみ。IPv6 firewall rule の追加は別 issue。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"vultr_firewall_rule"\s+"ssh"')
        assert block is not None
        assert not re.search(r'ip_type\s*=\s*"v6"', block), (
            'vultr_firewall_rule.ssh に ip_type = "v6" が含まれている（order.md スコープ外）'
        )

    def test_only_one_vultr_firewall_rule_resource_declared(self):
        """Given main.tf
        When ``resource "vultr_firewall_rule" "..."`` の宣言を全件走査する
        Then ``"ssh"`` の 1 個のみ (X4)。

        スコープ越境防止: 追加 rule リソース（80/443 / IPv6 等）を「ついで」に追加しない。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        rules = re.findall(r'resource\s+"vultr_firewall_rule"\s+"(\w+)"', text)
        assert rules == ["ssh"], (
            f"vultr_firewall_rule リソースが ['ssh'] 以外になっている: {rules}（order.md スコープ外。SSH 22 1 個のみ）"
        )

    def test_vultr_instance_has_firewall_group_id_wiring(self):
        """Given main.tf
        When vultr_instance.this の firewall_group_id を読む
        Then ``firewall_group_id = vultr_firewall_group.stream.id`` で結線されている (R4, H8)。

        plan §配線確認チェックリスト #4。配線漏れすると firewall を作っても無効。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"vultr_instance"\s+"this"')
        assert block is not None
        assert re.search(
            r"firewall_group_id\s*=\s*vultr_firewall_group\.stream\.id",
            block,
        ), (
            "vultr_instance.this.firewall_group_id が vultr_firewall_group.stream.id でない"
            "（配線漏れ。firewall を作っても instance に適用されない）"
        )

    def test_vultr_instance_has_no_explicit_depends_on_for_firewall(self):
        """Given main.tf
        When vultr_instance.this ブロックを読む
        Then ``depends_on = [...]`` の明示宣言が存在しない (E4)。

        plan アンチパターン #3: ``firewall_group_id`` 参照で暗黙依存が成立するため、
        冗長な depends_on は禁止。既存 ``test_no_explicit_depends_on_for_null_resource`` と同方針。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"vultr_instance"\s+"this"')
        assert block is not None
        # 行頭からインデント込みで `depends_on = [` が現れる箇所が無いこと
        assert not re.search(r"^\s*depends_on\s*=\s*\[", block, flags=re.MULTILINE), (
            "vultr_instance.this に明示的な depends_on を書いてはならない "
            "（plan アンチパターン #3、firewall_group_id 参照で暗黙依存が成立する）"
        )


# ============================================================================
# templates/youtube-stream.env.tftpl — #125 新規ファイル
# ============================================================================


class TestEnvTftpl:
    """``templates/youtube-stream.env.tftpl`` の env テンプレ内容（#125）。

    systemd ``EnvironmentFile`` 形式（``KEY=VALUE``、引用符なし）。terraform ``templatefile()``
    が ``${video}`` / ``${rtmp_url}`` を実値に展開し、systemd は env file をロードするだけ。
    """

    def test_file_exists(self):
        """Given infra/terraform/streaming/templates/
        When youtube-stream.env.tftpl を探す
        Then 存在する。
        """
        assert _ENV_TFTPL.exists(), "templates/youtube-stream.env.tftpl が存在しない"

    def test_contains_video_variable_assignment(self):
        """Given env tftpl
        When 全文を読む
        Then ``VIDEO=${video}`` 行がある（terraform templatefile で展開される変数記法）。

        値はクォートしない（systemd EnvironmentFile の慣例。クォートすると文字列に含まれてしまう）。
        """
        text = read_file(_ENV_TFTPL)
        assert re.search(r"^VIDEO=\$\{video\}\s*$", text, flags=re.MULTILINE), (
            "VIDEO=${video} 行が存在しない（terraform templatefile 変数記法を使うこと）"
        )

    def test_contains_rtmp_url_variable_assignment(self):
        """Given env tftpl
        When 全文を読む
        Then ``RTMP_URL=${rtmp_url}`` 行がある。
        """
        text = read_file(_ENV_TFTPL)
        assert re.search(r"^RTMP_URL=\$\{rtmp_url\}\s*$", text, flags=re.MULTILINE), (
            "RTMP_URL=${rtmp_url} 行が存在しない（terraform templatefile 変数記法を使うこと）"
        )

    def test_does_not_contain_systemd_style_dollar_var_for_known_keys(self):
        """Given env tftpl
        When 全文を読む
        Then ``$VIDEO`` / ``$RTMP_URL`` の systemd 参照記法（波括弧なし）が含まれていない。

        env file 内では既にリテラル値に展開済の値が並ぶべき。``$NAME`` は systemd unit の
        ``ExecStart`` 側で参照する記法であり、env file 内に書くのは誤り。
        """
        text = read_file(_ENV_TFTPL)
        # `${VIDEO}` ではなく `$VIDEO`（直後が { でない）パターンを検出
        assert not re.search(r"\$VIDEO\b(?!\s*\})", text), (
            "$VIDEO（systemd 参照記法）が env file に書かれている。${video} を使うこと"
        )
        assert not re.search(r"\$RTMP_URL\b(?!\s*\})", text), (
            "$RTMP_URL（systemd 参照記法）が env file に書かれている。${rtmp_url} を使うこと"
        )

    def test_does_not_contain_plaintext_secrets(self):
        """Given env tftpl
        When 全文を読む
        Then ``rtmp://`` URL や動画パスのリテラルが含まれていない（テンプレート段階では未展開）。

        secret は terraform templatefile() の variables map 経由でだけ流入させる。
        """
        text = read_file(_ENV_TFTPL)
        assert not re.search(r"rtmp://", text), "rtmp:// が env tftpl に直書きされている（${rtmp_url} を使うこと）"
        assert not re.search(
            r"/opt/youtube-stream/videos/[^\s$]+\.(mp4|mkv|mov|webm)",
            text,
            flags=re.IGNORECASE,
        ), "動画ファイルパスが env tftpl に直書きされている（${video} を使うこと）"

    def test_values_are_not_quoted(self):
        """Given env tftpl
        When VIDEO / RTMP_URL の右辺を読む
        Then 値がクォート（``"..."`` / ``'...'``）で囲まれていない。

        systemd ``EnvironmentFile`` は ``KEY=VALUE`` の VALUE を素のまま読む。クォートすると
        文字列の一部とみなされ、ffmpeg の引数解釈で破綻する。
        """
        text = read_file(_ENV_TFTPL)
        assert not re.search(r"^VIDEO=['\"]", text, flags=re.MULTILINE), (
            "VIDEO の値がクォートされている（systemd EnvironmentFile の慣例違反）"
        )
        assert not re.search(r"^RTMP_URL=['\"]", text, flags=re.MULTILINE), (
            "RTMP_URL の値がクォートされている（systemd EnvironmentFile の慣例違反）"
        )


# ============================================================================
# terraform.tfvars.example — #125 で video_path / TF_VAR_stream_key 注入手順を追記
# ============================================================================


class TestTfvarsExampleStreamKey:
    """``terraform.tfvars.example`` の #125 追加項目の secret 漏洩防止。"""

    def test_does_not_contain_stream_key_assignment(self):
        """Given terraform.tfvars.example
        When ファイル内容（コメント除去後）を読む
        Then ``stream_key = "..."`` のアクティブ代入が存在しない。

        secret は TF_VAR_stream_key 経由で渡す前提で、サンプルにも値を書かない
        （既存 ``test_does_not_contain_vultr_api_key_assignment`` と同種規約）。
        """
        text = strip_hcl_comments(read_file(_TFVARS_EXAMPLE))
        assert not re.search(r"^\s*stream_key\s*=", text, flags=re.MULTILINE), (
            "stream_key の代入がアクティブ行に存在する（secret 漏洩リスク）"
        )

    def test_mentions_tf_var_stream_key_in_comments(self):
        """Given terraform.tfvars.example
        When ファイル内容（コメント込み）を読む
        Then ``TF_VAR_stream_key`` の使い方がコメントに記載されている。

        運用者が secret 注入方法を発見できるよう、`vultr_api_key` と並列で説明する。
        """
        raw = read_file(_TFVARS_EXAMPLE)
        assert "TF_VAR_stream_key" in raw, (
            "TF_VAR_stream_key の案内コメントが無い（運用者が secret 注入方法を発見できない）"
        )

    def test_mentions_op_read_for_stream_key(self):
        """Given terraform.tfvars.example
        When ファイル内容（コメント込み）を読む
        Then ``op read`` による 1Password CLI 注入の案内が含まれている。

        ルート ``README.md`` / ``infra/terraform/gcp/terraform.tfvars.example`` の慣例を踏襲。
        """
        raw = read_file(_TFVARS_EXAMPLE)
        assert "op read" in raw, "op read（1Password CLI）による secret 注入手順がコメントに無い"

    def test_video_path_assignment_is_active(self):
        """Given terraform.tfvars.example
        When ファイル内容（コメント除去後）を読む
        Then ``video_path = "..."`` がアクティブ行（コメントアウトされていない行）に存在する。

        ``video_path`` はデフォルト値を持たない必須項目のため、サンプルでも明示する。
        """
        text = strip_hcl_comments(read_file(_TFVARS_EXAMPLE))
        assert re.search(r"^\s*video_path\s*=\s*\"", text, flags=re.MULTILINE), (
            'video_path = "..." がアクティブ行に存在しない（必須項目だがサンプルから発見できない）'
        )

    def test_does_not_mention_ssh_priv_key_path(self):
        """Given terraform.tfvars.example
        When ファイル内容（raw text、コメント込み）を読む
        Then ``ssh_priv_key_path`` キーワードがどこにも含まれていない。

        #154 で variables.tf から ``ssh_priv_key_path`` を撤去したため、サンプルにコメント行で
        残っていると、利用者がコメントアウト解除した際に「Reference to undeclared input
        variable」で apply が失敗する。
        """
        raw = read_file(_TFVARS_EXAMPLE)
        assert "ssh_priv_key_path" not in raw, (
            "terraform.tfvars.example に ssh_priv_key_path が残っている"
            "（撤去済み変数。利用者が有効化すると undeclared input variable で fail する）"
        )


# ============================================================================
# terraform.tfvars.example — #153 で allowed_ssh_cidr の必須サンプル追記
# ============================================================================


class TestTfvarsExampleFirewall:
    """``terraform.tfvars.example`` の #153 ``allowed_ssh_cidr`` discoverability。"""

    def test_allowed_ssh_cidr_assignment_is_active_with_slash_32_placeholder(self):
        """Given terraform.tfvars.example
        When ファイル内容（コメント除去後）を読む
        Then ``allowed_ssh_cidr = ["..."]`` がアクティブ行に存在し、``/32`` プレースホルダーを含む
        (R6, H9)。

        ``allowed_ssh_cidr`` は default = [] かつ validation で空入力を拒否する必須項目。
        operator がサンプルから視認できる必要があるため、``video_path`` と同様にアクティブ代入で示す。
        ``/32``（ホスト 1 台限定）が運用上自然なプレースホルダー。
        """
        text = strip_hcl_comments(read_file(_TFVARS_EXAMPLE))
        # アクティブ行（コメントアウトされていない行）に allowed_ssh_cidr = [...] が存在する
        match = re.search(
            r"^\s*allowed_ssh_cidr\s*=\s*\[([^\]]*)\]",
            text,
            flags=re.MULTILINE,
        )
        assert match is not None, (
            'allowed_ssh_cidr = ["..."] がアクティブ行に存在しない（必須項目だがサンプルから発見できない）'
        )
        list_body = match.group(1)
        assert "/32" in list_body, (
            "allowed_ssh_cidr のサンプル値に /32 プレースホルダーが含まれていない"
            "（ホスト 1 台限定の運用想定が伝わらない）"
        )


# ============================================================================
# infra/terraform/streaming/README.md — #125 新規ドキュメント
# ============================================================================


class TestStreamingReadme:
    """``infra/terraform/streaming/README.md`` の最低限の記載項目（#125）。

    order.md「secret 注入手順を README に記載」を満たし、運用者が ``terraform apply`` から
    動作確認まで辿れる導線を提供する。

    本テストは README の文章スタイルや章立て順序は問わない。**運用上クリティカルなキーワード**の
    包含のみ検証する（執筆の自由度を残す）。
    """

    def test_file_exists(self):
        """Given infra/terraform/streaming/
        When README.md を探す
        Then 存在する（gcp モジュールと並列の慣例）。
        """
        assert _STREAMING_README.exists(), "infra/terraform/streaming/README.md が存在しない"

    def test_mentions_tf_var_stream_key(self):
        """Given README
        When 全文を読む
        Then ``TF_VAR_stream_key`` 環境変数の言及がある（secret 注入の入口）。
        """
        text = read_file(_STREAMING_README)
        assert "TF_VAR_stream_key" in text, "README に TF_VAR_stream_key の言及が無い（secret 注入手順が辿れない）"

    def test_mentions_tf_var_vultr_api_key(self):
        """Given README
        When 全文を読む
        Then ``TF_VAR_vultr_api_key`` の言及がある（既存 secret も再掲する）。
        """
        text = read_file(_STREAMING_README)
        assert "TF_VAR_vultr_api_key" in text, (
            "README に TF_VAR_vultr_api_key の言及が無い（運用者が必要 env を網羅できない）"
        )

    def test_mentions_op_read_for_secret_injection(self):
        """Given README
        When 全文を読む
        Then ``op read`` による 1Password CLI 経由の secret 注入手順がある。
        """
        text = read_file(_STREAMING_README)
        assert "op read" in text, "README に op read（1Password CLI）の手順が無い"

    def test_mentions_terraform_apply_command(self):
        """Given README
        When 全文を読む
        Then ``terraform apply`` 実行手順が含まれている。
        """
        text = read_file(_STREAMING_README)
        assert re.search(r"terraform[^\n]*apply", text), "README に terraform apply の実行コマンドが書かれていない"

    def test_documents_encrypted_remote_tfstate_backend(self):
        """Given README
        When tfstate の説明を読む
        Then remote backend と暗号化 state の保存先が説明されている。
        """
        text = read_file(_STREAMING_README)
        assert 'backend "s3"' in text, 'README に backend "s3" の説明が無い'
        assert _TFSTATE_BACKEND_BUCKET in text, "README に tfstate bucket 名の説明が無い"
        assert _TFSTATE_BACKEND_KEY in text, "README に streaming tfstate key の説明が無い"
        assert "KMS" in text, "README に KMS 暗号化の説明が無い"
        assert "DynamoDB lock" in text, "README に DynamoDB lock の説明が無い"

    def test_documents_sensitive_is_cli_mask_only(self):
        """Given README
        When sensitive と tfstate の説明を読む
        Then sensitive=true は CLI 出力マスクのみであると説明されている。
        """
        text = read_file(_STREAMING_README)
        assert "CLI 出力マスクのみ" in text, (
            "README に sensitive=true が CLI マスクのみである説明が無い"
        )
        assert "tfstate JSON の値を暗号化しない" in text, (
            "README に sensitive=true が tfstate JSON を暗号化しない説明が無い"
        )

    def test_does_not_describe_nonsensitive_hash_as_unconditionally_safe(self):
        """Given README
        When nonsensitive(sha256(...)) の説明を読む
        Then hash 化の安全性を高エントロピー secret に限定している。
        """
        text = read_file(_STREAMING_README)
        assert "脱 sensitive 安全" not in text, (
            "README が nonsensitive(sha256(...)) を常に安全と誤読させる"
        )
        assert "高エントロピー" in text, (
            "README に hash 化の前提が高エントロピー secret である説明が無い"
        )
        assert "低エントロピー値" in text, (
            "README に低エントロピー値の hash 化が secret 保護でない説明が無い"
        )

    def test_mentions_systemctl_status_for_verification(self):
        """Given README
        When 全文を読む
        Then ``systemctl status`` 等の動作確認コマンドが書かれている。

        order.md「動作確認」セクションの最低限の引用。
        """
        text = read_file(_STREAMING_README)
        assert "systemctl" in text, "README に systemctl 系の動作確認コマンドが書かれていない"

    def test_mentions_11h_1h_streaming_cycle(self):
        """Given README
        When 全文を読む
        Then 11h 配信 / 1h 休止サイクルの説明が含まれている。

        利用者が「なぜ 11h で勝手に止まるか」を理解できる必要がある（systemd 由来の挙動）。
        """
        text = read_file(_STREAMING_README)
        # 「11h」「11 時間」「RuntimeMaxSec」のいずれかでカバー
        has_11h = "11h" in text or "11 時間" in text or "11時間" in text
        has_runtime_max = "RuntimeMaxSec" in text
        assert has_11h or has_runtime_max, (
            "README に 11h サイクル / RuntimeMaxSec の説明が無い（systemd 由来の自動停止が説明されない）"
        )

    def test_does_not_contain_plaintext_stream_key(self):
        """Given README
        When 全文を読む
        Then 実 stream key っぽいリテラル（``rtmp://...`` の URL 末尾値）が直書きされていない。

        ドキュメントとしての例示でも、実際の YouTube stream key 形式（連続英数字）を書かないこと。
        """
        text = read_file(_STREAMING_README)
        # rtmp://a.rtmp.youtube.com/live2/<英数字 8 文字以上> っぽいパターンを検出
        assert not re.search(
            r"rtmp://[\w.]+/live2/[A-Za-z0-9]{8,}",
            text,
        ), "README に実 stream key を含む rtmp URL が書かれている可能性（漏洩リスク）"

    def test_does_not_mention_ssh_priv_key_path(self):
        """Given README
        When 全文を読む
        Then ``ssh_priv_key_path`` キーワードがどこにも含まれていない。

        #154 で variables.tf から撤去された変数。README に残るとドキュメント / 実装乖離になり、
        運用者が「設定したのに反映されない」混乱を起こす。仕様準拠（README ↔ 実装）の保証。
        """
        text = read_file(_STREAMING_README)
        assert "ssh_priv_key_path" not in text, (
            "README に ssh_priv_key_path の言及が残っている（撤去済み変数。ドキュメント / 実装乖離）"
        )

    def test_mentions_ssh_add_for_agent_setup(self):
        """Given README
        When 全文を読む
        Then ``ssh-add`` コマンドの言及がある（ssh-agent への鍵登録手順）。

        #154 で ``connection.agent = true`` に切り替えたため、``terraform apply`` 成功の起動条件が
        「秘密鍵ファイルの存在」から「ssh-agent に鍵が登録されていること」に変わる。
        運用者が前提を満たせる導線として ``ssh-add`` 系コマンドの言及が必要。
        既存 ``test_mentions_*`` 系の緩い包含検査スタイルを踏襲（章立て自由度を残す）。
        """
        text = read_file(_STREAMING_README)
        assert "ssh-add" in text, (
            "README に ssh-add の言及が無い（ssh-agent 登録手順が辿れず terraform apply が失敗する）"
        )


# ============================================================================
# infra/terraform/streaming/README.md — #111 動画差し替え手順
# ============================================================================


class TestStreamingReadmeVideoSwap:
    """``infra/terraform/streaming/README.md`` 「動画の差し替え手順」セクション（#111）。

    依存 #125 で実装済みの ``null_resource.deploy`` (filemd5 trigger / current.mp4 上書き /
    systemctl restart) を運用フェーズで使うための手順ドキュメントを検証する。

    本テストは README の章立て順序や文章スタイルを問わず、運用上クリティカルなキーワードの
    包含のみ検証する（執筆の自由度を残す）。order.md「動画差し替え手順」のタスク項目と
    plan.md §write_tests ステップ指示に対応。
    """

    def test_has_video_swap_section_heading(self):
        """Given README
        When 全文を読む
        Then 「動画の差し替え」を含む Markdown 見出し（``##`` / ``###``）が存在する。

        運用者が見出しから瞬時に当該手順に到達できるよう、章として独立している必要がある。
        """
        text = read_file(_STREAMING_README)
        # ## または ### 行で「動画の差し替え」または「動画差し替え」を含む見出しがあること
        assert re.search(
            r"^#{2,3}\s+[^\n]*動画(の)?差し替え",
            text,
            flags=re.MULTILINE,
        ), "README に「動画(の)?差し替え」を含む ## / ### 見出しが無い（運用者が章を辿れない）"

    def test_mentions_tf_var_video_path(self):
        """Given README
        When 全文を読む
        Then ``TF_VAR_video_path`` 環境変数の言及がある。

        差し替え時に新しい動画パスを Terraform に渡すための env 名を運用者が
        正確に知る必要がある（typo すれば ``var.video_path is required`` で失敗する）。
        """
        text = read_file(_STREAMING_README)
        assert "TF_VAR_video_path" in text, (
            "README に TF_VAR_video_path の言及が無い（差し替え時の env 注入手順が辿れない）"
        )

    def test_mentions_terraform_plan_for_diff_check(self):
        """Given README
        When 全文を読む
        Then ``terraform ... plan`` の差分確認手順が記載されている。

        order.md「``terraform plan`` で **新動画 only** の差分が出ることの確認手順」要件。
        apply 前に意図しないリソース（``vultr_instance`` 等）の replace を察知する導線。
        """
        text = read_file(_STREAMING_README)
        assert re.search(r"terraform[^\n]*plan", text), (
            "README に terraform plan の差分確認手順が無い（apply 前の安全確認導線が欠落）"
        )

    def test_mentions_idle_window_for_zero_downtime(self):
        """Given README
        When 全文を読む
        Then 「休止」または「ダウンタイム」または「0 秒」のいずれかが書かれている。

        order.md「休止時間に実施するのが視聴者には透明」運用 tips 要件。
        運用者が「いつ apply すべきか」の判断軸を README から得られる必要がある。
        """
        text = read_file(_STREAMING_README)
        has_idle = "休止" in text
        has_downtime = "ダウンタイム" in text
        has_zero_sec = "0 秒" in text or "0秒" in text
        assert has_idle or has_downtime or has_zero_sec, (
            "README に休止時間 / ダウンタイム / 0 秒 のいずれの運用 tips も無い"
            "（視聴者影響を踏まえた実施タイミングの判断軸が欠落）"
        )

    def test_mentions_idempotency_with_filemd5(self):
        """Given README
        When 全文を読む
        Then 「filemd5」または「no-op」または「冪等」のいずれかが書かれている。

        order.md テスト第 3 項「同じ動画で再 apply → no-op（filemd5 不変）」の運用根拠。
        運用者が「動かない」と誤認しないよう、冪等性の仕組みを README から読み取れる必要がある。
        """
        text = read_file(_STREAMING_README)
        has_filemd5 = "filemd5" in text
        has_noop = "no-op" in text
        has_idempotent = "冪等" in text
        assert has_filemd5 or has_noop or has_idempotent, (
            "README に filemd5 / no-op / 冪等 のいずれの言及も無い"
            "（同一動画で再 apply した時の挙動が運用者に伝わらない）"
        )

    def test_mentions_current_mp4_overwrite(self):
        """Given README
        When 全文を読む
        Then ``current.mp4`` への上書き（旧動画削除の自然解消）に触れている。

        order.md 完了条件「旧動画は VPS 上に明示的に削除する仕組みを用意」を、
        単一ファイル方式（``provisioner "file"`` が毎回上書き）で満たす根拠を README に明記する。
        """
        text = read_file(_STREAMING_README)
        assert "current.mp4" in text, (
            "README に current.mp4 への上書きの言及が無い（旧動画が自然消去される根拠が辿れない）"
        )

    def test_mentions_swap_video_script(self):
        """Given README
        When 全文を読む
        Then ``swap_video.sh`` への到達導線（言及）が存在する。

        order.md「スクリプト化（任意）: ``scripts/streaming/swap_video.sh``」「1 コマンド
        ラッパーとして提供」要件。ラッパーを追加しても README から発見できなければ運用者は
        到達できないため、README が `swap_video.sh` という識別子に言及していることを担保する。
        """
        text = read_file(_STREAMING_README)
        assert "swap_video.sh" in text, (
            "README に swap_video.sh の言及が無い（1 コマンドラッパーへの到達導線が欠落し、運用者が発見できない）"
        )


# ============================================================================
# infra/terraform/streaming/README.md — #153 allowed_ssh_cidr の手順記載
# ============================================================================


class TestStreamingReadmeFirewall:
    """``infra/terraform/streaming/README.md`` の #153 ``allowed_ssh_cidr`` 手順言及。

    operator が CIDR 設定手順（IP 取得 → /32 化 → tfvars 記載）を辿れる導線を担保する。
    本テストは README の章立て順序や文章スタイルは問わず、運用上クリティカルなキーワード
    包含のみ検証する（執筆の自由度を残す）。
    """

    def test_mentions_allowed_ssh_cidr(self):
        """Given README
        When 全文を読む
        Then ``allowed_ssh_cidr`` キーワードの言及がある (R7, H10)。

        手順書からの到達経路。設定 key 名を README から発見できる必要がある。
        """
        text = read_file(_STREAMING_README)
        assert "allowed_ssh_cidr" in text, (
            "README に allowed_ssh_cidr の言及が無い（operator が必須項目を発見できず、CIDR 設定手順が辿れない）"
        )

    def test_mentions_ip_acquisition_path(self):
        """Given README
        When 全文を読む
        Then IP 取得導線（``/32`` / ``ifconfig.me`` / ``curl`` のいずれか）に言及している
        (R7, H11)。

        CIDR 化手順を運用者が辿れる必要がある。固定文言は要求しないが、
        「自分の IP を /32 で書く」という作業に対応するヒント語句が必須。
        """
        text = read_file(_STREAMING_README)
        has_slash_32 = "/32" in text
        has_ifconfig_me = "ifconfig.me" in text
        has_curl = "curl" in text
        assert has_slash_32 or has_ifconfig_me or has_curl, (
            "README に /32 / ifconfig.me / curl のいずれの言及も無い"
            "（CIDR 化手順 = IP 取得 → /32 化 が運用者に伝わらない）"
        )


# ============================================================================
# .claude/skills/streaming/references/swap_video.sh — #111 1 コマンドラッパー
# ============================================================================


class TestSwapVideoScript:
    """``.claude/skills/streaming/references/swap_video.sh`` の静的検査
    （#111 任意要件「1 コマンドラッパー」、#229 で skill 配布対象へ移動）。

    本スクリプトは ``TF_VAR_video_path`` を解決して export し、``terraform -chdir=...
    apply`` を起動するシェルラッパー。``terraform apply`` 単体運用も引き続き有効だが、
    `swap_video.sh <video-path>` で完了条件「1 コマンドで動画差替が完了」を堅く満たす。

    本テストは terraform バイナリ非依存の方針（既存 ``TestStreamingReadmeVideoSwap``
    と同様）に従い、ファイルテキスト・実行ビット・主要キーワードを正規表現で検証する。
    実行時挙動（subprocess での実 terraform 呼び出し / shellcheck 適用）はスコープ外。
    """

    def test_script_exists(self):
        """Given リポジトリ
        When ``.claude/skills/streaming/references/swap_video.sh`` を探す
        Then 当該ファイルが存在する。

        order.md「スクリプト化（任意）: ``swap_video.sh``」要件の最低条件。
        ラッパーは README から発見可能であっても、ファイルが無ければ叩けない。
        """
        assert _SWAP_VIDEO_SCRIPT.exists(), (
            f"{_SWAP_VIDEO_SCRIPT.relative_to(_REPO_ROOT)} が存在しない（1 コマンドラッパーが未実装）"
        )

    def test_script_is_executable(self):
        """Given スクリプトファイル
        When ファイル属性を確認
        Then 実行ビット（owner ``x``）が立っている。

        ``./.claude/skills/streaming/references/swap_video.sh <video>`` 形式で直接叩けるよう、
        実行属性が必要。``bash <path>/swap_video.sh`` 経由でしか動かないと
        運用者が事故る（タブ補完で失敗する）。
        """
        if not _SWAP_VIDEO_SCRIPT.exists():
            pytest.fail(f"{_SWAP_VIDEO_SCRIPT.relative_to(_REPO_ROOT)} が存在しない（先に実装が必要）")
        mode = _SWAP_VIDEO_SCRIPT.stat().st_mode
        # owner execute bit (0o100) が立っていること
        assert mode & 0o100, (
            f"{_SWAP_VIDEO_SCRIPT.relative_to(_REPO_ROOT)} に owner 実行ビットが無い"
            f"（chmod +x 漏れ。現在の mode: {oct(mode)}）"
        )

    def test_script_uses_strict_mode(self):
        """Given スクリプト本文
        When 全文を読む
        Then ``set -euo pipefail`` が記載されている。

        bash スクリプトの最低限の規律。`-e`（失敗即終了）, `-u`（未定義変数を fail）,
        `-o pipefail`（pipe 中の失敗を伝播）が無いと、provisioning 系の失敗が握りつぶされる。
        既存 ``.claude/skills/channel-setup/references/gcp-terraform-apply.sh:13`` と同方針。
        """
        text = read_file(_SWAP_VIDEO_SCRIPT)
        assert re.search(r"^set\s+-euo\s+pipefail\b", text, flags=re.MULTILINE), (
            "swap_video.sh に `set -euo pipefail` が無い（エラー握りつぶしリスク。Fail Fast 原則に違反）"
        )

    def test_script_exports_tf_var_video_path(self):
        """Given スクリプト本文
        When 全文を読む
        Then ``TF_VAR_video_path`` の export 行が記載されている。

        order.md 差し替え手順「``export TF_VAR_video_path=$(realpath ./new_video.mp4)``」
        を 1 コマンド化するのが本ラッパーの中核。env 注入が無ければ ``var.video_path``
        が解決できず terraform は ``Missing required argument`` で落ちる。
        """
        text = read_file(_SWAP_VIDEO_SCRIPT)
        assert re.search(r"export\s+TF_VAR_video_path\b", text), (
            "swap_video.sh に `export TF_VAR_video_path` が無い（差し替え対象の動画パスを Terraform に渡す経路が欠落）"
        )

    def test_script_uses_realpath_for_absolute_path(self):
        """Given スクリプト本文
        When 全文を読む
        Then ``realpath`` が呼び出されている。

        order.md「``$(realpath ./new_video.mp4)``」要件。Terraform の ``provisioner "file"``
        は実行時の cwd に依存するため、相対パスのまま渡すと別ディレクトリから叩いた時に
        破綻する。``realpath`` で絶対化する経路を必ず通す。
        """
        text = read_file(_SWAP_VIDEO_SCRIPT)
        assert re.search(r"\brealpath\b", text), (
            "swap_video.sh に `realpath` の呼び出しが無い"
            "（相対パス渡しで cwd 依存になり、別ディレクトリから叩くと破綻する）"
        )

    def test_script_runs_terraform_apply_with_chdir(self):
        """Given スクリプト本文
        When 全文を読む
        Then ``terraform`` の ``apply`` を ``-chdir=`` 付きで起動している。

        order.md「``TF_VAR_video_path`` をセットして ``terraform apply -auto-approve``」要件。
        既存 README が ``terraform -chdir=infra/terraform/streaming apply`` パターンで
        統一されているため、ラッパー側も ``-chdir=`` を使い記述パターンを揃える
        （plan.md「pushd ではなく -chdir= を使う」）。
        """
        text = read_file(_SWAP_VIDEO_SCRIPT)
        assert re.search(r"terraform\s+[^\n]*-chdir=", text), (
            "swap_video.sh に `terraform -chdir=...` が無い"
            "（既存 README の記述パターン (-chdir=) と不一致 / pushd 等の cwd 依存実装の疑い）"
        )
        assert re.search(r"terraform\s+[^\n]*\bapply\b", text), (
            "swap_video.sh に `terraform apply` 起動行が無い（差し替えを実行する本体コマンドが欠落）"
        )

    def test_script_default_apply_is_interactive(self):
        """Given スクリプト本文
        When 全文を読む
        Then ``-auto-approve`` の付与が条件分岐配下にある（無条件付与ではない）。

        plan.md「``--auto-approve`` は off（対話確認）」要件。デフォルトで
        ``-auto-approve`` を付けると誤 apply 事故のリスクが上がる。``--auto-approve``
        フラグを明示した時のみ ``-auto-approve`` を Terraform に渡す分岐構造であること。
        """
        text = read_file(_SWAP_VIDEO_SCRIPT)
        # `--auto-approve` のフラグハンドリング（引数パース）が存在する
        assert re.search(r"--auto-approve\b", text), (
            "swap_video.sh に `--auto-approve` 引数の取り扱いが無い"
            "（plan.md 仕様: フラグ off がデフォルト / 明示時のみ非対話 apply）"
        )
        # `terraform ... apply -auto-approve` が無条件に書かれていない
        # （= 直接 1 行で `terraform apply -auto-approve` を書くのは禁止。条件分岐配下が必須）
        unconditional = re.search(
            r"^[ \t]*terraform\s+[^\n]*\bapply\b[^\n]*-auto-approve",
            text,
            flags=re.MULTILINE,
        )
        # `if` / `case` / `$AUTO_APPROVE` などのガード語が同一スクリプト内にある場合は
        # 上記マッチが分岐配下にある可能性がある。安全側で「``apply -auto-approve`` の
        # 行が出現する場合は、その上方に AUTO_APPROVE 系変数のガードがあること」を要求する。
        if unconditional is not None:
            head = text[: unconditional.start()]
            assert re.search(r"AUTO_APPROVE", head), (
                "swap_video.sh が `terraform apply -auto-approve` を無条件で実行している"
                "（AUTO_APPROVE 変数等のガードが上方に無い。誤 apply リスク）"
            )

    def test_script_supports_auto_approve_flag(self):
        """Given スクリプト本文
        When 全文を読む
        Then ``-auto-approve`` を terraform に渡す経路と ``--auto-approve`` 受け取りが対になっている。

        ユーザーが ``--auto-approve`` を渡した時に Terraform 側へ ``-auto-approve``
        が伝播する経路があること。フラグだけ受け取って何もしない実装になっていないか担保する。
        """
        text = read_file(_SWAP_VIDEO_SCRIPT)
        # ユーザー向けフラグ `--auto-approve` の取り回し
        assert re.search(r"--auto-approve\b", text), "swap_video.sh が `--auto-approve` 引数を受け取っていない"
        # terraform へ渡す `-auto-approve`（シングルダッシュ）
        assert re.search(r"-auto-approve\b", text), (
            "swap_video.sh が terraform へ `-auto-approve` を渡していない"
            "（ユーザーフラグだけ受け取って Terraform 側に伝播していない）"
        )


# ============================================================================
# .claude/skills/streaming/SKILL.md — #153 allowed_ssh_cidr の operator 索引
# ============================================================================


class TestStreamingSkillFirewall:
    """``.claude/skills/streaming/SKILL.md`` の #153 ``allowed_ssh_cidr`` 言及。

    SKILL.md は operator 索引。明示しないと §1 初回構築の ``terraform apply`` が
    SSH 到達不可で詰むため、必須項目として CIDR を記載する必要がある。
    本テストは raw text のキーワード包含のみ検証する（章立て自由度を残す）。
    """

    def test_skill_file_exists(self):
        """Given .claude/skills/streaming/
        When SKILL.md を探す
        Then 存在する。
        """
        assert _STREAMING_SKILL.exists(), ".claude/skills/streaming/SKILL.md が存在しない"

    def test_mentions_allowed_ssh_cidr(self):
        """Given SKILL.md
        When 全文を読む
        Then ``allowed_ssh_cidr`` キーワードの言及がある (R8, H12)。

        operator 索引からの到達経路。明示しないと §1 初回構築の terraform apply が
        SSH 到達不可で詰む。
        """
        text = read_file(_STREAMING_SKILL)
        assert "allowed_ssh_cidr" in text, (
            "SKILL.md に allowed_ssh_cidr の言及が無い"
            "（operator が必須項目を発見できず、§1 初回構築で SSH 到達不可になる）"
        )


# ============================================================================
# .claude/skills/streaming/SKILL.md — #154 ssh-agent 切替の operator 索引
# ============================================================================


class TestStreamingSkillSshAgent:
    """``.claude/skills/streaming/SKILL.md`` の #154 ssh-agent 経路の言及。

    SKILL.md は operator 索引。``connection.agent = true`` に切り替わったため、
    operator が ``terraform apply`` 前に ``ssh-add`` で鍵を登録する必要がある。
    本テストは raw text のキーワード包含のみ検証する（章立て自由度を残す）。
    """

    def test_does_not_mention_ssh_priv_key_path(self):
        """Given SKILL.md
        When 全文を読む
        Then ``ssh_priv_key_path`` キーワードがどこにも含まれていない。

        #154 で variables.tf から撤去された変数。SKILL.md に残ると README / SKILL.md の整合が
        崩れ、operator が古い前提に従って詰まる。
        """
        text = read_file(_STREAMING_SKILL)
        assert "ssh_priv_key_path" not in text, (
            "SKILL.md に ssh_priv_key_path の言及が残っている（撤去済み変数。README / SKILL 不整合）"
        )

    def test_mentions_ssh_add_for_agent_setup(self):
        """Given SKILL.md
        When 全文を読む
        Then ``ssh-add`` コマンドの言及がある（ssh-agent への鍵登録手順）。

        #154 で ``connection.agent = true`` に切り替えたため、operator が ``terraform apply`` 前に
        ssh-agent へ鍵を登録する必要がある。SKILL.md 経由のオペレーターも起動条件を把握できる
        必要があるため、README と同じく ``ssh-add`` の緩い包含検査で担保する。
        """
        text = read_file(_STREAMING_SKILL)
        assert "ssh-add" in text, (
            "SKILL.md に ssh-add の言及が無い"
            "（operator が ssh-agent 登録手順を SKILL.md から辿れず terraform apply が失敗する）"
        )


# ============================================================================
# scripts/streaming/run-ffmpeg.sh — #160 ffmpeg ラッパー本体
# ============================================================================


class TestRunFfmpegScript:
    """``scripts/streaming/run-ffmpeg.sh`` の静的検査（#160）。

    systemd unit の ``ExecStart`` から呼ばれる ffmpeg 起動ラッパー。systemd が
    ``EnvironmentFile=/etc/youtube-stream.env`` 経由で注入する ``$VIDEO`` /
    ``$RTMP_URL`` をそのまま受け取り、``exec /usr/bin/ffmpeg ...`` でプロセス置換する
    ことで、unit 行に ``$RTMP_URL`` を残さない経路を提供する。``DynamicUser=yes``
    + 0600 root:root の env file 構成のため、ラッパー側で ``source`` してはならない。

    本テストは terraform バイナリ非依存方針に従い、ファイルテキスト・主要キーワードの
    包含のみ正規表現で検証する（既存 ``TestSwapVideoScript`` と同じスタイル）。
    """

    def test_script_exists(self):
        """Given リポジトリ
        When ``scripts/streaming/run-ffmpeg.sh`` を探す
        Then 当該ファイルが存在する。

        ExecStart の差し替え先が物理的に欠落すると ``systemctl start`` が
        ``status=203/EXEC`` で fail する。最低限の存在保証。
        """
        assert _RUN_FFMPEG_SCRIPT.exists(), (
            f"{_RUN_FFMPEG_SCRIPT.relative_to(_REPO_ROOT)} が存在しない（#160 ラッパーが未実装）"
        )

    def test_script_has_bash_shebang(self):
        """Given ラッパー本文
        When 1 行目を読む
        Then ``#!/usr/bin/env bash`` で始まる。

        既存 ``healthcheck.sh`` / ``notify.sh`` と同じ shebang で揃える。``set -eu`` の
        厳密モードと、``"$VIDEO"`` / ``"$RTMP_URL"`` のダブルクォート展開挙動を
        POSIX sh と互換取りにせず bash 固定で扱う。
        """
        text = read_file(_RUN_FFMPEG_SCRIPT)
        first_line = text.splitlines()[0] if text else ""
        assert first_line == "#!/usr/bin/env bash", (
            f"run-ffmpeg.sh の shebang が '#!/usr/bin/env bash' でない: {first_line!r}"
        )

    def test_script_uses_set_strict(self):
        """Given ラッパー本文
        When 全文を読む
        Then ``set -eu``（または ``set -euo pipefail``）が記載されている。

        ``set -u`` が必須: env file に VIDEO / RTMP_URL のどちらかが欠けたまま
        ffmpeg を呼ぶと argv が壊れて起動に失敗するため、未定義変数で Fail Fast する。
        """
        text = read_file(_RUN_FFMPEG_SCRIPT)
        assert re.search(r"^set\s+-eu(o\s+pipefail)?\b", text, flags=re.MULTILINE), (
            "run-ffmpeg.sh に `set -eu`（または `set -euo pipefail`）が無い（env 欠落でも気付けず argv が壊れる）"
        )

    def test_script_does_not_source_env_file(self):
        """Given ラッパー本文
        When 全文を読む
        Then ``source /etc/youtube-stream.env``（または ``. /etc/youtube-stream.env``）が記載されていない。

        ``/etc/youtube-stream.env`` は ``chmod 600 root:root``（main.tf）で配置され、
        unit 側の ``DynamicUser=yes``（#159）配下のラッパーは読み取れない。env は
        systemd 自身が ``EnvironmentFile=`` 経由（PID 1 / root）で注入するため、
        ラッパー側で ``source`` するとパーミッション拒否で ``set -e`` により即 fail する。
        後続 fix で「念のため」復活させるリグレッションを止めるための not-contains 検証。
        """
        text = read_file(_RUN_FFMPEG_SCRIPT)
        match = re.search(
            r"^\s*(?:source|\.)\s+/etc/youtube-stream\.env\b",
            text,
            flags=re.MULTILINE,
        )
        assert match is None, (
            "run-ffmpeg.sh に `source /etc/youtube-stream.env` 行が残っている"
            "（DynamicUser=yes + 0600 root:root の env file は読めず即 fail する。"
            "env は EnvironmentFile= 経由で systemd が注入する）"
        )

    def test_script_execs_ffmpeg(self):
        """Given ラッパー本文
        When 全文を読む
        Then ``exec /usr/bin/ffmpeg ...`` で起動している。

        ``exec`` 必須: 中継 shell が残ると systemd の ``Restart`` /
        ``RuntimeMaxSec`` シグナルが ffmpeg に直接届かなくなる。
        plan §「実装ガイドライン」最重要項目。
        """
        text = read_file(_RUN_FFMPEG_SCRIPT)
        assert re.search(r"^\s*exec\s+/usr/bin/ffmpeg\b", text, flags=re.MULTILINE), (
            "run-ffmpeg.sh が `exec /usr/bin/ffmpeg ...` でプロセス置換していない"
            "（中継 shell が残ると systemd シグナルが ffmpeg に直接届かない）"
        )

    def test_script_ffmpeg_argv_matches_pre_wrapper_spec(self):
        """Given ラッパー本文
        When ``exec /usr/bin/ffmpeg ...`` 行を読む
        Then ``-re -stream_loop -1 -i "$VIDEO" -c:v copy -c:a copy -f flv "$RTMP_URL"``
        の引数列が宣言されている (#185 互換)。

        #185 で systemd unit 側に ``-c:v copy -c:a copy``（再エンコードなし、
        動画音声をそのまま送出）を明示分離した意図を後退させない。``-c copy``
        ショートハンドや anullsrc 復活を禁止する。``$VIDEO`` / ``$RTMP_URL`` は
        ``set -u`` 配下の word-splitting 防止のためダブルクォート必須。
        """
        text = read_file(_RUN_FFMPEG_SCRIPT)
        expected = (
            r"exec\s+/usr/bin/ffmpeg\s+-re\s+-stream_loop\s+-1\s+"
            r'-i\s+"\$VIDEO"\s+'
            r"-c:v\s+copy\s+-c:a\s+copy\s+"
            r'-f\s+flv\s+"\$RTMP_URL"\s*$'
        )
        assert re.search(expected, text, flags=re.MULTILINE), (
            "run-ffmpeg.sh の ffmpeg argv が #185 仕様"
            '（-re -stream_loop -1 -i "$VIDEO" -c:v copy -c:a copy -f flv "$RTMP_URL"）'
            "と一致しない"
        )

    def test_script_does_not_use_c_copy_shorthand(self):
        """Given ラッパー本文
        When 全文を読む
        Then ``-c copy`` ショートハンド（``-c:v copy -c:a copy`` 分離前の形）が含まれていない。

        order.md 例の ``-c copy`` 短縮形は使わない（plan §採用しない選択肢）。
        #185 で動画音声をそのまま送出する明示分離に改訂済みのため、後退禁止。
        """
        text = read_file(_RUN_FFMPEG_SCRIPT)
        # `-c copy`（直後がコロンでない c）にマッチ。`-c:v copy` / `-c:a copy` は許容。
        assert not re.search(r"\s-c\s+copy\b", text), (
            "run-ffmpeg.sh に `-c copy` ショートハンドが含まれている"
            "（#185 で `-c:v copy -c:a copy` 明示分離に改訂済み。後退禁止）"
        )


# ============================================================================
# main.tf — #160 で追加される run-ffmpeg.sh の triggers / provisioner / chmod
# ============================================================================


class TestMainTfRunFfmpegProvisioner:
    """``main.tf`` の #160 ``run-ffmpeg.sh`` 配信配線を検証する。

    検証観点:
      - ``null_resource.deploy.triggers.run_ffmpeg_sh`` が
        ``filemd5("${local.scripts_dir}/run-ffmpeg.sh")`` で参照されている
        （#157 DRY パターン準拠）
      - ``provisioner "file"`` で ``${local.scripts_dir}/run-ffmpeg.sh`` を
        ``/opt/youtube-stream/bin/run-ffmpeg.sh`` にアップロードする
      - ``provisioner "remote-exec"`` の inline に ``chmod 755 .../run-ffmpeg.sh``
        が含まれ、``systemctl enable --now`` より前の順序で並ぶ
    """

    def test_triggers_run_ffmpeg_sh_uses_local_scripts_dir(self):
        """Given main.tf
        When ``null_resource.deploy.triggers.run_ffmpeg_sh`` を読む
        Then ``filemd5("${local.scripts_dir}/run-ffmpeg.sh")`` で参照している。

        #157 の DRY 不変条件（``../../../scripts/streaming`` リテラル 1 回出現）を
        破壊しないよう、必ず ``${local.scripts_dir}`` 経由で書く。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None
        triggers = extract_block(block, r"triggers")
        assert triggers is not None

        match = re.search(
            r'run_ffmpeg_sh\s*=\s*filemd5\(\s*"\$\{local\.scripts_dir\}/run-ffmpeg\.sh"\s*\)',
            triggers,
        )

        assert match is not None, (
            'triggers.run_ffmpeg_sh が filemd5("${local.scripts_dir}/run-ffmpeg.sh") でない'
            "（ラッパー更新が再デプロイトリガーにならない）"
        )

    def test_provisioner_file_run_ffmpeg_sh_sources_local_scripts_dir(self):
        """Given main.tf
        When run-ffmpeg.sh を /opt/youtube-stream/bin/run-ffmpeg.sh に配置する
        provisioner を読む
        Then ``source = "${local.scripts_dir}/run-ffmpeg.sh"`` で参照している。

        既存 ``healthcheck.sh`` / ``notify.sh`` と同形の配線パターン。
        source/destination のペアリングを順序非依存で検証する。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None

        match = re.search(
            r'provisioner\s+"file"\s*\{[^}]*?'
            r'source\s*=\s*"\$\{local\.scripts_dir\}/run-ffmpeg\.sh"[^}]*?'
            r'destination\s*=\s*"/opt/youtube-stream/bin/run-ffmpeg\.sh"[^}]*?\}',
            block,
            flags=re.DOTALL,
        )
        match_alt = re.search(
            r'provisioner\s+"file"\s*\{[^}]*?'
            r'destination\s*=\s*"/opt/youtube-stream/bin/run-ffmpeg\.sh"[^}]*?'
            r'source\s*=\s*"\$\{local\.scripts_dir\}/run-ffmpeg\.sh"[^}]*?\}',
            block,
            flags=re.DOTALL,
        )

        assert match or match_alt, (
            'provisioner "file" で source="${local.scripts_dir}/run-ffmpeg.sh" → '
            "/opt/youtube-stream/bin/run-ffmpeg.sh のアップロードが宣言されていない"
        )

    def test_remote_exec_chmod_includes_run_ffmpeg_sh(self):
        """Given main.tf
        When ``provisioner "remote-exec"`` の inline を読む
        Then ``chmod 755 ... /opt/youtube-stream/bin/run-ffmpeg.sh ...`` が含まれている。

        systemd は ``ExecStart`` 行の絶対パスを実行する。実行ビットが無いと
        ``status=203/EXEC`` で起動失敗する。``healthcheck.sh`` / ``notify.sh`` と
        同じ 755 を付与する。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None
        remote_exec = re.search(
            r'provisioner\s+"remote-exec"\s*\{(.*?)\n\s*\}',
            block,
            flags=re.DOTALL,
        )
        assert remote_exec is not None, 'provisioner "remote-exec" ブロックが見つからない'
        inline = remote_exec.group(1)
        assert re.search(
            r"chmod\s+755\b[^\n]*/opt/youtube-stream/bin/run-ffmpeg\.sh\b",
            inline,
        ), (
            "remote-exec の inline に chmod 755 .../run-ffmpeg.sh が無い"
            "（実行ビット不足で systemctl start が status=203/EXEC で fail する）"
        )

    def test_chmod_run_ffmpeg_sh_precedes_systemctl_enable(self):
        """Given main.tf
        When ``provisioner "remote-exec"`` の inline 順序を読む
        Then ``chmod 755 .../run-ffmpeg.sh`` が ``systemctl enable --now`` より前に並ぶ。

        順序逆転すると初回 apply 時に ``systemctl enable --now`` が起動を試みた
        瞬間にラッパーの実行ビットが無く ``status=203/EXEC`` で失敗する。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None
        remote_exec = re.search(
            r'provisioner\s+"remote-exec"\s*\{(.*?)\n\s*\}',
            block,
            flags=re.DOTALL,
        )
        assert remote_exec is not None
        inline = remote_exec.group(1)

        chmod_match = re.search(
            r"chmod\s+755\b[^\n]*run-ffmpeg\.sh\b",
            inline,
        )
        enable_match = re.search(r"systemctl\s+enable\s+--now\s+youtube-stream", inline)

        assert chmod_match is not None, "chmod 755 .../run-ffmpeg.sh が remote-exec inline に無い"
        assert enable_match is not None, "systemctl enable --now youtube-stream が remote-exec inline に無い"
        assert chmod_match.start() < enable_match.start(), (
            "remote-exec inline で chmod 755 .../run-ffmpeg.sh が "
            "systemctl enable --now より後に並んでいる（初回 apply で 203/EXEC fail のリスク）"
        )
