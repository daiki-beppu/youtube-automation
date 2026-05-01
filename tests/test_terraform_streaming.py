"""infra/terraform/streaming の Terraform 構成のスペック準拠テスト。

issue #123 の order.md と plan.md に基づき、以下を検証する:

- ``versions.tf``: ``vultr/vultr`` provider 宣言と provider ブロック
- ``variables.tf``: 5 変数の型/default/sensitive
- ``main.tf``: ``vultr_ssh_key`` + ``vultr_instance`` の構造と紐付け
- ``outputs.tf``: ``instance_ip`` / ``instance_id`` の expose
- ``terraform.tfvars.example``: secret を平文で含まない
- ルート ``.gitignore``: Terraform 系の ignore エントリ

terraform バイナリに依存せず、``.tf`` ファイルのテキストを正規表現で
構造検証する。実 ``terraform validate`` / ``apply`` は手動検証。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------- パス定数 ----------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_STREAMING_DIR = _REPO_ROOT / "infra" / "terraform" / "streaming"

_VERSIONS_TF = _STREAMING_DIR / "versions.tf"
_VARIABLES_TF = _STREAMING_DIR / "variables.tf"
_MAIN_TF = _STREAMING_DIR / "main.tf"
_OUTPUTS_TF = _STREAMING_DIR / "outputs.tf"
_TFVARS_EXAMPLE = _STREAMING_DIR / "terraform.tfvars.example"
_ROOT_GITIGNORE = _REPO_ROOT / ".gitignore"


# ---------- ヘルパー ----------


def _strip_hcl_comments(text: str) -> str:
    """行コメント (``#`` / ``//``) と ``/* ... */`` ブロックコメントを除去する。

    HCL の構文解析はせず、コメント行で false-positive のマッチを起こさないための前処理。
    文字列リテラル内の ``#`` などは想定しない（本テスト対象の HCL は素直な構造のみ）。
    """
    # ブロックコメント (greedy にならないよう非貪欲)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    # 行コメント
    cleaned_lines: list[str] = []
    for line in text.splitlines():
        # `#` が文字列内にあるケースは本テストの対象 HCL では発生しないため単純に切る
        for marker in ("#", "//"):
            idx = line.find(marker)
            if idx >= 0:
                line = line[:idx]
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def _read(path: Path) -> str:
    if not path.exists():
        pytest.fail(f"必須ファイルが存在しない: {path.relative_to(_REPO_ROOT)}")
    return path.read_text(encoding="utf-8")


def _extract_block(text: str, header_pattern: str) -> str | None:
    """``header { ... }`` または ``header = { ... }`` のトップレベルブロックを 1 つ抜き出す。

    ``header_pattern`` は header 行（``{`` 直前まで）にマッチする正規表現。
    ネストした ``{ }`` を 1 段までカウントしてマッチ範囲を確定する。
    HCL の ``required_providers`` 内は ``name = { ... }``（オブジェクトリテラル）
    形式のため、ヘッダーと ``{`` の間に任意で ``=`` を許容する。
    """
    match = re.search(header_pattern + r"\s*=?\s*\{", text)
    if not match:
        return None
    start = match.end()  # `{` の直後
    depth = 1
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i]
    return None


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
        text = _strip_hcl_comments(_read(_VERSIONS_TF))
        terraform_block = _extract_block(text, r"terraform")
        assert terraform_block is not None, "terraform { ... } ブロックが存在しない"
        assert re.search(r'required_version\s*=\s*"[^"]*>=\s*1\.5', terraform_block), (
            "required_version が >= 1.5 を含んでいない"
        )

    def test_required_providers_declares_vultr_source(self):
        """Given versions.tf
        When required_providers ブロックを読む
        Then vultr.source = "vultr/vultr" が宣言されている。
        """
        text = _strip_hcl_comments(_read(_VERSIONS_TF))
        terraform_block = _extract_block(text, r"terraform")
        assert terraform_block is not None
        rp_block = _extract_block(terraform_block, r"required_providers")
        assert rp_block is not None, "required_providers ブロックが存在しない"
        vultr_block = _extract_block(rp_block, r"vultr")
        assert vultr_block is not None, "required_providers.vultr が宣言されていない"
        assert re.search(r'source\s*=\s*"vultr/vultr"', vultr_block), (
            'required_providers.vultr.source が "vultr/vultr" でない'
        )

    def test_required_providers_vultr_version_at_least_2(self):
        """Given versions.tf
        When required_providers.vultr.version を読む
        Then ">= 2" を含む制約が宣言されている（order.md「>= 2.x」）。
        """
        text = _strip_hcl_comments(_read(_VERSIONS_TF))
        terraform_block = _extract_block(text, r"terraform")
        assert terraform_block is not None
        rp_block = _extract_block(terraform_block, r"required_providers")
        assert rp_block is not None
        vultr_block = _extract_block(rp_block, r"vultr")
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
        text = _strip_hcl_comments(_read(_VERSIONS_TF))
        provider_block = _extract_block(text, r'provider\s+"vultr"')
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
        text = _strip_hcl_comments(_read(_VARIABLES_TF))
        block = _extract_block(text, r'variable\s+"vultr_api_key"')
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
        text = _strip_hcl_comments(_read(_VARIABLES_TF))
        block = _extract_block(text, r'variable\s+"ssh_pub_key_path"')
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
        text = _strip_hcl_comments(_read(_VARIABLES_TF))
        block = _extract_block(text, r'variable\s+"region"')
        assert block is not None, 'variable "region" が存在しない'
        assert re.search(r"type\s*=\s*string", block), "region.type が string でない"
        assert re.search(r'default\s*=\s*"nrt"', block), 'region.default が "nrt" でない'
        assert re.search(r"description\s*=", block), "region.description が無い"

    def test_plan_default_is_vc2_1c_2gb(self):
        """Given variables.tf
        When plan 変数定義を読む
        Then default が "vc2-1c-2gb"（$10/月、2GB RAM）。
        """
        text = _strip_hcl_comments(_read(_VARIABLES_TF))
        block = _extract_block(text, r'variable\s+"plan"')
        assert block is not None, 'variable "plan" が存在しない'
        assert re.search(r"type\s*=\s*string", block), "plan.type が string でない"
        assert re.search(r'default\s*=\s*"vc2-1c-2gb"', block), 'plan.default が "vc2-1c-2gb" でない'
        assert re.search(r"description\s*=", block), "plan.description が無い"

    def test_os_id_is_number_type_with_ubuntu_24_04_default(self):
        """Given variables.tf
        When os_id 変数定義を読む
        Then type が number でかつ default が 2284（Ubuntu 24.04 LTS x64 の Vultr OS ID）。
        """
        text = _strip_hcl_comments(_read(_VARIABLES_TF))
        block = _extract_block(text, r'variable\s+"os_id"')
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
        text = _strip_hcl_comments(_read(_MAIN_TF))
        block = _extract_block(text, r'resource\s+"vultr_ssh_key"\s+"this"')
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
        text = _strip_hcl_comments(_read(_MAIN_TF))
        block = _extract_block(text, r'resource\s+"vultr_instance"\s+"this"')
        assert block is not None, 'resource "vultr_instance" "this" が存在しない'

    def test_vultr_instance_references_variables(self):
        """Given main.tf
        When vultr_instance.this の region/plan/os_id を読む
        Then すべて var.* で結線されている（ハードコード禁止）。
        """
        text = _strip_hcl_comments(_read(_MAIN_TF))
        block = _extract_block(text, r'resource\s+"vultr_instance"\s+"this"')
        assert block is not None
        assert re.search(r"region\s*=\s*var\.region", block), "instance.region が var.region でない"
        assert re.search(r"plan\s*=\s*var\.plan", block), "instance.plan が var.plan でない"
        assert re.search(r"os_id\s*=\s*var\.os_id", block), "instance.os_id が var.os_id でない"

    def test_vultr_instance_ssh_key_ids_links_ssh_key_resource(self):
        """Given main.tf
        When vultr_instance.this.ssh_key_ids を読む
        Then [vultr_ssh_key.this.id] で SSH 鍵リソースに結線されている。
        """
        text = _strip_hcl_comments(_read(_MAIN_TF))
        block = _extract_block(text, r'resource\s+"vultr_instance"\s+"this"')
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
        text = _strip_hcl_comments(_read(_MAIN_TF))
        block = _extract_block(text, r'resource\s+"vultr_instance"\s+"this"')
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
        text = _strip_hcl_comments(_read(_MAIN_TF))
        block = _extract_block(text, r'resource\s+"vultr_instance"\s+"this"')
        assert block is not None
        assert re.search(r'label\s*=\s*"youtube-stream"', block), 'label = "youtube-stream" が設定されていない'

    def test_vultr_instance_hostname_is_youtube_stream(self):
        """Given main.tf
        When vultr_instance.this.hostname を読む
        Then "youtube-stream" が設定されている（運用識別用、label/tags と網羅対称）。

        plan §実装アプローチ 4 / coder-decisions §3 で確定された運用識別子であり、
        誤って削除・改変された場合のリグレッションを検出する。
        """
        text = _strip_hcl_comments(_read(_MAIN_TF))
        block = _extract_block(text, r'resource\s+"vultr_instance"\s+"this"')
        assert block is not None
        assert re.search(r'hostname\s*=\s*"youtube-stream"', block), 'hostname = "youtube-stream" が設定されていない'

    def test_vultr_instance_user_data_uses_templatefile_for_cloud_init(self):
        """Given main.tf
        When vultr_instance.this.user_data を読む
        Then ``templatefile("${path.module}/cloud-init.yaml", {...})`` 経由で
             cloud-init.yaml が渡されている（issue #124 要件）。

        ``${path.module}`` を必ず付け、``-chdir`` 実行で相対パスが崩れないようにする。
        """
        text = _strip_hcl_comments(_read(_MAIN_TF))
        block = _extract_block(text, r'resource\s+"vultr_instance"\s+"this"')
        assert block is not None, 'resource "vultr_instance" "this" が存在しない'
        assert re.search(
            r"user_data\s*=\s*templatefile\(\s*\"\$\{path\.module\}/cloud-init\.yaml\"",
            block,
        ), 'user_data が templatefile("${path.module}/cloud-init.yaml", ...) で結線されていない'

    def test_vultr_instance_user_data_passes_unit_via_file_function(self):
        """Given main.tf
        When vultr_instance.this.user_data の templatefile 第 2 引数を読む
        Then ``youtube_stream_service = file("${path.module}/templates/youtube-stream.service.tftpl")``
             で systemd unit テンプレを読み込んで cloud-init に渡している。

        unit 側に Terraform 補間 (``${...}``) は無いため ``templatefile`` ではなく
        ``file`` を使う（補間を持たない静的ファイルは ``file`` で読む原則）。
        """
        text = _strip_hcl_comments(_read(_MAIN_TF))
        block = _extract_block(text, r'resource\s+"vultr_instance"\s+"this"')
        assert block is not None
        assert re.search(
            r"youtube_stream_service\s*=\s*file\(\s*\"\$\{path\.module\}/templates/youtube-stream\.service\.tftpl\"\s*\)",
            block,
        ), 'youtube_stream_service が file("${path.module}/templates/youtube-stream.service.tftpl") で渡されていない'

    def test_vultr_instance_user_data_does_not_inline_cloud_init_yaml(self):
        """Given main.tf
        When vultr_instance.this.user_data を読む
        Then ``<<EOT ... EOT`` / ``<<-EOT ... EOT`` のヒアドキュメントで cloud-init を
             直書きしていない（order.md「templatefile 経由」要件違反の検出）。
        """
        text = _strip_hcl_comments(_read(_MAIN_TF))
        block = _extract_block(text, r'resource\s+"vultr_instance"\s+"this"')
        assert block is not None
        assert not re.search(
            r"user_data\s*=\s*<<-?[A-Z]+",
            block,
        ), "user_data がヒアドキュメントで直書きされている（templatefile 経由でなければならない）"

    def test_vultr_instance_user_data_does_not_contain_secret_strings(self):
        """Given main.tf
        When vultr_instance.this.user_data 周辺を読む
        Then secret（rtmp URL / stream key）が直書きされていない
             （plan 差分でも露出しない要件）。
        """
        text = _strip_hcl_comments(_read(_MAIN_TF))
        block = _extract_block(text, r'resource\s+"vultr_instance"\s+"this"')
        assert block is not None
        assert "rtmp://" not in block, "main.tf の vultr_instance に rtmp:// URL が含まれている"
        assert "rtmps://" not in block, "main.tf の vultr_instance に rtmps:// URL が含まれている"
        assert "rtmp.youtube.com" not in block, "main.tf の vultr_instance に rtmp.youtube.com が含まれている"


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
        text = _strip_hcl_comments(_read(_OUTPUTS_TF))
        block = _extract_block(text, r'output\s+"instance_ip"')
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
        text = _strip_hcl_comments(_read(_OUTPUTS_TF))
        block = _extract_block(text, r'output\s+"instance_id"')
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
        text = _strip_hcl_comments(_read(_TFVARS_EXAMPLE))
        # コメント除去後に `vultr_api_key = ...` が残っていないこと
        assert not re.search(r"^\s*vultr_api_key\s*=", text, flags=re.MULTILINE), (
            "vultr_api_key の代入がアクティブ行に存在する（secret 漏洩リスク）"
        )

    def test_mentions_tf_var_vultr_api_key_in_comments(self):
        """Given terraform.tfvars.example
        When ファイル内容（コメント込み）を読む
        Then TF_VAR_vultr_api_key の使い方がコメントに記載されている。
        """
        raw = _read(_TFVARS_EXAMPLE)
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
        text = _read(_ROOT_GITIGNORE)
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
