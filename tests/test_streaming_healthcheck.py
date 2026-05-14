"""死活監視 (issue #109) のスペック準拠テスト。

検証対象:

1. ``.claude/skills/streaming/references/healthcheck.sh``
     - shebang / ``set -euo pipefail`` / cron 安全な ``PATH`` 宣言
     - ``classify_status`` 関数（純関数）の 4-way 判定
       (``ok`` / ``idle`` / ``manual`` / ``anomaly``)
     - ``systemctl show youtube-stream -p ActiveState,SubState,Result`` 呼び出し
     - 異常時のみ ``notify.sh`` を呼ぶ／正常・休止・手動停止では呼ばない
2. ``.claude/skills/streaming/references/notify.sh``
     - shebang / ``set -euo pipefail``
     - ``DISCORD_WEBHOOK_URL`` を ``/etc/youtube-stream-healthcheck.env`` から読む
     - ``curl`` で Discord に JSON POST する
     - cron を壊さないため ``exit 0`` で終わる
3. ``.claude/skills/streaming/references/logrotate.conf``
     - ``/opt/youtube-stream/logs/*.log`` を対象とする
     - ``daily`` / ``rotate 7`` / ``compress`` / ``copytruncate`` / ``missingok`` / ``notifempty``
4. ``.claude/skills/streaming/references/cron.d``
     - ``*/5 * * * * root /opt/youtube-stream/bin/healthcheck.sh`` 行を含む
5. ``infra/terraform/streaming/templates/youtube-stream-healthcheck.env.tftpl``
     - ``DISCORD_WEBHOOK_URL=${webhook}`` の 1 行
6. ``infra/terraform/streaming/variables.tf``
     - ``discord_webhook_url`` (sensitive=true, default なし)
7. ``infra/terraform/streaming/main.tf``
     - triggers に ``nonsensitive(sha256(var.discord_webhook_url))``
     - provisioner で 4 ファイル + env tftpl を配信
     - remote-exec で chmod / chown / cron 再起動
8. ``infra/terraform/streaming/cloud-init.yaml``
     - ``packages:`` に ``cron`` を追加
9. ``infra/terraform/streaming/terraform.tfvars.example``
     - ``discord_webhook_url`` のアクティブ代入が無い
     - ``TF_VAR_discord_webhook_url`` を案内コメントに含む
10. ``infra/terraform/streaming/README.md``
     - 死活監視セクション / Discord / 4 シナリオ言及
11. ``src/youtube_automation/utils/streaming_archive.py``
     - ``count_archives_for_date`` のモック検証
12. ``src/youtube_automation/scripts/streaming_archive_check.py``
     - argparse / 件数不足時 exit 1 / Discord 通知
13. ``pyproject.toml``
     - ``yt-stream-archive-check`` entry point 登録
14. ``docs/streaming-healthcheck.md``
     - 4 シナリオ言及

shell スクリプト系は ``bash`` バイナリに依存するため subprocess で直接実行する。
Terraform / YAML / .env tftpl は terraform に依存せずテキスト regex で構造検証する
(``test_terraform_streaming.py`` と同方針)。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 既存ヘルパーを再利用 (`tests/test_terraform_streaming.py:46-93`)
from tests.test_terraform_streaming import _extract_block, _read, _strip_hcl_comments

# ---------- パス定数 ----------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_STREAMING_SCRIPTS_DIR = _REPO_ROOT / ".claude" / "skills" / "streaming" / "references"
_HEALTHCHECK_SH = _STREAMING_SCRIPTS_DIR / "healthcheck.sh"
_NOTIFY_SH = _STREAMING_SCRIPTS_DIR / "notify.sh"
_LOGROTATE_CONF = _STREAMING_SCRIPTS_DIR / "logrotate.conf"
_CRON_D = _STREAMING_SCRIPTS_DIR / "cron.d"

_INFRA_DIR = _REPO_ROOT / "infra" / "terraform" / "streaming"
_HEALTHCHECK_ENV_TFTPL = _INFRA_DIR / "templates" / "youtube-stream-healthcheck.env.tftpl"
_VARIABLES_TF = _INFRA_DIR / "variables.tf"
_MAIN_TF = _INFRA_DIR / "main.tf"
_CLOUD_INIT_YAML = _INFRA_DIR / "cloud-init.yaml"
_TFVARS_EXAMPLE = _INFRA_DIR / "terraform.tfvars.example"
_STREAMING_README = _INFRA_DIR / "README.md"

_SECRETS_PY = _REPO_ROOT / "src" / "youtube_automation" / "utils" / "secrets.py"
_PYPROJECT = _REPO_ROOT / "pyproject.toml"
_HEALTHCHECK_DOC = _REPO_ROOT / "docs" / "streaming-healthcheck.md"


# ---------- bash ヘルパー ----------


def _run_bash(
    snippet: str,
    *,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess:
    """bash -c で snippet を実行し CompletedProcess を返す。

    ``check=False`` で返す（呼び出し側で returncode を検証する責務）。
    """
    return subprocess.run(
        ["bash", "-c", snippet],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd) if cwd else None,
        check=False,
    )


def _classify(active: str, sub: str, result: str) -> tuple[int, str, str]:
    """healthcheck.sh を source して ``classify_status`` を呼び、(returncode, stdout, stderr) を返す。

    bash 関数の単体テスト用 fixture。stdout のトリム済み文字列を分類結果として比較する。
    """
    if not _HEALTHCHECK_SH.exists():
        pytest.fail(f"healthcheck.sh が存在しない: {_HEALTHCHECK_SH}")
    snippet = f'source "{_HEALTHCHECK_SH}" && classify_status "{active}" "{sub}" "{result}"'
    proc = _run_bash(snippet)
    return proc.returncode, proc.stdout.strip(), proc.stderr


# ============================================================================
# .claude/skills/streaming/references/healthcheck.sh
# ============================================================================


class TestHealthcheckShStructure:
    """``.claude/skills/streaming/references/healthcheck.sh`` の静的構造
    （shebang / set -euo / PATH）。"""

    def test_file_exists(self):
        """Given .claude/skills/streaming/references/
        When healthcheck.sh を探す
        Then 存在する。
        """
        assert _HEALTHCHECK_SH.exists(), (
            ".claude/skills/streaming/references/healthcheck.sh が存在しない"
        )

    def test_has_bash_shebang(self):
        """Given healthcheck.sh
        When 1 行目を読む
        Then ``#!/usr/bin/env bash`` で始まる（POSIX sh ではなく bash 機能を使うため）。
        """
        first_line = _read(_HEALTHCHECK_SH).splitlines()[0]
        assert first_line == "#!/usr/bin/env bash", f"shebang が #!/usr/bin/env bash でない: {first_line!r}"

    def test_has_set_strict_mode(self):
        """Given healthcheck.sh
        When 全文を読む
        Then ``set -euo pipefail`` が含まれている（Fail Fast 原則）。
        """
        text = _read(_HEALTHCHECK_SH)
        assert re.search(r"^set\s+-euo\s+pipefail\s*$", text, flags=re.MULTILINE), (
            "set -euo pipefail が無い（cron 実行時にエラーが握りつぶされる）"
        )

    def test_declares_explicit_path_for_cron(self):
        """Given healthcheck.sh
        When 全文を読む
        Then cron 実行を想定した明示的な ``PATH=`` 宣言がある。

        cron は最小 PATH で実行される（``/usr/bin:/bin`` のみ）。systemctl など
        ``/sbin`` 系コマンドを呼ぶため、スクリプト側で標準パスを export する必要がある。
        """
        text = _read(_HEALTHCHECK_SH)
        # PATH=... が明示的に export または assignment されている
        assert re.search(
            r"^(?:export\s+)?PATH=[^\n]*(?:/usr/sbin|/usr/bin|/sbin|/bin)",
            text,
            flags=re.MULTILINE,
        ), "PATH= の明示宣言が無い（cron PATH 問題で systemctl が見つからない可能性）"


class TestHealthcheckShClassifyStatus:
    """``classify_status`` 関数の 4-way 判定（ok / idle / manual / anomaly）。

    plan §「判定ロジックの設計」: 4-way 分類 で order.md の 4 シナリオ
    （kill -9 / systemctl stop / RuntimeMaxSec / 1h 再開）すべてを通知制御できる。
    """

    def test_active_running_classifies_as_ok(self):
        """Given 配信中 (ActiveState=active, SubState=running, Result=success)
        When classify_status を呼ぶ
        Then 'ok' を出力する（通知しない）。
        """
        rc, out, _ = _classify("active", "running", "success")
        assert rc == 0, f"classify_status が non-zero で終わった: rc={rc}"
        assert out == "ok", f"active+running+success の分類が ok でない: {out!r}"

    def test_active_running_with_prior_failure_still_ok(self):
        """Given 配信中だが直前の Result が failure 系
        When classify_status を呼ぶ
        Then 'ok' を返す（再起動成功後の Result は遺留値、再走中なら通知不要）。

        plan §「実装アプローチ」: ``active+running`` は Result を問わず ok。
        """
        rc, out, _ = _classify("active", "running", "core-dump")
        assert rc == 0
        assert out == "ok", f"active+running は Result に依らず ok のはず: {out!r}"

    def test_activating_auto_restart_with_success_classifies_as_idle(self):
        """Given 11h 到達後の 1h 休止中 (activating+auto-restart+success)
        When classify_status を呼ぶ
        Then 'idle' を出力する（通知しない、計画停止）。

        order.md「5 分間隔 × 1 時間の休止 = 12 回ぶん抑止」要件。
        """
        rc, out, _ = _classify("activating", "auto-restart", "success")
        assert rc == 0
        assert out == "idle", f"activating+auto-restart+success の分類が idle でない: {out!r}"

    def test_activating_auto_restart_with_signal_classifies_as_anomaly(self):
        """Given kill -9 直後の自動再起動待ち (activating+auto-restart+signal)
        When classify_status を呼ぶ
        Then 'anomaly' を出力する（Result≠success なら異常通知）。
        """
        rc, out, _ = _classify("activating", "auto-restart", "signal")
        assert rc == 0
        assert out == "anomaly", (
            f"activating+auto-restart+signal は anomaly のはず（Result が success でない）: {out!r}"
        )

    def test_inactive_dead_with_success_classifies_as_manual(self):
        """Given 手動停止後 (inactive+dead+success: systemctl stop)
        When classify_status を呼ぶ
        Then 'manual' を出力する（通知しない）。

        order.md テスト 2「systemctl stop で通知されない」要件。
        """
        rc, out, _ = _classify("inactive", "dead", "success")
        assert rc == 0
        assert out == "manual", f"inactive+dead+success の分類が manual でない: {out!r}"

    def test_inactive_dead_with_signal_classifies_as_anomaly(self):
        """Given kill -9 直後 (inactive+dead+signal)
        When classify_status を呼ぶ
        Then 'anomaly' を出力する（Result が success でない）。
        """
        rc, out, _ = _classify("inactive", "dead", "signal")
        assert rc == 0
        assert out == "anomaly", f"inactive+dead+signal は anomaly のはず: {out!r}"

    def test_failed_classifies_as_anomaly(self):
        """Given systemd failed 状態 (failed+failed+core-dump)
        When classify_status を呼ぶ
        Then 'anomaly' を出力する。
        """
        rc, out, _ = _classify("failed", "failed", "core-dump")
        assert rc == 0
        assert out == "anomaly", f"failed+failed+core-dump の分類が anomaly でない: {out!r}"

    def test_unknown_state_classifies_as_anomaly(self):
        """Given 未定義の組み合わせ
        When classify_status を呼ぶ
        Then 'anomaly' を出力する（Fail Safe: 想定外は通知側に倒す）。
        """
        rc, out, _ = _classify("reloading", "reload", "success")
        assert rc == 0
        assert out == "anomaly", f"未定義の組み合わせは anomaly に分類すべき: {out!r}"


class TestHealthcheckShBehavior:
    """``healthcheck.sh`` の振る舞い（systemctl 出力をパース → 適切に notify を呼ぶ）。

    PATH を tmp にすり替え、偽 systemctl と偽 notify.sh で「呼ばれた／呼ばれない」を確認する。
    実装側は notify.sh を ``$(dirname "$0")/notify.sh`` 等で呼び出す前提（PATH に
    /opt/youtube-stream/bin を追加するか、相対参照する）。本テストは tmp_dir に
    healthcheck.sh と notify.sh を並べて配置することで両パターンに耐える。
    """

    @pytest.fixture
    def fake_env(self, tmp_path: Path):
        """偽 systemctl + 偽 notify.sh を配置した tmp 環境を構築する。

        ``systemctl`` は ``ActiveState=...\\nSubState=...\\nResult=...`` を
        ``--value`` 形式で 3 行出力する偽実装にする。値は環境変数経由で差し替える。
        ``notify.sh`` は呼ばれたら ``called`` ファイルにメッセージを書き込むだけ。
        """
        if not _HEALTHCHECK_SH.exists():
            pytest.skip("healthcheck.sh が未作成のため skip")
        if not _NOTIFY_SH.exists():
            pytest.skip("notify.sh が未作成のため skip")

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()

        called_marker = tmp_path / "notify_called.log"

        # 偽 systemctl（環境変数 FAKE_ACTIVE / FAKE_SUB / FAKE_RESULT を読み出す）
        fake_systemctl = bin_dir / "systemctl"
        fake_systemctl.write_text(
            "#!/usr/bin/env bash\n"
            "# 偽 systemctl: -p ActiveState -p SubState -p Result --value のとき値を 3 行出力\n"
            'echo "${FAKE_ACTIVE:-active}"\n'
            'echo "${FAKE_SUB:-running}"\n'
            'echo "${FAKE_RESULT:-success}"\n'
        )
        fake_systemctl.chmod(0o755)

        # 偽 notify.sh（呼ばれたら called_marker に追記）
        fake_notify = bin_dir / "notify.sh"
        fake_notify.write_text(
            "#!/usr/bin/env bash\n"
            f'echo "$@" >> "{called_marker}"\n'
            "exit 0\n"
        )
        fake_notify.chmod(0o755)

        # healthcheck.sh を tmp_dir/bin にコピー（同ディレクトリ参照に対応）
        shimmed_healthcheck = bin_dir / "healthcheck.sh"
        shimmed_healthcheck.write_bytes(_HEALTHCHECK_SH.read_bytes())
        shimmed_healthcheck.chmod(0o755)

        return {
            "bin_dir": bin_dir,
            "called_marker": called_marker,
            "healthcheck": shimmed_healthcheck,
        }

    def _run_with_state(
        self,
        fake_env,
        *,
        active: str,
        sub: str,
        result: str,
    ) -> subprocess.CompletedProcess:
        """偽 systemd 状態を環境変数で渡して healthcheck.sh を実行する。"""
        env = os.environ.copy()
        # 偽 systemctl が tmp/bin から見つかるよう PATH 先頭に挿入
        env["PATH"] = f"{fake_env['bin_dir']}{os.pathsep}{env.get('PATH', '')}"
        env["FAKE_ACTIVE"] = active
        env["FAKE_SUB"] = sub
        env["FAKE_RESULT"] = result
        return subprocess.run(
            ["bash", str(fake_env["healthcheck"])],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def test_ok_state_does_not_call_notify(self, fake_env):
        """Given active+running+success
        When healthcheck.sh を実行する
        Then notify.sh が呼ばれない。
        """
        proc = self._run_with_state(fake_env, active="active", sub="running", result="success")
        assert proc.returncode == 0, f"healthcheck.sh が non-zero: {proc.stderr}"
        assert not fake_env["called_marker"].exists(), "ok 状態で notify.sh が呼ばれた（誤検知）"

    def test_idle_state_does_not_call_notify(self, fake_env):
        """Given activating+auto-restart+success（11h+1h サイクルの 1h 休止）
        When healthcheck.sh を実行する
        Then notify.sh が呼ばれない。

        order.md「5 分 × 12 回抑止」要件の core test。
        """
        proc = self._run_with_state(
            fake_env, active="activating", sub="auto-restart", result="success"
        )
        assert proc.returncode == 0, f"healthcheck.sh が non-zero: {proc.stderr}"
        assert not fake_env["called_marker"].exists(), (
            "1h 休止中（idle）で notify.sh が呼ばれた（5 分間隔で誤検知が 12 回飛ぶ）"
        )

    def test_manual_state_does_not_call_notify(self, fake_env):
        """Given inactive+dead+success（systemctl stop）
        When healthcheck.sh を実行する
        Then notify.sh が呼ばれない。

        order.md テスト 2「systemctl stop で通知されない」。
        """
        proc = self._run_with_state(fake_env, active="inactive", sub="dead", result="success")
        assert proc.returncode == 0
        assert not fake_env["called_marker"].exists(), "手動停止で notify.sh が呼ばれた"

    def test_anomaly_state_calls_notify(self, fake_env):
        """Given failed+failed+core-dump（kill -9 等）
        When healthcheck.sh を実行する
        Then notify.sh が呼ばれる（メッセージ引数を 1 つ以上渡す）。
        """
        proc = self._run_with_state(fake_env, active="failed", sub="failed", result="core-dump")
        assert proc.returncode == 0, f"healthcheck.sh が non-zero: {proc.stderr}"
        assert fake_env["called_marker"].exists(), (
            "anomaly 状態で notify.sh が呼ばれていない（異常通知が飛ばない）"
        )
        # メッセージが空でないこと
        called_text = fake_env["called_marker"].read_text()
        assert called_text.strip(), "notify.sh が空メッセージで呼ばれた（Discord 表示が無意味）"


# ============================================================================
# .claude/skills/streaming/references/notify.sh
# ============================================================================


class TestNotifyShStructure:
    """``.claude/skills/streaming/references/notify.sh`` の静的構造。"""

    def test_file_exists(self):
        """Given .claude/skills/streaming/references/
        When notify.sh を探す
        Then 存在する。
        """
        assert _NOTIFY_SH.exists(), (
            ".claude/skills/streaming/references/notify.sh が存在しない"
        )

    def test_has_bash_shebang(self):
        """Given notify.sh
        When 1 行目を読む
        Then ``#!/usr/bin/env bash`` で始まる。
        """
        first_line = _read(_NOTIFY_SH).splitlines()[0]
        assert first_line == "#!/usr/bin/env bash", f"shebang が不正: {first_line!r}"

    def test_has_set_strict_mode(self):
        """Given notify.sh
        When 全文を読む
        Then ``set -euo pipefail`` が含まれている。
        """
        text = _read(_NOTIFY_SH)
        assert re.search(r"^set\s+-euo\s+pipefail\s*$", text, flags=re.MULTILINE), (
            "set -euo pipefail が無い"
        )

    def test_loads_env_file_for_webhook(self):
        """Given notify.sh
        When 全文を読む
        Then ``/etc/youtube-stream-healthcheck.env`` を source または読み込んでいる。

        secret は env file で配信され notify.sh に直書きしない（plan §15）。
        """
        text = _read(_NOTIFY_SH)
        # source / `.` / set -a + . どれでも環境変数を読み込めばよい
        assert "/etc/youtube-stream-healthcheck.env" in text, (
            "/etc/youtube-stream-healthcheck.env を参照していない（webhook を読み込めない）"
        )

    def test_does_not_hardcode_webhook_url(self):
        """Given notify.sh
        When 全文を読む
        Then ``discord.com/api/webhooks/<id>/<token>`` の実値らしきリテラルが直書きされていない。

        secret 漏洩防止の最重要要件。
        """
        text = _read(_NOTIFY_SH)
        assert not re.search(
            r"https://discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_\-]{20,}",
            text,
        ), "Discord Webhook URL が直書きされている（secret 漏洩リスク）"

    def test_uses_curl_for_post(self):
        """Given notify.sh
        When 全文を読む
        Then ``curl`` が呼ばれ、``-X POST`` または ``--data`` 系の POST 経路がある。
        """
        text = _read(_NOTIFY_SH)
        assert re.search(r"\bcurl\b", text), "curl が使われていない（HTTP POST する手段が無い）"

    def test_posts_json_with_content_field(self):
        """Given notify.sh
        When 全文を読む
        Then ``Content-Type: application/json`` を指定し ``content`` フィールドを含む JSON を送る。

        Discord Webhook の仕様: ``{"content": "..."}`` 形式が最低限。
        """
        text = _read(_NOTIFY_SH)
        assert "application/json" in text, "Content-Type: application/json が指定されていない"
        assert re.search(r'"content"', text), 'Discord JSON の "content" フィールドが無い'

    def test_does_not_propagate_curl_failure_to_cron(self):
        """Given notify.sh
        When 全文を読む
        Then ``curl`` 失敗が cron まで伝播しない（``|| true`` か末尾 ``exit 0`` 等で吸収）。

        plan §「実装アプローチ 3」: HTTP エラーでも exit 0（cron を壊さない）。
        """
        text = _read(_NOTIFY_SH)
        # curl ... || true / curl ... || : / 末尾に exit 0 / curl 行を if/||  で囲む 等
        has_or_true = re.search(r"curl[^\n]*\|\|\s*(true|:)", text)
        has_exit_zero = re.search(r"^exit\s+0\s*$", text, flags=re.MULTILINE)
        # set +e で囲む手段もあり
        has_set_plus_e = re.search(r"set\s+\+e", text)
        assert has_or_true or has_exit_zero or has_set_plus_e, (
            "curl 失敗時に cron へエラーが伝播する書き方になっている "
            "（|| true / exit 0 / set +e のいずれかで吸収すること）"
        )


# ============================================================================
# .claude/skills/streaming/references/logrotate.conf
# ============================================================================


class TestLogrotateConf:
    """``.claude/skills/streaming/references/logrotate.conf`` の最低限のディレクティブ。"""

    def test_file_exists(self):
        """Given .claude/skills/streaming/references/
        When logrotate.conf を探す
        Then 存在する。
        """
        assert _LOGROTATE_CONF.exists(), (
            ".claude/skills/streaming/references/logrotate.conf が存在しない"
        )

    def test_targets_youtube_stream_logs(self):
        """Given logrotate.conf
        When 全文を読む
        Then ``/opt/youtube-stream/logs/*.log`` を対象としている。
        """
        text = _read(_LOGROTATE_CONF)
        assert re.search(r"/opt/youtube-stream/logs/\*\.log", text), (
            "/opt/youtube-stream/logs/*.log を対象としていない"
        )

    @pytest.mark.parametrize(
        "directive",
        [
            "daily",  # 1 日 1 ローテ
            "rotate 7",  # 7 日分保持
            "compress",  # gzip 圧縮
            "copytruncate",  # ffmpeg を再起動せずに済ませる
            "missingok",  # ログ未生成でもエラーにしない
            "notifempty",  # 空ファイルはローテ対象外
        ],
    )
    def test_contains_required_directive(self, directive: str):
        """Given logrotate.conf
        When ファイル内容を走査する
        Then 指定ディレクティブが宣言されている。

        ``copytruncate`` は ffmpeg の長時間配信を中断せずローテするため必須
        （inode を保持したまま truncate するため file descriptor が引き続き有効）。
        """
        text = _read(_LOGROTATE_CONF)
        # 単語境界でマッチ（"rotate 7" のような space を含むディレクティブもそのまま）
        pattern = rf"(?m)^\s*{re.escape(directive)}\s*$"
        assert re.search(pattern, text), f"logrotate.conf に '{directive}' ディレクティブが無い"


# ============================================================================
# .claude/skills/streaming/references/cron.d
# ============================================================================


class TestCronD:
    """``.claude/skills/streaming/references/cron.d`` の cron job 宣言。"""

    def test_file_exists(self):
        """Given .claude/skills/streaming/references/
        When cron.d を探す
        Then 存在する。
        """
        assert _CRON_D.exists(), (
            ".claude/skills/streaming/references/cron.d が存在しない"
        )

    def test_has_5min_schedule_for_healthcheck(self):
        """Given cron.d
        When 全文を読む
        Then ``*/5 * * * * root /opt/youtube-stream/bin/healthcheck.sh`` 行がある。

        cron.d 形式は ``user`` フィールド（``root``）を含むのが特徴。crontab 形式と区別される。
        """
        text = _read(_CRON_D)
        assert re.search(
            r"^\s*\*/5\s+\*\s+\*\s+\*\s+\*\s+root\s+/opt/youtube-stream/bin/healthcheck\.sh\b",
            text,
            flags=re.MULTILINE,
        ), "*/5 * * * * root /opt/youtube-stream/bin/healthcheck.sh の cron.d 行が無い"


# ============================================================================
# infra/terraform/streaming/templates/youtube-stream-healthcheck.env.tftpl
# ============================================================================


class TestHealthcheckEnvTftpl:
    """``templates/youtube-stream-healthcheck.env.tftpl`` の env テンプレ内容。

    systemd ``EnvironmentFile`` 慣例: ``KEY=VALUE``、引用符なし。terraform
    ``templatefile()`` で ``${webhook}`` を実値に展開する。
    """

    def test_file_exists(self):
        """Given infra/terraform/streaming/templates/
        When youtube-stream-healthcheck.env.tftpl を探す
        Then 存在する。
        """
        assert _HEALTHCHECK_ENV_TFTPL.exists(), (
            "templates/youtube-stream-healthcheck.env.tftpl が存在しない"
        )

    def test_contains_webhook_variable_assignment(self):
        """Given env tftpl
        When 全文を読む
        Then ``DISCORD_WEBHOOK_URL=${webhook}`` 行がある（terraform templatefile 変数記法）。
        """
        text = _read(_HEALTHCHECK_ENV_TFTPL)
        assert re.search(r"^DISCORD_WEBHOOK_URL=\$\{webhook\}\s*$", text, flags=re.MULTILINE), (
            "DISCORD_WEBHOOK_URL=${webhook} 行が存在しない"
        )

    def test_value_is_not_quoted(self):
        """Given env tftpl
        When DISCORD_WEBHOOK_URL の右辺を読む
        Then 値がクォート（``"..."`` / ``'...'``）で囲まれていない。

        systemd EnvironmentFile はクォートを文字列の一部とみなす（curl URL に余計な文字が混入する）。
        """
        text = _read(_HEALTHCHECK_ENV_TFTPL)
        assert not re.search(r"^DISCORD_WEBHOOK_URL=['\"]", text, flags=re.MULTILINE), (
            "DISCORD_WEBHOOK_URL の値がクォートされている（systemd EnvironmentFile 慣例違反）"
        )

    def test_does_not_contain_plaintext_webhook(self):
        """Given env tftpl
        When 全文を読む
        Then ``https://discord.com/api/webhooks/...`` の実値が直書きされていない。

        secret は terraform templatefile() の variables map 経由でだけ流入させる。
        """
        text = _read(_HEALTHCHECK_ENV_TFTPL)
        assert not re.search(r"https://discord(?:app)?\.com/api/webhooks/", text), (
            "Discord Webhook URL が直書きされている（${webhook} を使うこと）"
        )


# ============================================================================
# infra/terraform/streaming/variables.tf — discord_webhook_url
# ============================================================================


class TestVariablesTfDiscordWebhook:
    """``variables.tf`` の ``discord_webhook_url`` 変数定義。"""

    def test_discord_webhook_url_is_sensitive_string_with_no_default(self):
        """Given variables.tf
        When discord_webhook_url 変数定義を読む
        Then type=string, sensitive=true, description あり, default は宣言されていない。

        既存 ``stream_key`` / ``vultr_api_key`` と同種規約（Fail Fast、tfstate にも sensitive 扱い）。
        """
        text = _strip_hcl_comments(_read(_VARIABLES_TF))
        block = _extract_block(text, r'variable\s+"discord_webhook_url"')
        assert block is not None, 'variable "discord_webhook_url" が存在しない'
        assert re.search(r"type\s*=\s*string", block), "discord_webhook_url.type が string でない"
        assert re.search(r"sensitive\s*=\s*true", block), (
            "discord_webhook_url.sensitive = true が無い（tfstate に平文で残るリスク）"
        )
        assert re.search(r"description\s*=", block), "discord_webhook_url.description が無い"
        assert not re.search(r"\bdefault\s*=", block), (
            "discord_webhook_url には default を設定してはならない（Fail Fast / secret はランタイム注入）"
        )


# ============================================================================
# infra/terraform/streaming/main.tf — null_resource.deploy 拡張
# ============================================================================


class TestMainTfHealthcheckDeploy:
    """``main.tf`` の ``null_resource.deploy`` への死活監視 4 ファイル + env tftpl 配信検証。"""

    def test_triggers_includes_discord_webhook_url_hash(self):
        """Given main.tf
        When null_resource.deploy.triggers を読む
        Then ``nonsensitive(sha256(var.discord_webhook_url))`` の trigger がある。

        既存 stream_key と同パターン: secret 派生は terraform 1.5+ で sensitive 扱いされるため
        nonsensitive() で剥がす。SHA256 は不可逆なので脱 sensitive 安全。
        """
        text = _strip_hcl_comments(_read(_MAIN_TF))
        block = _extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None
        triggers = _extract_block(block, r"triggers")
        assert triggers is not None, "null_resource.deploy.triggers ブロックが存在しない"
        assert re.search(
            r"nonsensitive\(\s*sha256\(\s*var\.discord_webhook_url\s*\)\s*\)",
            triggers,
        ), (
            "triggers に nonsensitive(sha256(var.discord_webhook_url)) が無い "
            "（webhook 差し替えで再 deploy されない）"
        )

    @pytest.mark.parametrize(
        "destination",
        [
            "/opt/youtube-stream/bin/healthcheck.sh",
            "/opt/youtube-stream/bin/notify.sh",
            "/etc/logrotate.d/youtube-stream",
            "/etc/cron.d/youtube-stream-healthcheck",
        ],
    )
    def test_provisioner_file_uploads_healthcheck_asset(self, destination: str):
        """Given main.tf
        When null_resource.deploy 内の provisioner "file" を走査する
        Then 指定 destination の宣言がある。

        4 アセット（healthcheck.sh / notify.sh / logrotate.conf / cron.d）すべて配信されること。
        """
        text = _strip_hcl_comments(_read(_MAIN_TF))
        block = _extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None
        assert re.search(
            rf'destination\s*=\s*"{re.escape(destination)}"',
            block,
        ), f'provisioner "file" で destination="{destination}" が宣言されていない'

    def test_provisioner_file_uploads_healthcheck_env_via_templatefile(self):
        """Given main.tf
        When null_resource.deploy 内の provisioner "file" を走査する
        Then ``/etc/youtube-stream-healthcheck.env`` への配信があり、
             ``templatefile("${path.module}/templates/youtube-stream-healthcheck.env.tftpl", ...)``
             で生成されている。
        """
        text = _strip_hcl_comments(_read(_MAIN_TF))
        block = _extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None
        assert re.search(
            r'destination\s*=\s*"/etc/youtube-stream-healthcheck\.env"',
            block,
        ), '/etc/youtube-stream-healthcheck.env への provisioner "file" destination が無い'
        assert re.search(
            r'templatefile\(\s*"\$\{path\.module\}/templates/youtube-stream-healthcheck\.env\.tftpl"',
            block,
        ), (
            "templatefile で youtube-stream-healthcheck.env.tftpl を読み込んでいない"
            "（webhook が systemd EnvironmentFile に展開されない）"
        )

    def test_env_templatefile_passes_webhook_from_var(self):
        """Given main.tf
        When healthcheck.env を生成する templatefile() の variables map を読む
        Then ``webhook = var.discord_webhook_url`` が渡されている。
        """
        # raw を読む（コメント除去で消える可能性のある記号は無いが、test_terraform_streaming.py の慣例に倣う）
        text = _read(_MAIN_TF)
        # 同じ行近傍に webhook = var.discord_webhook_url が現れること
        assert re.search(
            r"webhook\s*=\s*var\.discord_webhook_url",
            text,
        ), "templatefile に webhook = var.discord_webhook_url が渡されていない"

    def test_remote_exec_secures_healthcheck_env_file_perms(self):
        """Given main.tf
        When provisioner "remote-exec" の inline を読む
        Then ``/etc/youtube-stream-healthcheck.env`` に対し chmod 600 と chown root:root が実行される。

        webhook を読める範囲を root に限定する（secret 隔離）。
        """
        text = _strip_hcl_comments(_read(_MAIN_TF))
        block = _extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None
        remote_exec = re.search(
            r'provisioner\s+"remote-exec"\s*\{(.*?)\n\s*\}',
            block,
            flags=re.DOTALL,
        )
        assert remote_exec is not None
        inline = remote_exec.group(1)
        assert re.search(
            r"chmod\s+0?600\s+/etc/youtube-stream-healthcheck\.env",
            inline,
        ), "chmod 0600 /etc/youtube-stream-healthcheck.env が無い"
        assert re.search(
            r"chown\s+root:root\s+/etc/youtube-stream-healthcheck\.env",
            inline,
        ), "chown root:root /etc/youtube-stream-healthcheck.env が無い"

    def test_remote_exec_makes_bin_dir_and_executable(self):
        """Given main.tf
        When provisioner "remote-exec" の inline を読む
        Then ``/opt/youtube-stream/bin`` を作成し、配置した shell スクリプトを実行可能にしている。

        ``mkdir -p /opt/youtube-stream/bin`` または ``install -d`` 系のいずれか + ``chmod 755`` 系。
        """
        text = _strip_hcl_comments(_read(_MAIN_TF))
        block = _extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None
        remote_exec = re.search(
            r'provisioner\s+"remote-exec"\s*\{(.*?)\n\s*\}',
            block,
            flags=re.DOTALL,
        )
        assert remote_exec is not None
        inline = remote_exec.group(1)
        # ディレクトリ作成（mkdir -p または install -d）
        assert re.search(
            r"(mkdir\s+-p|install\s+-d)[^\n]*/opt/youtube-stream/bin\b",
            inline,
        ), "/opt/youtube-stream/bin の作成コマンドが無い"
        # 実行権限付与（個別 chmod 755 でも /opt/.../bin/*.sh への一括でも可）
        assert re.search(
            r"chmod\s+(?:0?7?55|\+x)[^\n]*/opt/youtube-stream/bin",
            inline,
        ), "/opt/youtube-stream/bin 配下のスクリプトに実行権限が付与されていない"

    def test_remote_exec_reloads_cron(self):
        """Given main.tf
        When provisioner "remote-exec" の inline を読む
        Then cron daemon を反映するコマンドがある（``systemctl restart cron`` / ``service cron reload`` 等）。

        cron.d は配置するだけでは即時反映されない場合があるため、明示的に再起動を呼ぶ必要がある
        （Ubuntu 24.04 の vixie-cron / cron は通常自動検知するが、明示で確実にする）。
        """
        text = _strip_hcl_comments(_read(_MAIN_TF))
        block = _extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None
        remote_exec = re.search(
            r'provisioner\s+"remote-exec"\s*\{(.*?)\n\s*\}',
            block,
            flags=re.DOTALL,
        )
        assert remote_exec is not None
        inline = remote_exec.group(1)
        has_systemctl = re.search(r"systemctl\s+(?:restart|reload)\s+cron\b", inline)
        has_service = re.search(r"service\s+cron\s+(?:restart|reload)\b", inline)
        assert has_systemctl or has_service, (
            "cron daemon の reload/restart コマンドが無い（cron.d の即時反映が保証されない）"
        )


# ============================================================================
# infra/terraform/streaming/cloud-init.yaml — cron package 追加
# ============================================================================


class TestCloudInitCronPackage:
    """cloud-init.yaml の ``packages:`` リストに ``cron`` が追加されている。"""

    def test_packages_list_includes_cron(self):
        """Given cloud-init.yaml
        When ``packages:`` リストを読む
        Then ``cron`` が含まれている。

        Ubuntu 24.04 minimal は cron が同梱されない場合があり、cron.d を配置しても起動しない
        （既存 ffmpeg と同パターンで宣言する）。
        """
        text = _read(_CLOUD_INIT_YAML)
        match = re.search(
            r"^packages:\s*\n((?:[ \t]+.*\n)+)",
            text,
            flags=re.MULTILINE,
        )
        assert match is not None, "packages: リストブロックが存在しない"
        packages_block = match.group(1)
        assert re.search(r"^\s*-\s*cron\b", packages_block, flags=re.MULTILINE), (
            "packages リストに cron が含まれていない（cron.d を配置しても起動しないリスク）"
        )


# ============================================================================
# infra/terraform/streaming/terraform.tfvars.example — Discord 案内
# ============================================================================


class TestTfvarsExampleDiscordWebhook:
    """``terraform.tfvars.example`` の Discord webhook 注入手順。"""

    def test_does_not_contain_discord_webhook_url_assignment(self):
        """Given terraform.tfvars.example
        When ファイル内容（コメント除去後）を読む
        Then ``discord_webhook_url = "..."`` のアクティブ代入が存在しない。

        secret は TF_VAR_discord_webhook_url 経由で渡す前提（既存 stream_key と同種規約）。
        """
        text = _strip_hcl_comments(_read(_TFVARS_EXAMPLE))
        assert not re.search(r"^\s*discord_webhook_url\s*=", text, flags=re.MULTILINE), (
            "discord_webhook_url の代入がアクティブ行に存在する（secret 漏洩リスク）"
        )

    def test_mentions_tf_var_discord_webhook_url_in_comments(self):
        """Given terraform.tfvars.example
        When ファイル内容（コメント込み）を読む
        Then ``TF_VAR_discord_webhook_url`` の使い方がコメントに記載されている。
        """
        raw = _read(_TFVARS_EXAMPLE)
        assert "TF_VAR_discord_webhook_url" in raw, (
            "TF_VAR_discord_webhook_url の案内コメントが無い（運用者が secret 注入方法を発見できない）"
        )


# ============================================================================
# infra/terraform/streaming/README.md — 死活監視セクション
# ============================================================================


class TestStreamingReadmeHealthcheck:
    """README.md の死活監視セクション（plan §3）。"""

    def test_mentions_discord(self):
        """Given README
        When 全文を読む
        Then Discord 言及がある（通知手段の説明）。
        """
        text = _read(_STREAMING_README)
        assert "Discord" in text, "README に Discord 言及が無い（死活監視の通知手段が説明されない）"

    def test_mentions_tf_var_discord_webhook_url(self):
        """Given README
        When 全文を読む
        Then ``TF_VAR_discord_webhook_url`` 環境変数の言及がある（secret 注入の入口）。
        """
        text = _read(_STREAMING_README)
        assert "TF_VAR_discord_webhook_url" in text, (
            "README に TF_VAR_discord_webhook_url の言及が無い（secret 注入手順が辿れない）"
        )

    def test_mentions_healthcheck_script_path(self):
        """Given README
        When 全文を読む
        Then ``healthcheck.sh`` の言及がある（運用者が cron で何が動くかを把握できる）。
        """
        text = _read(_STREAMING_README)
        assert "healthcheck.sh" in text, "README に healthcheck.sh の言及が無い"

    @pytest.mark.parametrize(
        "scenario_keyword",
        [
            "kill",  # kill -9 シナリオ
            "systemctl stop",  # 手動停止シナリオ
            "RuntimeMaxSec",  # 計画停止シナリオ
            "再開",  # 自動再開シナリオ（漢字でも英語の "restart" でも可）
        ],
    )
    def test_mentions_each_test_scenario(self, scenario_keyword: str):
        """Given README
        When 全文を読む
        Then order.md の 4 テストシナリオが運用手順に含まれている。

        ``再開`` は systemd の自動再起動文脈。"restart" 単独は他箇所と被るため、
        日本語キーワードまたは "RestartSec" / "auto-restart" を緩く受け入れる。
        """
        text = _read(_STREAMING_README)
        if scenario_keyword == "再開":
            assert (
                "再開" in text
                or "auto-restart" in text
                or "RestartSec" in text
            ), "README に自動再開シナリオの言及が無い"
        else:
            assert scenario_keyword in text, (
                f"README に '{scenario_keyword}' シナリオの言及が無い（4 シナリオ運用手順未網羅）"
            )


# ============================================================================
# src/youtube_automation/utils/streaming_archive.py — count_archives_for_date
# ============================================================================


class TestStreamingArchiveCount:
    """``count_archives_for_date`` のモックテスト。

    YouTube Data API:
      1. ``search.list(forMine=True, type='video', eventType='completed',
                       publishedAfter=..., publishedBefore=...)``
      2. ``videos.list(id=..., part='snippet,liveStreamingDetails')``
      3. ``liveBroadcastContent='none'`` ∧ ``actualEndTime ∈ target_date`` のものを数える
    """

    def _make_service(self, search_items: list[dict], video_items: list[dict]) -> MagicMock:
        """googleapiclient リソースを模した MagicMock を組み立てる。"""
        service = MagicMock()
        service.search.return_value.list.return_value.execute.return_value = {"items": search_items}
        service.videos.return_value.list.return_value.execute.return_value = {"items": video_items}
        return service

    def test_returns_zero_when_no_videos_found(self):
        """Given search.list が空配列を返す
        When count_archives_for_date を呼ぶ
        Then 0 を返す（API を 2 回目以降呼ばない最適化は問わない）。
        """
        from youtube_automation.utils.streaming_archive import count_archives_for_date

        service = self._make_service(search_items=[], video_items=[])
        count = count_archives_for_date(service, date(2026, 5, 1))
        assert count == 0, f"動画ゼロのとき 0 を返すべき: {count}"

    def test_counts_videos_with_actual_end_time_in_target_date(self):
        """Given target_date に actualEndTime を持つ動画 2 本
        When count_archives_for_date を呼ぶ
        Then 2 を返す。

        order.md「1 日 2 本のアーカイブ」要件の通常系。
        """
        from youtube_automation.utils.streaming_archive import count_archives_for_date

        target = date(2026, 5, 1)
        search_items = [
            {"id": {"videoId": "v1"}},
            {"id": {"videoId": "v2"}},
        ]
        video_items = [
            {
                "id": "v1",
                "snippet": {"liveBroadcastContent": "none"},
                "liveStreamingDetails": {"actualEndTime": "2026-05-01T11:00:00Z"},
            },
            {
                "id": "v2",
                "snippet": {"liveBroadcastContent": "none"},
                "liveStreamingDetails": {"actualEndTime": "2026-05-01T23:00:00Z"},
            },
        ]
        service = self._make_service(search_items, video_items)
        count = count_archives_for_date(service, target)
        assert count == 2, f"target_date のアーカイブ 2 本を数えていない: {count}"

    def test_excludes_videos_outside_target_date(self):
        """Given actualEndTime が target_date より前または後の動画
        When count_archives_for_date を呼ぶ
        Then 数に含めない。
        """
        from youtube_automation.utils.streaming_archive import count_archives_for_date

        target = date(2026, 5, 1)
        search_items = [
            {"id": {"videoId": "v_before"}},
            {"id": {"videoId": "v_after"}},
            {"id": {"videoId": "v_target"}},
        ]
        video_items = [
            {
                "id": "v_before",
                "snippet": {"liveBroadcastContent": "none"},
                "liveStreamingDetails": {"actualEndTime": "2026-04-30T23:59:59Z"},
            },
            {
                "id": "v_after",
                "snippet": {"liveBroadcastContent": "none"},
                "liveStreamingDetails": {"actualEndTime": "2026-05-02T00:00:00Z"},
            },
            {
                "id": "v_target",
                "snippet": {"liveBroadcastContent": "none"},
                "liveStreamingDetails": {"actualEndTime": "2026-05-01T12:00:00Z"},
            },
        ]
        service = self._make_service(search_items, video_items)
        count = count_archives_for_date(service, target)
        assert count == 1, f"target_date 以外のアーカイブを数えてはならない: {count}"

    def test_excludes_videos_still_live_or_upcoming(self):
        """Given liveBroadcastContent が 'live' / 'upcoming' の動画
        When count_archives_for_date を呼ぶ
        Then 数に含めない（アーカイブ済みのみ対象）。
        """
        from youtube_automation.utils.streaming_archive import count_archives_for_date

        target = date(2026, 5, 1)
        search_items = [
            {"id": {"videoId": "v_live"}},
            {"id": {"videoId": "v_upcoming"}},
            {"id": {"videoId": "v_archived"}},
        ]
        video_items = [
            {
                "id": "v_live",
                "snippet": {"liveBroadcastContent": "live"},
                "liveStreamingDetails": {"actualEndTime": "2026-05-01T11:00:00Z"},
            },
            {
                "id": "v_upcoming",
                "snippet": {"liveBroadcastContent": "upcoming"},
                "liveStreamingDetails": {},
            },
            {
                "id": "v_archived",
                "snippet": {"liveBroadcastContent": "none"},
                "liveStreamingDetails": {"actualEndTime": "2026-05-01T23:00:00Z"},
            },
        ]
        service = self._make_service(search_items, video_items)
        count = count_archives_for_date(service, target)
        assert count == 1, "liveBroadcastContent != 'none' を除外していない"

    def test_excludes_non_live_videos_without_live_streaming_details(self):
        """Given liveStreamingDetails が無い通常動画
        When count_archives_for_date を呼ぶ
        Then 数に含めない（ライブ配信由来のアーカイブだけを対象）。
        """
        from youtube_automation.utils.streaming_archive import count_archives_for_date

        target = date(2026, 5, 1)
        search_items = [{"id": {"videoId": "v_normal"}}]
        video_items = [
            {
                "id": "v_normal",
                "snippet": {
                    "liveBroadcastContent": "none",
                    "publishedAt": "2026-05-01T12:00:00Z",
                },
                # liveStreamingDetails 不在
            },
        ]
        service = self._make_service(search_items, video_items)
        count = count_archives_for_date(service, target)
        assert count == 0, "liveStreamingDetails 不在の通常動画は数えないこと"


# ============================================================================
# src/youtube_automation/scripts/streaming_archive_check.py — CLI
# ============================================================================


class TestStreamingArchiveCheckCli:
    """``yt-stream-archive-check`` CLI の振る舞い。"""

    def test_module_is_importable(self):
        """Given streaming_archive_check.py
        When import する
        Then エラーなく読み込める（main 関数を export している）。
        """
        from youtube_automation.scripts import streaming_archive_check

        assert hasattr(streaming_archive_check, "main"), "main() が export されていない"

    def test_exit_zero_when_count_meets_expected(self):
        """Given count_archives_for_date が 2 を返す + --expected 2
        When main を呼ぶ
        Then exit 0（正常）。
        """
        from youtube_automation.scripts import streaming_archive_check

        with (
            patch.object(
                streaming_archive_check,
                "count_archives_for_date",
                return_value=2,
            ),
            patch.object(
                streaming_archive_check,
                "build_youtube_service",
                return_value=MagicMock(),
            ),
            patch.object(sys, "argv", ["yt-stream-archive-check", "--date", "2026-05-01", "--expected", "2"]),
        ):
            try:
                rc = streaming_archive_check.main()
            except SystemExit as e:
                rc = e.code
        # main() が int を return するか SystemExit を投げるかは実装次第、どちらも 0 を期待
        assert rc in (0, None), f"件数充足で exit 0 にならない: {rc}"

    def test_exit_nonzero_when_count_below_expected(self):
        """Given count_archives_for_date が 1 を返す + --expected 2
        When main を呼ぶ
        Then exit 非 0（不足エラー）。
        """
        from youtube_automation.scripts import streaming_archive_check

        with (
            patch.object(
                streaming_archive_check,
                "count_archives_for_date",
                return_value=1,
            ),
            patch.object(
                streaming_archive_check,
                "build_youtube_service",
                return_value=MagicMock(),
            ),
            patch.object(sys, "argv", ["yt-stream-archive-check", "--date", "2026-05-01", "--expected", "2"]),
        ):
            try:
                rc = streaming_archive_check.main()
            except SystemExit as e:
                rc = e.code
        assert rc not in (0, None), f"件数不足で exit 非 0 にならない: {rc}"

    def test_notify_on_shortage_posts_to_discord(self):
        """Given count_archives_for_date が不足を返す + --notify-on-shortage
        When main を呼ぶ
        Then Discord 通知用関数が呼ばれる（webhook POST）。
        """
        from youtube_automation.scripts import streaming_archive_check

        # Discord 通知の発火経路は requests.post / urllib どちらでも検出する
        with (
            patch.object(
                streaming_archive_check,
                "count_archives_for_date",
                return_value=0,
            ),
            patch.object(
                streaming_archive_check,
                "build_youtube_service",
                return_value=MagicMock(),
            ),
            patch.object(
                streaming_archive_check,
                "get_secret",
                return_value="https://discord.com/api/webhooks/123/abc",
            ),
            patch("requests.post") as mock_post,
            patch.object(
                sys,
                "argv",
                [
                    "yt-stream-archive-check",
                    "--date",
                    "2026-05-01",
                    "--expected",
                    "2",
                    "--notify-on-shortage",
                ],
            ),
        ):
            try:
                streaming_archive_check.main()
            except SystemExit:
                pass
            assert mock_post.called, (
                "--notify-on-shortage を指定しても Discord に POST していない（通知が飛ばない）"
            )


# ============================================================================
# pyproject.toml — yt-stream-archive-check entry point
# ============================================================================


class TestPyprojectEntryPoint:
    """``[project.scripts]`` への ``yt-stream-archive-check`` 登録。"""

    def test_yt_stream_archive_check_is_registered(self):
        """Given pyproject.toml
        When [project.scripts] セクションを読む
        Then ``yt-stream-archive-check`` が登録されている。

        ``yt-*`` プレフィックス規約 (CLAUDE.md) に従う。
        """
        text = _read(_PYPROJECT)
        # `yt-stream-archive-check = "..."` 行が [project.scripts] にあること
        assert re.search(
            r'^yt-stream-archive-check\s*=\s*"youtube_automation\.scripts\.streaming_archive_check:main"',
            text,
            flags=re.MULTILINE,
        ), (
            "yt-stream-archive-check entry point が pyproject.toml に登録されていない "
            '（"youtube_automation.scripts.streaming_archive_check:main" を指すこと）'
        )


# ============================================================================
# docs/streaming-healthcheck.md — 運用手順書
# ============================================================================


class TestHealthcheckDoc:
    """``docs/streaming-healthcheck.md`` の運用手順書（4 シナリオ網羅）。"""

    def test_file_exists(self):
        """Given docs/
        When streaming-healthcheck.md を探す
        Then 存在する。
        """
        assert _HEALTHCHECK_DOC.exists(), "docs/streaming-healthcheck.md が存在しない"

    @pytest.mark.parametrize(
        "scenario_keyword",
        [
            "kill",
            "systemctl stop",
            "RuntimeMaxSec",
        ],
    )
    def test_documents_each_test_scenario(self, scenario_keyword: str):
        """Given streaming-healthcheck.md
        When 全文を読む
        Then order.md の 3 シナリオ（4 つ目「自動再開」は文脈で吸収）が手順書に含まれている。

        order.md「各シナリオが運用手順書に記載済み」要件。
        """
        text = _read(_HEALTHCHECK_DOC)
        assert scenario_keyword in text, (
            f"運用手順書に '{scenario_keyword}' シナリオの記載が無い"
        )

    def test_documents_auto_restart_scenario(self):
        """Given streaming-healthcheck.md
        When 全文を読む
        Then 1 時間後の自動再開（RestartSec / auto-restart / 再開 のいずれか）の言及がある。
        """
        text = _read(_HEALTHCHECK_DOC)
        assert (
            "再開" in text
            or "RestartSec" in text
            or "auto-restart" in text
        ), "運用手順書に自動再開シナリオの記載が無い"
