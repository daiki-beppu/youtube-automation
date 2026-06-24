"""infra/terraform/streaming の ``main.tf`` 群の検証テスト。

- ``vultr_ssh_key`` + ``vultr_instance`` の構造と紐付け
- ``user_data`` の templatefile 連鎖（#124）
- null_resource (provisioner) による run-ffmpeg.sh 配置（#214）
- locals.scripts_dir 参照
- vultr_firewall_group / vultr_firewall_rule（#153）
"""

from __future__ import annotations

import re

from tests.helpers.hcl import extract_block, read_file, strip_hcl_comments
from tests.streaming._helpers import (
    _INSTALL_ROOT_VAR,
    _MAIN_TF,
)

# ============================================================================
# main.tf
# ============================================================================


class TestMainTf:
    """``main.tf`` の vultr_ssh_key + vultr_instance 定義。"""

    def test_tls_private_key_resource_uses_ed25519(self):
        """Given main.tf
        When tls_private_key.ssh_host を読む
        Then algorithm が ED25519 に固定されている。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"tls_private_key"\s+"ssh_host"')
        assert block is not None, 'resource "tls_private_key" "ssh_host" が存在しない'
        assert re.search(r"algorithm\s*=\s*local\.ssh_host_key_algorithm", block), (
            "tls_private_key.ssh_host.algorithm が local.ssh_host_key_algorithm を参照していない"
        )
        assert re.search(r'ssh_host_key_algorithm\s*=\s*"ED25519"', text), (
            'locals.ssh_host_key_algorithm が "ED25519" でない'
        )

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

    def test_vultr_instance_user_data_passes_host_key_material(self):
        """Given main.tf
        When vultr_instance.this.user_data を読む
        Then cloud-init template に host 鍵の private/public を明示的に渡している。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"vultr_instance"\s+"this"')
        assert block is not None
        assert re.search(r'user_data\s*=\s*templatefile\(\s*"\$\{path\.module\}/cloud-init\.yaml"\s*,\s*\{', block), (
            'user_data が templatefile("${path.module}/cloud-init.yaml", { ... }) でない'
        )
        assert re.search(r"ssh_host_private_key\s*=\s*tls_private_key\.ssh_host\.private_key_openssh", block), (
            "cloud-init に ssh_host_private_key が渡されていない"
        )
        assert re.search(r"ssh_host_public_key\s*=\s*local\.ssh_host_public_key", block), (
            "cloud-init に ssh_host_public_key が渡されていない"
        )

    def test_null_resource_connection_enables_host_key_verification(self):
        """Given main.tf
        When null_resource.deploy.connection を読む
        Then host_key = local.ssh_host_public_key で検証を有効化している。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        deploy_block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert deploy_block is not None, 'resource "null_resource" "deploy" が存在しない'
        connection_block = extract_block(deploy_block, r"connection")
        assert connection_block is not None, "null_resource.deploy.connection が存在しない"
        assert re.search(r"agent\s*=\s*true", connection_block), "connection.agent = true が無い"
        assert re.search(r"host_key\s*=\s*local\.ssh_host_public_key", connection_block), (
            "connection.host_key が local.ssh_host_public_key を参照していない"
        )

    def test_null_resource_triggers_include_host_key_hash(self):
        """Given main.tf
        When null_resource.deploy.triggers を読む
        Then ssh_host_key トリガーで host 鍵変更時に再実行される。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        deploy_block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert deploy_block is not None
        triggers_block = extract_block(deploy_block, r"triggers")
        assert triggers_block is not None, "null_resource.deploy.triggers が存在しない"
        assert re.search(r"ssh_host_key\s*=\s*local\.ssh_host_public_key_sha", triggers_block), (
            "triggers.ssh_host_key が local.ssh_host_public_key_sha を参照していない"
        )

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

    def test_user_data_template_passes_required_variables(self):
        """Given main.tf
        When vultr_instance.this.user_data の右辺を読む
        Then ``systemd_unit = ...`` も内側 ``templatefile(...service.tftpl...)`` の
             呼び出しも残らず、cloud-init の配置 root (``install_root``) と
             host 鍵配布用の ``ssh_host_*`` 変数だけが渡されている (#212/#195)。

        unit 配置は ``null_resource.deploy`` の ``provisioner "file"`` に統一されたため、
        user_data には cloud-init 用の配置 root と host 鍵配布用変数のみを渡す。
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
        assert re.search(
            r"install_root\s*=\s*var\.install_root",
            block,
        ), "cloud-init templatefile に install_root = var.install_root が渡されていない"
        assert re.search(r"\bssh_host_private_key\s*=", block), (
            "user_data の variables map に ssh_host_private_key が無い（host 鍵配布経路が欠落）"
        )
        assert re.search(r"\bssh_host_public_key\s*=", block), (
            "user_data の variables map に ssh_host_public_key が無い（host 鍵配布経路が欠落）"
        )

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

    def test_triggers_block_has_required_keys(self):
        """Given main.tf
        When null_resource.deploy.triggers を読む
        Then deploy 再実行に必要なキーが宣言されている。

        - instance_id = vultr_instance.this.id（VPS 再作成時の再 deploy）
        - video_hash = filemd5(var.video_path)（動画差分での再 deploy）
        - stream_hours / break_hours（配信サイクル差分での再 deploy）
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
        assert re.search(r"stream_hours\s*=\s*tostring\(\s*var\.stream_hours\s*\)", triggers), (
            "triggers.stream_hours が tostring(var.stream_hours) でない"
        )
        assert re.search(r"break_hours\s*=\s*tostring\(\s*var\.break_hours\s*\)", triggers), (
            "triggers.break_hours が tostring(var.break_hours) でない"
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
        Then ``content = templatefile("${path.module}/templates/youtube-stream.service.tftpl",``
             ``{ install_root = var.install_root, stream_hours = var.stream_hours, break_hours = var.break_hours })``
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
            r'"\$\{path\.module\}/templates/youtube-stream\.service\.tftpl"\s*,\s*\{'
            r"[^}]*install_root\s*=\s*var\.install_root"
            r"[^}]*stream_hours\s*=\s*var\.stream_hours"
            r"[^}]*break_hours\s*=\s*var\.break_hours[^}]*\}\s*\)"
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
            'youtube-stream.service.tftpl", { install_root, stream_hours, break_hours }) → '
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
        Then source=var.video_path, destination=${var.install_root}/videos/current.mp4。

        cloud-init で作成済みの ``${install_root}/videos/`` （cloud-init.yaml:14）に固定名で配置。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None
        # 動画アップロード provisioner は source=var.video_path で識別
        # ブロック内に「source = var.video_path」と「destination = "${var.install_root}/.../current.mp4"」が
        # 同じ provisioner "file" 内にあることを検証（順序は問わない）
        match = re.search(
            r'provisioner\s+"file"\s*\{[^}]*?source\s*=\s*var\.video_path[^}]*?'
            rf'destination\s*=\s*"{_INSTALL_ROOT_VAR}/videos/current\.mp4"[^}}]*?\}}',
            block,
            flags=re.DOTALL,
        )
        match_alt = re.search(
            r'provisioner\s+"file"\s*\{[^}]*?'
            rf'destination\s*=\s*"{_INSTALL_ROOT_VAR}/videos/current\.mp4"[^}}]*?'
            r"source\s*=\s*var\.video_path[^}]*?\}",
            block,
            flags=re.DOTALL,
        )
        assert match or match_alt, (
            'provisioner "file" で source=var.video_path → '
            "${var.install_root}/videos/current.mp4 へのアップロードが宣言されていない"
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
        Then ``video = "${var.install_root}/videos/current.mp4"`` と
             ``rtmp_url = "rtmp://a.rtmp.youtube.com/live2/${var.stream_key}"`` が渡されている。

        コメント除去ヘルパーは URL 内の ``//`` を削るため、この検証は raw text で行う。
        """
        text = read_file(_MAIN_TF)  # raw（rtmp:// の // を保持するためコメント除去しない）
        # video 変数（リテラル文字列）
        assert re.search(
            rf'video\s*=\s*"{_INSTALL_ROOT_VAR}/videos/current\.mp4"',
            text,
        ), 'templatefile に video = "${var.install_root}/videos/current.mp4" が渡されていない'
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

        order.md 完了条件「0600 / root 所有」「配信サイクル開始」を満たす。
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

    def test_triggers_logrotate_conf_uses_template_path(self):
        """Given main.tf
        When ``null_resource.deploy.triggers.logrotate_conf`` を読む
        Then ``filemd5("${path.module}/templates/logrotate.conf.tftpl")`` で参照している。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None
        triggers = extract_block(block, r"triggers")
        assert triggers is not None

        match = re.search(
            r'logrotate_conf\s*=\s*filemd5\(\s*"\$\{path\.module\}/templates/logrotate\.conf\.tftpl"\s*\)',
            triggers,
        )

        assert match is not None, (
            'triggers.logrotate_conf が filemd5("${path.module}/templates/logrotate.conf.tftpl") でない'
        )

    def test_triggers_cron_d_uses_template_path(self):
        """Given main.tf
        When ``null_resource.deploy.triggers.cron_d`` を読む
        Then ``filemd5("${path.module}/templates/cron.d.tftpl")`` で参照している。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None
        triggers = extract_block(block, r"triggers")
        assert triggers is not None

        match = re.search(
            r'cron_d\s*=\s*filemd5\(\s*"\$\{path\.module\}/templates/cron\.d\.tftpl"\s*\)',
            triggers,
        )

        assert match is not None, 'triggers.cron_d が filemd5("${path.module}/templates/cron.d.tftpl") でない'

    def test_provisioner_file_healthcheck_sh_sources_local_scripts_dir(self):
        """Given main.tf
        When healthcheck.sh を ${var.install_root}/bin/healthcheck.sh に配置する provisioner を読む
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
            rf'destination\s*=\s*"{_INSTALL_ROOT_VAR}/bin/healthcheck\.sh"[^}}]*?\}}',
            block,
            flags=re.DOTALL,
        )
        match_alt = re.search(
            r'provisioner\s+"file"\s*\{[^}]*?'
            rf'destination\s*=\s*"{_INSTALL_ROOT_VAR}/bin/healthcheck\.sh"[^}}]*?'
            r'source\s*=\s*"\$\{local\.scripts_dir\}/healthcheck\.sh"[^}]*?\}',
            block,
            flags=re.DOTALL,
        )

        assert match or match_alt, (
            'provisioner "file" で source="${local.scripts_dir}/healthcheck.sh" → '
            "${var.install_root}/bin/healthcheck.sh のアップロードが宣言されていない"
        )

    def test_provisioner_file_notify_sh_sources_local_scripts_dir(self):
        """Given main.tf
        When notify.sh を ${var.install_root}/bin/notify.sh に配置する provisioner を読む
        Then ``source = "${local.scripts_dir}/notify.sh"`` で参照している。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None

        match = re.search(
            r'provisioner\s+"file"\s*\{[^}]*?'
            r'source\s*=\s*"\$\{local\.scripts_dir\}/notify\.sh"[^}]*?'
            rf'destination\s*=\s*"{_INSTALL_ROOT_VAR}/bin/notify\.sh"[^}}]*?\}}',
            block,
            flags=re.DOTALL,
        )
        match_alt = re.search(
            r'provisioner\s+"file"\s*\{[^}]*?'
            rf'destination\s*=\s*"{_INSTALL_ROOT_VAR}/bin/notify\.sh"[^}}]*?'
            r'source\s*=\s*"\$\{local\.scripts_dir\}/notify\.sh"[^}]*?\}',
            block,
            flags=re.DOTALL,
        )

        assert match or match_alt, (
            'provisioner "file" で source="${local.scripts_dir}/notify.sh" → '
            "${var.install_root}/bin/notify.sh のアップロードが宣言されていない"
        )

    def test_provisioner_file_logrotate_conf_uses_templatefile(self):
        """Given main.tf
        When logrotate.conf を /etc/logrotate.d/youtube-stream に配置する provisioner を読む
        Then ``templatefile("${path.module}/templates/logrotate.conf.tftpl", ...)`` で生成している。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None

        match = re.search(
            r'provisioner\s+"file"\s*\{[^}]*?'
            r'content\s*=\s*templatefile\(\s*"\$\{path\.module\}/templates/logrotate\.conf\.tftpl"'
            r"[^}]*install_root\s*=\s*var\.install_root[^}]*\}\s*\)[^}]*?"
            r'destination\s*=\s*"/etc/logrotate\.d/youtube-stream"[^}]*?\}',
            block,
            flags=re.DOTALL,
        )
        match_alt = re.search(
            r'provisioner\s+"file"\s*\{[^}]*?'
            r'destination\s*=\s*"/etc/logrotate\.d/youtube-stream"[^}]*?'
            r'content\s*=\s*templatefile\(\s*"\$\{path\.module\}/templates/logrotate\.conf\.tftpl"'
            r"[^}]*install_root\s*=\s*var\.install_root[^}]*\}\s*\)[^}]*?\}",
            block,
            flags=re.DOTALL,
        )

        assert match or match_alt, (
            'provisioner "file" で templatefile("${path.module}/templates/logrotate.conf.tftpl", ...) → '
            "/etc/logrotate.d/youtube-stream のアップロードが宣言されていない"
        )

    def test_provisioner_file_cron_d_uses_templatefile(self):
        """Given main.tf
        When cron.d を /etc/cron.d/youtube-stream-healthcheck に配置する provisioner を読む
        Then ``templatefile("${path.module}/templates/cron.d.tftpl", ...)`` で生成している。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None

        match = re.search(
            r'provisioner\s+"file"\s*\{[^}]*?'
            r'content\s*=\s*templatefile\(\s*"\$\{path\.module\}/templates/cron\.d\.tftpl"'
            r"[^}]*install_root\s*=\s*var\.install_root[^}]*\}\s*\)[^}]*?"
            r'destination\s*=\s*"/etc/cron\.d/youtube-stream-healthcheck"[^}]*?\}',
            block,
            flags=re.DOTALL,
        )
        match_alt = re.search(
            r'provisioner\s+"file"\s*\{[^}]*?'
            r'destination\s*=\s*"/etc/cron\.d/youtube-stream-healthcheck"[^}]*?'
            r'content\s*=\s*templatefile\(\s*"\$\{path\.module\}/templates/cron\.d\.tftpl"'
            r"[^}]*install_root\s*=\s*var\.install_root[^}]*\}\s*\)[^}]*?\}",
            block,
            flags=re.DOTALL,
        )

        assert match or match_alt, (
            'provisioner "file" で templatefile("${path.module}/templates/cron.d.tftpl", ...) → '
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
# main.tf — #160 で追加される run-ffmpeg.sh の triggers / provisioner / chmod
# ============================================================================


class TestMainTfRunFfmpegProvisioner:
    """``main.tf`` の #160 ``run-ffmpeg.sh`` 配信配線を検証する。

    検証観点:
      - ``null_resource.deploy.triggers.run_ffmpeg_sh`` が
        ``filemd5("${local.scripts_dir}/run-ffmpeg.sh")`` で参照されている
        （#157 DRY パターン準拠）
      - ``provisioner "file"`` で ``${local.scripts_dir}/run-ffmpeg.sh`` を
        ``${var.install_root}/bin/run-ffmpeg.sh`` にアップロードする
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
        When run-ffmpeg.sh を ${var.install_root}/bin/run-ffmpeg.sh に配置する
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
            rf'destination\s*=\s*"{_INSTALL_ROOT_VAR}/bin/run-ffmpeg\.sh"[^}}]*?\}}',
            block,
            flags=re.DOTALL,
        )
        match_alt = re.search(
            r'provisioner\s+"file"\s*\{[^}]*?'
            rf'destination\s*=\s*"{_INSTALL_ROOT_VAR}/bin/run-ffmpeg\.sh"[^}}]*?'
            r'source\s*=\s*"\$\{local\.scripts_dir\}/run-ffmpeg\.sh"[^}]*?\}',
            block,
            flags=re.DOTALL,
        )

        assert match or match_alt, (
            'provisioner "file" で source="${local.scripts_dir}/run-ffmpeg.sh" → '
            "${var.install_root}/bin/run-ffmpeg.sh のアップロードが宣言されていない"
        )

    def test_remote_exec_chmod_includes_run_ffmpeg_sh(self):
        """Given main.tf
        When ``provisioner "remote-exec"`` の inline を読む
        Then ``chmod 755 ... ${var.install_root}/bin/run-ffmpeg.sh ...`` が含まれている。

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
            rf"chmod\s+755\b[^\n]*{_INSTALL_ROOT_VAR}/bin/run-ffmpeg\.sh\b",
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
