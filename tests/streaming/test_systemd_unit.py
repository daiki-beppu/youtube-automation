"""infra/terraform/streaming の ``templates/youtube-stream.service.tftpl`` の検証テスト。

配信サイクル制御を含む systemd unit テンプレート（#124 / #214 系の追加要件含む）。
"""

from __future__ import annotations

import re

from tests.helpers.hcl import read_file
from tests.streaming._helpers import (
    _INSTALL_ROOT_TFTPL,
    _SYSTEMD_TFTPL,
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

    @staticmethod
    def _render_cycle_template(stream_hours: int, break_hours: int) -> str:
        """Terraform templatefile の cycle 条件だけをテスト用に展開する。"""
        text = read_file(_SYSTEMD_TFTPL)
        text = text.replace("${install_root}", "/opt/youtube-stream")
        if stream_hours > 0:
            text = re.sub(
                r"%\{\s*if stream_hours > 0\s*\}\n(.*?)%\{\s*endif\s*\}",
                lambda match: match.group(1).replace("${stream_hours}", str(stream_hours)),
                text,
                flags=re.DOTALL,
            )
        else:
            text = re.sub(
                r"%\{\s*if stream_hours > 0\s*\}\n.*?%\{\s*endif\s*\}\n?",
                "",
                text,
                flags=re.DOTALL,
            )
        restart_sec = f"RestartSec={break_hours}h" if stream_hours > 0 and break_hours > 0 else "RestartSec=10s"
        text = re.sub(
            r"%\{\s*if stream_hours > 0 && break_hours > 0\s*\}\n.*?%\{\s*else\s*\}\n.*?%\{\s*endif\s*\}",
            restart_sec,
            text,
            flags=re.DOTALL,
        )
        return text

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
        self._assert_service_directive(r"^Type=simple\s*$", "[Service].Type=simple が無い")

    def test_service_environment_file_path(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``EnvironmentFile=/etc/youtube-stream.env`` が宣言されている (R11)。

        secret 隔離の核。VIDEO/RTMP_URL を unit 内に直書きせず .env から読む経路を強制する。
        """
        self._assert_service_directive(
            r"^EnvironmentFile=/etc/youtube-stream\.env\s*$",
            "[Service].EnvironmentFile=/etc/youtube-stream.env が無い（secret 隔離が破綻）",
        )

    def test_service_exec_start_invokes_wrapper_without_env_expansion(self):
        """Given .tftpl
        When [Service].ExecStart を読む
        Then ラッパー ``${install_root}/bin/run-ffmpeg.sh`` のみを呼び、
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
        expected = rf"^ExecStart={_INSTALL_ROOT_TFTPL}/bin/run-ffmpeg\.sh\s*$"
        assert re.search(expected, service, flags=re.MULTILINE), (
            "[Service].ExecStart が ${install_root}/bin/run-ffmpeg.sh のみを呼ぶラッパー化形式（#160）と一致しない"
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

    def test_service_runtime_max_sec_is_conditional_on_stream_hours(self):
        """Given .tftpl
        When [Service] を読む
        Then stream_hours > 0 のときだけ ``RuntimeMaxSec=${stream_hours}h`` が出力される。

        stream_hours=0 は 24/7 連続配信を表し、RuntimeMaxSec 行を省略する。
        """
        text = read_file(_SYSTEMD_TFTPL)
        assert "%{ if stream_hours > 0 }" in text, "stream_hours > 0 の条件分岐が無い"
        assert "RuntimeMaxSec=${stream_hours}h" in text, "RuntimeMaxSec が stream_hours 変数で出力されていない"
        assert self._section(self._render_cycle_template(0, 0), "Service") is not None
        default_service = self._section(self._render_cycle_template(0, 0), "Service")
        legacy_service = self._section(self._render_cycle_template(11, 1), "Service")
        assert default_service is not None
        assert legacy_service is not None
        assert "RuntimeMaxSec" not in default_service, "stream_hours=0 で RuntimeMaxSec が出力されている"
        assert re.search(r"^RuntimeMaxSec=11h\s*$", legacy_service, flags=re.MULTILINE), (
            "stream_hours=11 で RuntimeMaxSec=11h が出力されない"
        )

    def test_service_restart_always(self):
        """Given .tftpl
        When [Service] を読む
        Then ``Restart=always`` が宣言されている (R14)。
        """
        self._assert_service_directive(
            r"^Restart=always\s*$",
            "[Service].Restart=always が無い（停止後に自動再開しない）",
        )

    def test_service_restart_sec_uses_break_hours_or_crash_restart_default(self):
        """Given .tftpl
        When [Service] を読む
        Then break_hours > 0 のとき ``RestartSec=${break_hours}h``、
             0 のとき ``RestartSec=10s`` が出力される。
        """
        text = read_file(_SYSTEMD_TFTPL)
        assert "%{ if stream_hours > 0 && break_hours > 0 }" in text, (
            "stream_hours > 0 && break_hours > 0 の条件分岐が無い"
        )
        assert "RestartSec=${break_hours}h" in text, "RestartSec が break_hours 変数で出力されていない"
        assert "RestartSec=10s" in text, "break_hours=0 用の RestartSec=10s が無い"
        default_service = self._section(self._render_cycle_template(0, 0), "Service")
        legacy_service = self._section(self._render_cycle_template(11, 1), "Service")
        assert default_service is not None
        assert legacy_service is not None
        assert re.search(r"^RestartSec=10s\s*$", default_service, flags=re.MULTILINE), (
            "break_hours=0 で RestartSec=10s が出力されない"
        )
        assert re.search(r"^RestartSec=1h\s*$", legacy_service, flags=re.MULTILINE), (
            "break_hours=1 で RestartSec=1h が出力されない"
        )

    def test_service_restart_sec_ignores_break_hours_when_stream_hours_zero(self):
        """Given stream_hours=0 (24/7 モード) かつ break_hours=1
        When テンプレートを展開する
        Then ``RestartSec=10s`` が出力される（break_hours は無視される）。

        stream_hours=0 では RuntimeMaxSec が省略されるため、RestartSec が長時間になると
        クラッシュ時の再起動が遅延する。24/7 モードでは break_hours を無視して
        常にクラッシュ再起動用の 10s を使う。
        """
        service = self._section(self._render_cycle_template(0, 1), "Service")
        assert service is not None
        assert re.search(r"^RestartSec=10s\s*$", service, flags=re.MULTILINE), (
            "stream_hours=0, break_hours=1 で RestartSec=10s が出力されない（24/7 モードでは break_hours を無視すべき）"
        )
        assert not re.search(r"^RestartSec=1h\s*$", service, flags=re.MULTILINE), (
            "stream_hours=0 なのに RestartSec=1h が出力されている"
            "（RuntimeMaxSec なしで RestartSec が長時間だとクラッシュ復旧が遅延する）"
        )

    def test_service_custom_cycle_values(self):
        """Given stream_hours=8, break_hours=2
        When テンプレートを展開する
        Then RuntimeMaxSec=8h, RestartSec=2h が出力される。
        """
        service = self._section(self._render_cycle_template(8, 2), "Service")
        assert service is not None
        assert re.search(r"^RuntimeMaxSec=8h\s*$", service, flags=re.MULTILINE), (
            "stream_hours=8 で RuntimeMaxSec=8h が出力されない"
        )
        assert re.search(r"^RestartSec=2h\s*$", service, flags=re.MULTILINE), (
            "break_hours=2 で RestartSec=2h が出力されない"
        )

    def test_service_custom_cycle_no_break(self):
        """Given stream_hours=6, break_hours=0
        When テンプレートを展開する
        Then RuntimeMaxSec=6h が出力され、RestartSec=10s（クラッシュ再起動）になる。
        """
        service = self._section(self._render_cycle_template(6, 0), "Service")
        assert service is not None
        assert re.search(r"^RuntimeMaxSec=6h\s*$", service, flags=re.MULTILINE), (
            "stream_hours=6 で RuntimeMaxSec=6h が出力されない"
        )
        assert re.search(r"^RestartSec=10s\s*$", service, flags=re.MULTILINE), (
            "stream_hours=6, break_hours=0 で RestartSec=10s が出力されない"
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
        self._assert_service_directive(
            r"^DynamicUser=yes\s*$",
            "[Service].DynamicUser=yes が無い（root 実行のままだと CVE 経路が塞がらない）",
        )

    def test_service_no_new_privileges(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``NoNewPrivileges=true`` が宣言されている (#159 R2)。

        setuid バイナリによる権限昇格を遮断する hardening の核。
        """
        self._assert_service_directive(
            r"^NoNewPrivileges=true\s*$",
            "[Service].NoNewPrivileges=true が無い（setuid 経由の権限昇格を許す）",
        )

    def test_service_protect_system_strict(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``ProtectSystem=strict`` が宣言されている (#159 R3)。

        ``/`` ``/usr`` ``/boot`` ``/etc`` を read-only にする hardening の核。
        """
        self._assert_service_directive(
            r"^ProtectSystem=strict\s*$",
            "[Service].ProtectSystem=strict が無い（/usr などへの書き込みが防げない）",
        )

    def test_service_protect_home_true(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``ProtectHome=true`` が宣言されている (#159 R4)。

        ``/home`` の不可視化による secret 漏洩経路の遮断。
        """
        self._assert_service_directive(
            r"^ProtectHome=true\s*$",
            "[Service].ProtectHome=true が無い（/home からの secret 漏洩経路が残る）",
        )

    def test_service_private_tmp(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``PrivateTmp=true`` が宣言されている (#159 R5)。

        ``/tmp`` を namespace で隔離し他プロセスとの共有を遮断する。
        """
        self._assert_service_directive(
            r"^PrivateTmp=true\s*$",
            "[Service].PrivateTmp=true が無い（/tmp 経由の干渉が防げない）",
        )

    def test_service_private_devices(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``PrivateDevices=true`` が宣言されている (#159 R6)。

        ``/dev`` を最小サブセット化し物理デバイスへの直接アクセスを遮断する。
        """
        self._assert_service_directive(
            r"^PrivateDevices=true\s*$",
            "[Service].PrivateDevices=true が無い（/dev 経由の物理デバイス露出が残る）",
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
        Then ``ReadOnlyPaths=${install_root}/videos`` が宣言されている (#159 R9)。

        動画ファイルの書き換え防止。``ProtectSystem=strict`` と組み合わせて
        書き込み可能領域を最小化する。
        """
        self._assert_service_directive(
            rf"^ReadOnlyPaths={_INSTALL_ROOT_TFTPL}/videos\s*$",
            "[Service].ReadOnlyPaths=${install_root}/videos が無い（動画ファイルの書き換え防止が効かない）",
        )

    def test_service_read_write_paths_logs(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``ReadWritePaths=${install_root}/logs`` が宣言されている (#159 R10)。

        logrotate 対象パスの書き込み許可（spec 指示）。``ProtectSystem=strict`` 下で
        書き込みが必要な領域を明示する。
        """
        self._assert_service_directive(
            rf"^ReadWritePaths={_INSTALL_ROOT_TFTPL}/logs\s*$",
            "[Service].ReadWritePaths=${install_root}/logs が無い（logs ディレクトリへの書き込み経路が破綻）",
        )

    def test_only_install_root_terraform_interpolation_remains(self):
        """Given .tftpl
        When 全文を読む
        Then systemd unit に渡す Terraform 補間だけが残っている (R20 の片側)。

        ``$VIDEO`` ``$RTMP_URL`` は systemd の env 参照（波括弧なし）であり terraform は素通しする。
        templatefile() の variables map にない補間を書くと評価時に未定義変数で fail する。
        """
        text = read_file(_SYSTEMD_TFTPL)
        interpolations = re.findall(r"\$\{[^}]+\}", text)
        assert interpolations, "Terraform 補間が無い（install_root の配線検証になっていない）"
        assert set(interpolations) <= {"${install_root}", "${stream_hours}", "${break_hours}"}, (
            "templatefile() に渡していない補間が残っている（systemd で参照したい場合は $NAME と書く / "
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

        起動失敗カウントの時間窓を無効化し、``Restart=always`` + ``RestartSec``
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

        ``RuntimeMaxSec`` 到達時の SIGTERM 終了を明示的に success 扱いに揃え、
        healthcheck の anomaly 誤判定経路を遮断する。
        """
        self._assert_service_directive(
            r"^SuccessExitStatus=143\s+SIGTERM\s*$",
            "[Service].SuccessExitStatus=143 SIGTERM が無い（SIGTERM 終了を anomaly 誤判定する余地が残る）",
        )

    def test_service_timeout_stop_sec_30s(self):
        """Given .tftpl
        When [Service] セクションを読む
        Then ``TimeoutStopSec=30s`` が宣言されている (#214)。

        SIGTERM → SIGKILL 待機を 90s から 30s に短縮し、ffmpeg flush の現実的時間に揃える。
        """
        self._assert_service_directive(
            r"^TimeoutStopSec=30s\s*$",
            "[Service].TimeoutStopSec=30s が無い（停止待機がデフォルト 90s のままになる）",
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
