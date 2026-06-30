"""infra/terraform/streaming の Terraform メタ層（バージョン / 出力 / tfvars / gitignore） の検証テスト。

- ``versions.tf``: terraform / required_providers / provider 宣言
- ``outputs.tf``: 公開する output 値
- ``terraform.tfvars.example``: secret を平文で含まない例
- ルート ``.gitignore``: Terraform 系の ignore エントリ
- ``templates/logrotate.conf.tftpl`` / ``templates/cron.d.tftpl``: install_root 参照
"""

from __future__ import annotations

import re

import pytest

from tests.helpers.hcl import extract_block, read_file, strip_hcl_comments
from tests.streaming._helpers import (
    _CRON_D_TFTPL,
    _INSTALL_ROOT_TFTPL,
    _LOGROTATE_TFTPL,
    _OUTPUTS_TF,
    _ROOT_GITIGNORE,
    _TFSTATE_BACKEND_PREFIX,
    _TFVARS_EXAMPLE,
    _VERSIONS_TF,
)

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

    def test_backend_uses_gcs_remote_state(self):
        """Given versions.tf
        When terraform backend を読む
        Then GCS backend は streaming prefix を宣言している。
        """
        text = strip_hcl_comments(read_file(_VERSIONS_TF))
        terraform_block = extract_block(text, r"terraform")
        assert terraform_block is not None, "terraform { ... } ブロックが存在しない"
        backend_block = extract_block(terraform_block, r'backend\s+"gcs"')
        assert backend_block is not None, 'backend "gcs" ブロックが存在しない'
        assert re.search(rf'prefix\s*=\s*"{re.escape(_TFSTATE_BACKEND_PREFIX)}"', backend_block), (
            "GCS backend prefix が streaming でない"
        )
        assert extract_block(terraform_block, r'backend\s+"s3"') is None, 'backend "s3" が残っている'

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

    def test_required_providers_declares_tls_source(self):
        """Given versions.tf
        When required_providers ブロックを読む
        Then tls.source = "hashicorp/tls" が宣言されている。
        """
        text = strip_hcl_comments(read_file(_VERSIONS_TF))
        terraform_block = extract_block(text, r"terraform")
        assert terraform_block is not None
        rp_block = extract_block(terraform_block, r"required_providers")
        assert rp_block is not None, "required_providers ブロックが存在しない"
        tls_block = extract_block(rp_block, r"tls")
        assert tls_block is not None, "required_providers.tls が宣言されていない"
        assert re.search(r'source\s*=\s*"hashicorp/tls"', tls_block), (
            'required_providers.tls.source が "hashicorp/tls" でない'
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

    def test_required_providers_tls_version_at_least_4(self):
        """Given versions.tf
        When required_providers.tls.version を読む
        Then ">= 4" を含む制約が宣言されている。
        """
        text = strip_hcl_comments(read_file(_VERSIONS_TF))
        terraform_block = extract_block(text, r"terraform")
        assert terraform_block is not None
        rp_block = extract_block(terraform_block, r"required_providers")
        assert rp_block is not None
        tls_block = extract_block(rp_block, r"tls")
        assert tls_block is not None
        assert re.search(r'version\s*=\s*"[^"]*>=\s*4', tls_block), (
            "required_providers.tls.version が >= 4 を満たしていない"
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


class TestVersionsTfExternalProvider:
    """``versions.tf`` の ``required_providers.external`` 宣言（#1299）。"""

    def test_required_providers_declares_external_source(self):
        """Given versions.tf
        When required_providers.external を読む
        Then source = "hashicorp/external" が宣言されている。
        """
        text = strip_hcl_comments(read_file(_VERSIONS_TF))
        terraform_block = extract_block(text, r"terraform")
        assert terraform_block is not None
        rp_block = extract_block(terraform_block, r"required_providers")
        assert rp_block is not None, "required_providers ブロックが存在しない"
        external_block = extract_block(rp_block, r"external")
        assert external_block is not None, "required_providers.external が宣言されていない"
        assert re.search(r'source\s*=\s*"hashicorp/external"', external_block), (
            'required_providers.external.source が "hashicorp/external" でない'
        )

    def test_required_providers_external_version_at_least_2_3(self):
        """Given versions.tf
        When required_providers.external.version を読む
        Then ">= 2.3" を含む制約が宣言されている。
        """
        text = strip_hcl_comments(read_file(_VERSIONS_TF))
        terraform_block = extract_block(text, r"terraform")
        assert terraform_block is not None
        rp_block = extract_block(terraform_block, r"required_providers")
        assert rp_block is not None
        external_block = extract_block(rp_block, r"external")
        assert external_block is not None
        assert re.search(r'version\s*=\s*"[^"]*>=\s*2\.3', external_block), (
            "required_providers.external.version が >= 2.3 を満たしていない"
        )


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
# terraform.tfvars.example — #1219 で stream_hours / break_hours のサンプル追記
# ============================================================================


class TestTfvarsExampleStreamCycle:
    """``terraform.tfvars.example`` の #1219 配信サイクル変数の discoverability。"""

    def test_stream_cycle_variables_are_documented_as_optional_examples(self):
        """Given terraform.tfvars.example
        When ファイル内容（raw text）を読む
        Then stream_hours / break_hours のコメント付きサンプルが存在する。

        デフォルト値 0 は variables.tf にあるため、サンプルでは任意項目として示す。
        """
        raw = read_file(_TFVARS_EXAMPLE)
        assert "# stream_hours = 0" in raw, "stream_hours の任意サンプルが無い"
        assert "# break_hours  = 0" in raw, "break_hours の任意サンプルが無い"
        assert "24/7" in raw, "0 / 0 が 24/7 連続配信である説明が無い"


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
# templates/logrotate.conf.tftpl / templates/cron.d.tftpl — install_root 展開
# ============================================================================


class TestInstallRootTemplates:
    """``install_root`` を受け取る運用アセットテンプレート。"""

    def test_logrotate_template_uses_install_root_logs_path(self):
        """Given logrotate.conf.tftpl
        When 全文を読む
        Then ``${install_root}/logs/*.log`` を対象にしている。
        """
        text = read_file(_LOGROTATE_TFTPL)
        assert re.search(
            rf"^{_INSTALL_ROOT_TFTPL}/logs/\*\.log\s+\{{",
            text,
            flags=re.MULTILINE,
        ), "logrotate.conf.tftpl が ${install_root}/logs/*.log を対象にしていない"

    @pytest.mark.parametrize(
        "directive",
        ["daily", "rotate 7", "compress", "copytruncate", "missingok", "notifempty"],
    )
    def test_logrotate_template_contains_required_directive(self, directive):
        """Given logrotate.conf.tftpl
        When 全文を読む
        Then ffmpeg ログ運用に必要な logrotate directive が残っている。
        """
        text = read_file(_LOGROTATE_TFTPL)
        pattern = rf"(?m)^\s*{re.escape(directive)}\s*$"
        assert re.search(pattern, text), f"logrotate.conf.tftpl に {directive} が無い"

    def test_cron_template_uses_install_root_healthcheck_path(self):
        """Given cron.d.tftpl
        When cron 行を読む
        Then ``${install_root}/bin/healthcheck.sh`` を呼ぶ。
        """
        text = read_file(_CRON_D_TFTPL)
        assert re.search(
            rf"^\s*\*/5\s+\*\s+\*\s+\*\s+\*\s+root\s+{_INSTALL_ROOT_TFTPL}/bin/healthcheck\.sh\b",
            text,
            flags=re.MULTILINE,
        ), "cron.d.tftpl が ${install_root}/bin/healthcheck.sh を呼んでいない"
