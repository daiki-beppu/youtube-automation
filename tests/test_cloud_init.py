"""infra/terraform/streaming/cloud-init.yaml と systemd unit テンプレートの構造検証テスト。

issue #124 の order.md と plan.md に基づき、以下を検証する:

- ``cloud-init.yaml``: ``#cloud-config`` 先頭 / ``package_update`` / ``packages`` /
  ``runcmd`` での ``/opt/youtube-stream/{videos,logs}`` 作成 / ``daemon-reload`` /
  ``write_files`` での systemd unit 配置 / ``${youtube_stream_service}`` プレースホルダ /
  ``enable --now`` 不在 / secret 不在
- ``templates/youtube-stream.service.tftpl``: 3 セクション存在 /
  ``EnvironmentFile=/etc/youtube-stream.env`` / ``ExecStart`` リテラル一致 /
  ``Restart=always`` / ``RestartSec=5`` / ``StandardOutput``/``StandardError`` /
  ``WantedBy=multi-user.target`` / リテラル stream key / RTMP URL 不在
- 結合: ``${youtube_stream_service}`` を unit テキストで実置換した結果が
  PyYAML でパース可能（インデント破綻検出）

terraform バイナリに依存せず、ファイルテキストを正規表現と PyYAML で
構造検証する。実 ``terraform validate`` / ``apply`` は手動検証。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

# ---------- パス定数 ----------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_STREAMING_DIR = _REPO_ROOT / "infra" / "terraform" / "streaming"

_CLOUD_INIT_YAML = _STREAMING_DIR / "cloud-init.yaml"
_TEMPLATES_DIR = _STREAMING_DIR / "templates"
_UNIT_TFTPL = _TEMPLATES_DIR / "youtube-stream.service.tftpl"


# ---------- ヘルパー ----------


def _read(path: Path) -> str:
    if not path.exists():
        pytest.fail(f"必須ファイルが存在しない: {path.relative_to(_REPO_ROOT)}")
    return path.read_text(encoding="utf-8")


def _render_terraform_indent(template_text: str, var_name: str, content: str) -> str:
    """``${indent(N, var_name)}`` プレースホルダを Terraform 互換に展開する。

    Terraform の ``indent(N, str)`` は ``str`` の 2 行目以降に N 個の空白を
    プレフィックスする（1 行目はそのまま）。テンプレ側でプレースホルダ自体が
    既にインデントされている前提で、結果として全行が同じ列に揃う。

    本ヘルパーは ``${indent(<N>, <var_name>)}`` および ``${<var_name>}`` の
    両方の記法を 1 度だけ展開する（テストとしての厳密さを保ちつつ、
    実装側の細かな書き方差を吸収する）。
    """

    def _indent_replacer(match: re.Match[str]) -> str:
        n = int(match.group(1))
        first, *rest = content.splitlines()
        if not rest:
            return first
        prefix = " " * n
        return "\n".join([first, *[prefix + line for line in rest]])

    pattern_indent = re.compile(r"\$\{\s*indent\(\s*(\d+)\s*,\s*" + re.escape(var_name) + r"\s*\)\s*\}")
    rendered, replacements = pattern_indent.subn(_indent_replacer, template_text)
    if replacements:
        return rendered

    # indent() を使わず素の ${var} 形式で書かれている場合のフォールバック
    pattern_plain = re.compile(r"\$\{\s*" + re.escape(var_name) + r"\s*\}")
    return pattern_plain.sub(content, template_text)


# ---------- フィクスチャ ----------


@pytest.fixture
def cloud_init_text() -> str:
    return _read(_CLOUD_INIT_YAML)


@pytest.fixture
def unit_text() -> str:
    return _read(_UNIT_TFTPL)


# ============================================================================
# cloud-init.yaml: 先頭 / トップレベル構造
# ============================================================================


class TestCloudInitTopLevel:
    """``cloud-init.yaml`` のトップレベル構造（cloud-config の必須要素）。"""

    def test_cloud_init_yaml_exists(self):
        """Given infra/terraform/streaming/
        When cloud-init.yaml を探す
        Then 存在する。
        """
        assert _CLOUD_INIT_YAML.exists(), f"必須ファイルが存在しない: {_CLOUD_INIT_YAML.relative_to(_REPO_ROOT)}"

    def test_starts_with_cloud_config_header(self, cloud_init_text: str):
        """Given cloud-init.yaml
        When 先頭行を読む
        Then ``#cloud-config`` で始まる（cloud-init が user_data を YAML として認識する条件）。
        """
        first_line = cloud_init_text.splitlines()[0] if cloud_init_text else ""
        assert first_line.strip() == "#cloud-config", f"先頭行が #cloud-config でない: {first_line!r}"

    def test_package_update_is_true(self, cloud_init_text: str):
        """Given cloud-init.yaml
        When ``package_update`` を探す
        Then ``true`` に設定されている（apt update を実行）。
        """
        assert re.search(r"^\s*package_update\s*:\s*true\b", cloud_init_text, flags=re.MULTILINE), (
            "package_update: true が宣言されていない"
        )

    def test_packages_includes_ffmpeg(self, cloud_init_text: str):
        """Given cloud-init.yaml
        When ``packages:`` リストを読む
        Then ``ffmpeg`` が含まれている。
        """
        # PyYAML でパースして packages を取り出す（template 部分を除いてパースできる箇所のみ確認）
        # 実テンプレ展開後の検証は別テストで行うため、ここではパース不要な文字列レベルで確認する。
        assert re.search(r"^\s*-\s*ffmpeg\b", cloud_init_text, flags=re.MULTILINE), (
            "packages リストに ffmpeg が含まれていない"
        )


# ============================================================================
# cloud-init.yaml: write_files / runcmd
# ============================================================================


class TestCloudInitWriteFiles:
    """``write_files`` で systemd unit を ``/etc/systemd/system/youtube-stream.service`` に配置。"""

    def test_write_files_targets_systemd_unit_path(self, cloud_init_text: str):
        """Given cloud-init.yaml
        When ``write_files`` 配下の path を探す
        Then ``/etc/systemd/system/youtube-stream.service`` が宣言されている。
        """
        assert re.search(
            r"^\s*-?\s*path\s*:\s*/etc/systemd/system/youtube-stream\.service\b",
            cloud_init_text,
            flags=re.MULTILINE,
        ), "write_files で /etc/systemd/system/youtube-stream.service が指定されていない"

    def test_write_files_owner_root_root(self, cloud_init_text: str):
        """Given cloud-init.yaml
        When ``write_files`` のエントリを読む
        Then owner = ``root:root`` が設定されている（systemd unit の所有者）。
        """
        assert re.search(
            r"^\s*owner\s*:\s*['\"]?root:root['\"]?\b",
            cloud_init_text,
            flags=re.MULTILINE,
        ), "write_files の owner が root:root で設定されていない"

    def test_write_files_permissions_0644(self, cloud_init_text: str):
        """Given cloud-init.yaml
        When ``write_files`` の permissions を読む
        Then ``0644``（systemd unit の標準パーミッション）。
        """
        assert re.search(
            r"^\s*permissions\s*:\s*['\"]0644['\"]",
            cloud_init_text,
            flags=re.MULTILINE,
        ), "write_files の permissions が '0644' でない"

    def test_unit_content_uses_youtube_stream_service_placeholder(self, cloud_init_text: str):
        """Given cloud-init.yaml
        When ``content:`` 配下のテキストを読む
        Then ``${...youtube_stream_service...}`` プレースホルダで unit を流し込んでいる
             （unit テキストを直書きしていない）。
        """
        # ${indent(6, youtube_stream_service)} もしくは ${youtube_stream_service} のいずれか
        assert re.search(
            r"\$\{[^}]*\byoutube_stream_service\b[^}]*\}",
            cloud_init_text,
        ), "${...youtube_stream_service...} プレースホルダが存在しない（unit が直書きされている可能性）"


class TestCloudInitRuncmd:
    """``runcmd`` で 3 ディレクトリ作成 + ``daemon-reload`` を実行。"""

    def test_runcmd_creates_videos_directory(self, cloud_init_text: str):
        """Given cloud-init.yaml
        When ``runcmd`` を読む
        Then ``/opt/youtube-stream/videos`` を root:root, 0755 で作成するコマンドがある。
        """
        # `install -d` でも `mkdir -p && chown && chmod` でも、`/opt/youtube-stream/videos`
        # を作成する行があれば良い（最終状態で root:root 0755 になっていること）
        assert re.search(
            r"/opt/youtube-stream/videos\b",
            cloud_init_text,
        ), "runcmd で /opt/youtube-stream/videos を作成していない"

    def test_runcmd_creates_logs_directory(self, cloud_init_text: str):
        """Given cloud-init.yaml
        When ``runcmd`` を読む
        Then ``/opt/youtube-stream/logs`` を作成するコマンドがある。
        """
        assert re.search(
            r"/opt/youtube-stream/logs\b",
            cloud_init_text,
        ), "runcmd で /opt/youtube-stream/logs を作成していない"

    def test_runcmd_directories_are_root_owned_with_0755(self, cloud_init_text: str):
        """Given cloud-init.yaml
        When ``runcmd`` のディレクトリ作成コマンドを読む
        Then root 所有 + mode 0755 の指示が含まれている。

        ``install -d -o root -g root -m 0755 ...`` 形式、
        または ``mkdir -p ... && chown root:root ... && chmod 0755 ...`` 形式の
        いずれかが許容される。
        """
        # `install -d` を 1 行でも使っていれば owner/group/mode が同時指定されているはず
        has_install_form = re.search(
            r"install\s+-d\s+(?:-[ogm]\s+\S+\s+){2,}",
            cloud_init_text,
        )
        # フォールバック: mkdir + chown + chmod の組み合わせ
        has_explicit_mode = "0755" in cloud_init_text and re.search(
            r"chown\s+root:root\b",
            cloud_init_text,
        )
        assert has_install_form or has_explicit_mode, "ディレクトリ作成で root:root / 0755 を保証する指示がない"

    def test_runcmd_calls_daemon_reload(self, cloud_init_text: str):
        """Given cloud-init.yaml
        When ``runcmd`` を読む
        Then ``systemctl daemon-reload`` を呼んでいる（unit 配置後の必須手順）。
        """
        assert re.search(
            r"systemctl\s+daemon-reload\b",
            cloud_init_text,
        ), "runcmd に systemctl daemon-reload が無い"


# ============================================================================
# cloud-init.yaml: スコープ外項目の不在 / secret 不在
# ============================================================================


class TestCloudInitOutOfScopeAbsence:
    """次 issue 担当の項目が混入していないこと。"""

    def test_does_not_enable_youtube_stream_service(self, cloud_init_text: str):
        """Given cloud-init.yaml
        When ``systemctl enable`` の文字列を探す
        Then 存在しない（``enable --now`` は次 issue で追加する）。

        本 issue で enable してしまうと .env / 動画未配置のまま起動失敗ループに入る。
        """
        # `systemctl enable` も `enable --now` も書かない
        assert not re.search(
            r"systemctl\s+enable\b",
            cloud_init_text,
        ), "systemctl enable が含まれている（次 issue 担当項目を先取りしてはならない）"
        assert "--now" not in cloud_init_text, "--now が含まれている（次 issue 担当項目を先取りしてはならない）"

    def test_does_not_write_youtube_stream_env(self, cloud_init_text: str):
        """Given cloud-init.yaml
        When ``/etc/youtube-stream.env`` への ``write_files`` を探す
        Then 存在しない（.env 配置は次 issue 担当）。

        write_files の path として ``/etc/youtube-stream.env`` が出現してはいけない。
        unit 内の ``EnvironmentFile=/etc/youtube-stream.env`` は宣言なので OK。
        """
        assert not re.search(
            r"^\s*-?\s*path\s*:\s*/etc/youtube-stream\.env\b",
            cloud_init_text,
            flags=re.MULTILINE,
        ), "write_files で /etc/youtube-stream.env を書いている（次 issue 担当）"


class TestCloudInitNoSecrets:
    """``user_data`` に secret が含まれないこと（plan 差分でも露出しない要件）。"""

    def test_does_not_contain_rtmp_url(self, cloud_init_text: str):
        """Given cloud-init.yaml
        When 本文を走査する
        Then ``rtmp://`` / ``rtmps://`` で始まる URL が含まれない。
        """
        assert "rtmp://" not in cloud_init_text, "rtmp:// URL が含まれている（secret 漏洩リスク）"
        assert "rtmps://" not in cloud_init_text, "rtmps:// URL が含まれている（secret 漏洩リスク）"

    def test_does_not_contain_youtube_live_endpoint(self, cloud_init_text: str):
        """Given cloud-init.yaml
        When 本文を走査する
        Then YouTube Live RTMP のエンドポイント（``a.rtmp.youtube.com`` 等）が含まれない。
        """
        assert "rtmp.youtube.com" not in cloud_init_text, "rtmp.youtube.com が含まれている（secret 漏洩リスク）"

    def test_does_not_contain_stream_key_assignment(self, cloud_init_text: str):
        """Given cloud-init.yaml
        When 本文を走査する
        Then ``stream_key=`` / ``STREAM_KEY=`` 形式の代入が含まれない。
        """
        assert not re.search(
            r"\b(stream[_-]?key|STREAM[_-]?KEY)\s*[:=]\s*\S",
            cloud_init_text,
        ), "stream_key 代入が含まれている（secret 漏洩リスク）"


# ============================================================================
# youtube-stream.service.tftpl: セクション構造
# ============================================================================


class TestUnitTftplSections:
    """systemd unit の ``[Unit]`` / ``[Service]`` / ``[Install]`` セクション。"""

    def test_unit_tftpl_exists(self):
        """Given infra/terraform/streaming/templates/
        When youtube-stream.service.tftpl を探す
        Then 存在する。
        """
        assert _UNIT_TFTPL.exists(), f"必須ファイルが存在しない: {_UNIT_TFTPL.relative_to(_REPO_ROOT)}"

    def test_unit_section_exists(self, unit_text: str):
        """Given youtube-stream.service.tftpl
        When ``[Unit]`` セクションを探す
        Then 存在する。
        """
        assert re.search(r"^\[Unit\]\s*$", unit_text, flags=re.MULTILINE), "[Unit] セクションが存在しない"

    def test_service_section_exists(self, unit_text: str):
        """Given youtube-stream.service.tftpl
        When ``[Service]`` セクションを探す
        Then 存在する。
        """
        assert re.search(r"^\[Service\]\s*$", unit_text, flags=re.MULTILINE), "[Service] セクションが存在しない"

    def test_install_section_exists(self, unit_text: str):
        """Given youtube-stream.service.tftpl
        When ``[Install]`` セクションを探す
        Then 存在する。
        """
        assert re.search(r"^\[Install\]\s*$", unit_text, flags=re.MULTILINE), "[Install] セクションが存在しない"


class TestUnitTftplUnitDirectives:
    """``[Unit]`` セクションのディレクティブ。"""

    def test_unit_has_description(self, unit_text: str):
        """Given youtube-stream.service.tftpl
        When ``[Unit]`` セクションを読む
        Then ``Description=`` が宣言されている（systemd ベストプラクティス）。
        """
        assert re.search(r"^Description=.+$", unit_text, flags=re.MULTILINE), "Description= が無い"

    def test_unit_after_network_online(self, unit_text: str):
        """Given youtube-stream.service.tftpl
        When ``[Unit]`` セクションを読む
        Then ``After=network-online.target`` が宣言されている（NW 待機）。
        """
        assert re.search(
            r"^After=.*\bnetwork-online\.target\b",
            unit_text,
            flags=re.MULTILINE,
        ), "After=network-online.target が無い"

    def test_unit_wants_network_online(self, unit_text: str):
        """Given youtube-stream.service.tftpl
        When ``[Unit]`` セクションを読む
        Then ``Wants=network-online.target`` が宣言されている。

        ``After`` だけだとターゲットが pulled in されない場合があるため
        ``Wants`` でも要求する。
        """
        assert re.search(
            r"^Wants=.*\bnetwork-online\.target\b",
            unit_text,
            flags=re.MULTILINE,
        ), "Wants=network-online.target が無い"


class TestUnitTftplServiceDirectives:
    """``[Service]`` セクションのディレクティブ。"""

    def test_service_type_simple(self, unit_text: str):
        """Given youtube-stream.service.tftpl
        When ``[Service]`` セクションを読む
        Then ``Type=simple`` が宣言されている（fork しない長期プロセス）。
        """
        assert re.search(r"^Type=simple\s*$", unit_text, flags=re.MULTILINE), "Type=simple が無い"

    def test_service_environment_file_path(self, unit_text: str):
        """Given youtube-stream.service.tftpl
        When ``[Service]`` セクションを読む
        Then ``EnvironmentFile=/etc/youtube-stream.env`` が宣言されている
             （stream key を unit 内に直書きしないための要）。
        """
        assert re.search(
            r"^EnvironmentFile=/etc/youtube-stream\.env\s*$",
            unit_text,
            flags=re.MULTILINE,
        ), "EnvironmentFile=/etc/youtube-stream.env が無い（secret 隔離が機能しない）"

    def test_service_exec_start_literal(self, unit_text: str):
        """Given youtube-stream.service.tftpl
        When ``[Service]`` セクションを読む
        Then ``ExecStart=/usr/bin/ffmpeg -re -stream_loop -1 -i $VIDEO -c copy -f flv $RTMP_URL``
             がリテラル一致する（order.md で明示された形）。
        """
        expected = "ExecStart=/usr/bin/ffmpeg -re -stream_loop -1 -i $VIDEO -c copy -f flv $RTMP_URL"
        # 行末の余分な空白は許容するが本体はリテラル一致
        assert re.search(
            r"^" + re.escape(expected) + r"\s*$",
            unit_text,
            flags=re.MULTILINE,
        ), f"ExecStart が指定リテラルと一致しない（期待: {expected!r}）"

    def test_service_restart_always(self, unit_text: str):
        """Given youtube-stream.service.tftpl
        When ``[Service]`` セクションを読む
        Then ``Restart=always`` が宣言されている（プロセス死活で自動再起動）。
        """
        assert re.search(r"^Restart=always\s*$", unit_text, flags=re.MULTILINE), "Restart=always が無い"

    def test_service_restart_sec_5(self, unit_text: str):
        """Given youtube-stream.service.tftpl
        When ``[Service]`` セクションを読む
        Then ``RestartSec=5`` が宣言されている（リトライ間隔）。
        """
        assert re.search(r"^RestartSec=5\s*$", unit_text, flags=re.MULTILINE), "RestartSec=5 が無い"

    def test_service_standard_output_appends_log(self, unit_text: str):
        """Given youtube-stream.service.tftpl
        When ``[Service]`` セクションを読む
        Then ``StandardOutput=append:/opt/youtube-stream/logs/ffmpeg.log`` が宣言されている。
        """
        assert re.search(
            r"^StandardOutput=append:/opt/youtube-stream/logs/ffmpeg\.log\s*$",
            unit_text,
            flags=re.MULTILINE,
        ), "StandardOutput=append:/opt/youtube-stream/logs/ffmpeg.log が無い"

    def test_service_standard_error_appends_log(self, unit_text: str):
        """Given youtube-stream.service.tftpl
        When ``[Service]`` セクションを読む
        Then ``StandardError=append:/opt/youtube-stream/logs/ffmpeg.log`` が宣言されている。
        """
        assert re.search(
            r"^StandardError=append:/opt/youtube-stream/logs/ffmpeg\.log\s*$",
            unit_text,
            flags=re.MULTILINE,
        ), "StandardError=append:/opt/youtube-stream/logs/ffmpeg.log が無い"


class TestUnitTftplInstallDirectives:
    """``[Install]`` セクションのディレクティブ。"""

    def test_install_wanted_by_multi_user(self, unit_text: str):
        """Given youtube-stream.service.tftpl
        When ``[Install]`` セクションを読む
        Then ``WantedBy=multi-user.target`` が宣言されている。
        """
        assert re.search(
            r"^WantedBy=multi-user\.target\s*$",
            unit_text,
            flags=re.MULTILINE,
        ), "WantedBy=multi-user.target が無い"


class TestUnitTftplNoSecrets:
    """unit テンプレに secret が含まれないこと（``ExecStart`` 直書き禁止の検証）。"""

    def test_no_rtmp_url_literal(self, unit_text: str):
        """Given youtube-stream.service.tftpl
        When 本文を走査する
        Then ``rtmp://`` / ``rtmps://`` URL が含まれない。
        """
        assert "rtmp://" not in unit_text, "unit に rtmp:// URL がリテラル含まれている"
        assert "rtmps://" not in unit_text, "unit に rtmps:// URL がリテラル含まれている"

    def test_no_youtube_live_endpoint(self, unit_text: str):
        """Given youtube-stream.service.tftpl
        When 本文を走査する
        Then ``rtmp.youtube.com`` が含まれない。
        """
        assert "rtmp.youtube.com" not in unit_text, "unit に rtmp.youtube.com がリテラル含まれている"

    def test_no_stream_key_value(self, unit_text: str):
        """Given youtube-stream.service.tftpl
        When 本文を走査する
        Then ``$VIDEO`` / ``$RTMP_URL`` 以外の変数代入や stream key 値が含まれない。

        ``Environment=KEY=VALUE`` 形式での値直書きは EnvironmentFile 方針に反する。
        """
        # `Environment=` で値を直接設定していないこと（EnvironmentFile= は別キーなので OK）
        assert not re.search(
            r"^Environment=\S",
            unit_text,
            flags=re.MULTILINE,
        ), "Environment= で値を直書きしている（EnvironmentFile= に統一すべき）"


# ============================================================================
# 結合: cloud-init.yaml + unit を実置換した結果が valid YAML
# ============================================================================


class TestCloudInitWithUnitRendersValidYaml:
    """``${...youtube_stream_service...}`` を unit テキストで置換した結果が PyYAML でパース可能。"""

    def test_rendered_cloud_init_is_valid_yaml(self, cloud_init_text: str, unit_text: str):
        """Given cloud-init.yaml + youtube-stream.service.tftpl
        When ``${indent(6, youtube_stream_service)}`` を unit で置換する
        Then PyYAML で構文エラーなくパースできる（インデント破綻が無い）。
        """
        rendered = _render_terraform_indent(cloud_init_text, "youtube_stream_service", unit_text)
        try:
            data = yaml.safe_load(rendered)
        except yaml.YAMLError as exc:
            pytest.fail(f"render 後の cloud-init.yaml が valid YAML でない: {exc}")
        assert isinstance(data, dict), "render 後のトップレベルが mapping でない"

    def test_rendered_yaml_packages_includes_ffmpeg(self, cloud_init_text: str, unit_text: str):
        """Given render 済み cloud-init.yaml
        When ``packages`` フィールドを読む
        Then list 形式で ``ffmpeg`` を含む。
        """
        rendered = _render_terraform_indent(cloud_init_text, "youtube_stream_service", unit_text)
        data = yaml.safe_load(rendered)
        packages = data.get("packages")
        assert isinstance(packages, list), "packages が list でない"
        assert "ffmpeg" in packages, f"packages に ffmpeg が含まれない: {packages!r}"

    def test_rendered_yaml_write_files_contains_unit_content(self, cloud_init_text: str, unit_text: str):
        """Given render 済み cloud-init.yaml
        When ``write_files`` の content フィールドを読む
        Then ``ExecStart=/usr/bin/ffmpeg ...`` が完全な行として含まれる。

        プレースホルダ展開後に unit の中身が破損なく流し込まれていることの最終チェック。
        """
        rendered = _render_terraform_indent(cloud_init_text, "youtube_stream_service", unit_text)
        data = yaml.safe_load(rendered)
        write_files = data.get("write_files")
        assert isinstance(write_files, list) and write_files, "write_files が list でないか空"
        # /etc/systemd/system/youtube-stream.service エントリを探す
        unit_entry = next(
            (
                entry
                for entry in write_files
                if isinstance(entry, dict) and entry.get("path") == "/etc/systemd/system/youtube-stream.service"
            ),
            None,
        )
        assert unit_entry is not None, "write_files に /etc/systemd/system/youtube-stream.service エントリが無い"
        content = unit_entry.get("content", "")
        assert "ExecStart=/usr/bin/ffmpeg -re -stream_loop -1 -i $VIDEO -c copy -f flv $RTMP_URL" in content, (
            "render 後の unit content に ExecStart リテラルが含まれない（インデント破綻の可能性）"
        )
        assert "EnvironmentFile=/etc/youtube-stream.env" in content, (
            "render 後の unit content に EnvironmentFile= が含まれない"
        )
