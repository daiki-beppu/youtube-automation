"""infra/terraform/streaming の ``variables.tf`` 群の検証テスト。

- 5 変数の型 / default / sensitive
- null_resource (provisioner) 用変数
- vultr_firewall_group / vultr_firewall_rule 用変数
"""

from __future__ import annotations

import re

from tests.helpers.hcl import extract_block, read_file, strip_hcl_comments
from tests.streaming._helpers import (
    _DEFAULT_INSTALL_ROOT,
    _VARIABLES_TF,
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

    def test_install_root_is_string_with_default_youtube_stream_root(self):
        """Given variables.tf
        When install_root 変数定義を読む
        Then type=string, default は /opt/youtube-stream で宣言されている。

        既存挙動は保ったまま、配置 root だけを上書き可能にする。
        """
        text = strip_hcl_comments(read_file(_VARIABLES_TF))
        block = extract_block(text, r'variable\s+"install_root"')
        assert block is not None, 'variable "install_root" が存在しない'
        assert re.search(r"type\s*=\s*string", block), "install_root.type が string でない"
        assert re.search(r"description\s*=", block), "install_root.description が無い"
        assert re.search(
            rf'default\s*=\s*"{re.escape(_DEFAULT_INSTALL_ROOT)}"',
            block,
        ), 'install_root.default が "/opt/youtube-stream" でない'

    def test_stream_hours_is_number_with_zero_default(self):
        """Given variables.tf
        When stream_hours 変数定義を読む
        Then type=number, default=0, description あり、非負 validation が宣言されている。

        0 は RuntimeMaxSec を省略する 24/7 連続配信モード。
        負数は > 0 分岐の else 側に入り 24/7 モードに黙って吸収されるため、非負を検証する。
        """
        text = strip_hcl_comments(read_file(_VARIABLES_TF))
        block = extract_block(text, r'variable\s+"stream_hours"')
        assert block is not None, 'variable "stream_hours" が存在しない'
        assert re.search(r"type\s*=\s*number", block), "stream_hours.type が number でない"
        assert re.search(r"default\s*=\s*0\b", block), "stream_hours.default が 0 でない"
        assert re.search(r"description\s*=", block), "stream_hours.description が無い"
        validation = extract_block(block, r"validation")
        assert validation is not None, "stream_hours.validation ブロックが存在しない（負数が 24/7 モードに吸収される）"
        assert re.search(
            r"condition\s*=\s*var\.stream_hours\s*>=\s*0",
            validation,
        ), "stream_hours.validation.condition が var.stream_hours >= 0 でない"
        assert re.search(r"error_message\s*=\s*\"", validation), "stream_hours.validation.error_message が宣言されていない"

    def test_break_hours_is_number_with_zero_default(self):
        """Given variables.tf
        When break_hours 変数定義を読む
        Then type=number, default=0, description あり、非負 validation が宣言されている。

        0 は休止なしを表し、systemd unit では RestartSec=10s を使う。
        負数は > 0 分岐の else 側に入り休止なしモードに黙って吸収されるため、非負を検証する。
        """
        text = strip_hcl_comments(read_file(_VARIABLES_TF))
        block = extract_block(text, r'variable\s+"break_hours"')
        assert block is not None, 'variable "break_hours" が存在しない'
        assert re.search(r"type\s*=\s*number", block), "break_hours.type が number でない"
        assert re.search(r"default\s*=\s*0\b", block), "break_hours.default が 0 でない"
        assert re.search(r"description\s*=", block), "break_hours.description が無い"
        validation = extract_block(block, r"validation")
        assert validation is not None, "break_hours.validation ブロックが存在しない（負数が休止なしモードに吸収される）"
        assert re.search(
            r"condition\s*=\s*var\.break_hours\s*>=\s*0",
            validation,
        ), "break_hours.validation.condition が var.break_hours >= 0 でない"
        assert re.search(r"error_message\s*=\s*\"", validation), "break_hours.validation.error_message が宣言されていない"

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
