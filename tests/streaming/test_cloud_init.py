"""infra/terraform/streaming の cloud-init / env テンプレートの検証テスト。

- ``cloud-init.yaml``: package_update / packages / runcmd / write_files / daemon-reload (#124)
- ``templates/youtube-stream.env.tftpl``: ffmpeg 環境変数
"""

from __future__ import annotations

import re

import yaml

from tests.helpers.hcl import read_file
from tests.streaming._helpers import (
    _CLOUD_INIT_YAML,
    _DEFAULT_INSTALL_ROOT,
    _ENV_TFTPL,
    _extract_yaml_packages_block,
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

    def test_declares_ssh_keys_block_for_ed25519_host_key(self):
        """Given cloud-init.yaml
        When ssh_keys ブロックを読む
        Then ed25519_private / ed25519_public の両方を template 変数経由で埋め込む。
        """
        text = read_file(_CLOUD_INIT_YAML)
        assert re.search(r"^ssh_keys:\s*$", text, flags=re.MULTILINE), "ssh_keys: ブロックが存在しない"
        assert re.search(r"^\s+ed25519_private:\s+\|$", text, flags=re.MULTILINE), (
            "ssh_keys.ed25519_private の block scalar 宣言が無い"
        )
        assert '${replace(trimspace(ssh_host_private_key), "\\n", "\\n    ")}' in text, (
            "ssh_keys.ed25519_private が ssh_host_private_key template を参照していない"
        )
        assert "${trimspace(ssh_host_public_key)}" in text, (
            "ssh_keys.ed25519_public が ssh_host_public_key template を参照していない"
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

    def test_runcmd_does_not_own_deploy_directories(self):
        """Given cloud-init.yaml, Then deploy-owned install_root paths are absent."""
        assert "${install_root}" not in read_file(_CLOUD_INIT_YAML)

    def test_cloud_init_yaml_no_longer_bakes_systemd_unit(self):
        """Given cloud-init.yaml
        When 全文を読む
        Then ``systemd_unit`` テンプレート変数・
             ``/etc/systemd/system/youtube-stream.service`` パスのいずれも含まれない (#212)。

        systemd unit は ``null_resource.deploy`` の ``provisioner "file"`` で SCP 配信するように
        統一されたため、cloud-init 側に unit の焼き付け経路を残してはならない。残骸を残すと
        「設定したのに使われない」混乱と、初回 apply 時の二重配置リスクを招く。

        ``write_files`` 自体は sshd など OS 初期設定ファイルの配置に利用できるため禁止しない。
        """
        text = read_file(_CLOUD_INIT_YAML)
        assert "systemd_unit" not in text, (
            "cloud-init.yaml に systemd_unit テンプレート変数が残っている"
            "（user_data の内側 templatefile 結線が撤去されたため未定義変数になる）"
        )
        assert not re.search(r"/etc/systemd/system/youtube-stream\.service", text), (
            "cloud-init.yaml に /etc/systemd/system/youtube-stream.service の配置宣言が残っている"
        )

    def test_write_files_pins_sshd_to_ed25519_host_key(self):
        """Given cloud-init.yaml
        When ``write_files`` を読む
        Then sshd drop-in が ed25519 host key だけを提示する設定で配置される。

        openssh-server の更新で ECDSA/RSA 鍵が再生成されても、Terraform provisioner の
        ``host_key``（ed25519 固定）と SSH サーバーの提示鍵が食い違わないことを保証する。
        """
        loaded = yaml.safe_load(read_file(_CLOUD_INIT_YAML))
        entries = loaded.get("write_files", [])
        drop_in = next(
            (entry for entry in entries if entry.get("path") == "/etc/ssh/sshd_config.d/99-hostkey-ed25519.conf"),
            None,
        )

        assert drop_in is not None, "sshd の ed25519 host key 固定用 drop-in が配置されていない"
        assert drop_in.get("owner") == "root:root", "sshd drop-in の owner が root:root でない"
        assert drop_in.get("permissions") == "0644", "sshd drop-in の permissions が 0644 でない"
        assert drop_in.get("content", "").splitlines() == ["HostKey /etc/ssh/ssh_host_ed25519_key"], (
            "sshd drop-in が ed25519 以外の host key も提示する設定になっている"
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

    def test_hardening_runcmd_order(self):
        """Given cloud-init.yaml
        When runcmd の出現順序を読む
        Then hardening 3 行が sed → reload → reconfigure の順で配置されている。

        早期 hardening の意図に従い、issue 推奨形どおり 3 行を runcmd 先頭に挿入する。
        """
        text = read_file(_CLOUD_INIT_YAML)
        sed_idx = text.find("sed -i")
        reload_idx = text.find("systemctl reload ssh")
        reconfigure_idx = text.find("dpkg-reconfigure")
        assert sed_idx != -1, "sed -i 行が cloud-init.yaml に見つからない（前段確認）"
        assert reload_idx != -1, "systemctl reload ssh 行が cloud-init.yaml に見つからない（前段確認）"
        assert reconfigure_idx != -1, "dpkg-reconfigure 行が cloud-init.yaml に見つからない（前段確認）"
        assert sed_idx < reload_idx < reconfigure_idx, (
            "hardening 3 行が sed → systemctl reload ssh → dpkg-reconfigure の順でない"
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
            rf"{re.escape(_DEFAULT_INSTALL_ROOT)}/videos/[^\s$]+\.(mp4|mkv|mov|webm)",
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
