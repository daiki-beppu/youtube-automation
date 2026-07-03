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
3. ``infra/terraform/streaming/templates/youtube-stream-healthcheck.env.tftpl``
     - ``DISCORD_WEBHOOK_URL=${webhook}`` の 1 行
4. ``infra/terraform/streaming/variables.tf``
     - ``discord_webhook_url`` (sensitive=true, default なし)
5. ``infra/terraform/streaming/main.tf``
     - triggers に ``nonsensitive(sha256(var.discord_webhook_url))``
     - provisioner で 4 ファイル + env tftpl を配信
     - remote-exec で chmod / chown / cron 再起動
6. ``infra/terraform/streaming/cloud-init.yaml``
     - ``packages:`` に ``cron`` を追加
7. ``infra/terraform/streaming/terraform.tfvars.example``
     - ``discord_webhook_url`` のアクティブ代入が無い
     - ``TF_VAR_discord_webhook_url`` を案内コメントに含む
8. ``infra/terraform/streaming/README.md``
     - 死活監視セクション / Discord / 4 シナリオ言及
9. ``src/youtube_automation/utils/streaming/daily_archive.py``
     - ``count_archives_for_date`` のモック検証
10. ``src/youtube_automation/scripts/streaming_archive_check.py``
     - argparse / 件数不足時 exit 1 / Discord 通知
11. ``pyproject.toml``
     - ``yt-stream-archive-check`` entry point 登録
12. ``docs/streaming-healthcheck.md``
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

from tests.helpers.hcl import extract_block, read_file, strip_hcl_comments

# ---------- パス定数 ----------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_STREAMING_SCRIPTS_DIR = _REPO_ROOT / ".claude" / "skills" / "streaming" / "references"
_HEALTHCHECK_SH = _STREAMING_SCRIPTS_DIR / "healthcheck.sh"
_NOTIFY_SH = _STREAMING_SCRIPTS_DIR / "notify.sh"

_INFRA_DIR = _REPO_ROOT / "infra" / "terraform" / "streaming"
_HEALTHCHECK_ENV_TFTPL = _INFRA_DIR / "templates" / "youtube-stream-healthcheck.env.tftpl"
_VARIABLES_TF = _INFRA_DIR / "variables.tf"
_MAIN_TF = _INFRA_DIR / "main.tf"
_CLOUD_INIT_YAML = _INFRA_DIR / "cloud-init.yaml"
_TFVARS_EXAMPLE = _INFRA_DIR / "terraform.tfvars.example"
_STREAMING_README = _INFRA_DIR / "README.md"

_INSTALL_ROOT_VAR = r"\$\{var\.install_root\}"

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
        assert _HEALTHCHECK_SH.exists(), ".claude/skills/streaming/references/healthcheck.sh が存在しない"

    def test_has_bash_shebang(self):
        """Given healthcheck.sh
        When 1 行目を読む
        Then ``#!/usr/bin/env bash`` で始まる（POSIX sh ではなく bash 機能を使うため）。
        """
        first_line = read_file(_HEALTHCHECK_SH).splitlines()[0]
        assert first_line == "#!/usr/bin/env bash", f"shebang が #!/usr/bin/env bash でない: {first_line!r}"

    def test_has_set_strict_mode(self):
        """Given healthcheck.sh
        When 全文を読む
        Then ``set -euo pipefail`` が含まれている（Fail Fast 原則）。
        """
        text = read_file(_HEALTHCHECK_SH)
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
        text = read_file(_HEALTHCHECK_SH)
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
        ``KEY=VALUE`` 形式で 3 行出力する偽実装にする（順序非依存パースを反映）。値は環境
        変数経由で差し替える。``notify.sh`` は呼ばれたら ``called`` ファイルにメッセージを
        書き込むだけ。``state_dir`` は ``YT_STREAM_STATE_DIR`` で healthcheck.sh に渡し、
        ``last_status`` ファイルを tmp 配下に閉じ込める。
        """
        if not _HEALTHCHECK_SH.exists():
            pytest.skip("healthcheck.sh が未作成のため skip")
        if not _NOTIFY_SH.exists():
            pytest.skip("notify.sh が未作成のため skip")

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()

        state_dir = tmp_path / "state"

        called_marker = tmp_path / "notify_called.log"

        # 偽 systemctl（環境変数 FAKE_ACTIVE / FAKE_SUB / FAKE_RESULT を読み出す）
        # 順序非依存パースに合わせて KEY=VALUE 形式で出力する。
        fake_systemctl = bin_dir / "systemctl"
        fake_systemctl.write_text(
            "#!/usr/bin/env bash\n"
            "# 偽 systemctl: -p ActiveState -p SubState -p Result のとき KEY=VALUE で 3 行出力\n"
            'echo "ActiveState=${FAKE_ACTIVE:-active}"\n'
            'echo "SubState=${FAKE_SUB:-running}"\n'
            'echo "Result=${FAKE_RESULT:-success}"\n'
        )
        fake_systemctl.chmod(0o755)

        # 偽 notify.sh（呼ばれたら called_marker に追記）
        fake_notify = bin_dir / "notify.sh"
        fake_notify.write_text(f'#!/usr/bin/env bash\necho "$@" >> "{called_marker}"\nexit 0\n')
        fake_notify.chmod(0o755)

        # healthcheck.sh を tmp_dir/bin にコピー（同ディレクトリ参照に対応）
        shimmed_healthcheck = bin_dir / "healthcheck.sh"
        shimmed_healthcheck.write_bytes(_HEALTHCHECK_SH.read_bytes())
        shimmed_healthcheck.chmod(0o755)

        return {
            "bin_dir": bin_dir,
            "called_marker": called_marker,
            "healthcheck": shimmed_healthcheck,
            "state_dir": state_dir,
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
        # last_status を tmp に閉じ込める（本番では /var/lib/youtube-stream/last_status）
        env["YT_STREAM_STATE_DIR"] = str(fake_env["state_dir"])
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
        proc = self._run_with_state(fake_env, active="activating", sub="auto-restart", result="success")
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
        assert fake_env["called_marker"].exists(), "anomaly 状態で notify.sh が呼ばれていない（異常通知が飛ばない）"
        # メッセージが空でないこと
        called_text = fake_env["called_marker"].read_text()
        assert called_text.strip(), "notify.sh が空メッセージで呼ばれた（Discord 表示が無意味）"

    def test_consecutive_anomaly_does_not_renotify(self, fake_env):
        """Given 1 回目で anomaly 通知が発火、last_status に "anomaly" が保存された後
        When 2 回目も anomaly 状態で healthcheck.sh を実行する
        Then notify.sh は 2 回目では呼ばれない（連打防止）。

        order.md「anomaly → anomaly は無音（連打防止）」要件の core test。
        """
        # 1 回目: unknown → anomaly で通知
        self._run_with_state(fake_env, active="failed", sub="failed", result="core-dump")
        assert fake_env["called_marker"].exists(), "1 回目の anomaly で notify が呼ばれていない"
        first_call_size = fake_env["called_marker"].stat().st_size

        # 2 回目: anomaly → anomaly で無音
        proc = self._run_with_state(fake_env, active="failed", sub="failed", result="core-dump")
        assert proc.returncode == 0
        second_call_size = fake_env["called_marker"].stat().st_size
        assert second_call_size == first_call_size, "anomaly → anomaly でも notify が再度呼ばれた（5 分ごと連打）"

    def test_recovered_from_anomaly_calls_notify(self, fake_env):
        """Given 1 回目で anomaly 状態（last_status に "anomaly" が保存される）
        When 2 回目に ok 状態（active+running+success）で healthcheck.sh を実行する
        Then notify.sh が呼ばれ、メッセージに "recovered" が含まれる。

        order.md「anomaly → ok/idle/manual の遷移で "recovered: <new>" 通知」要件。
        """
        # 1 回目: anomaly
        self._run_with_state(fake_env, active="failed", sub="failed", result="core-dump")
        first_text = fake_env["called_marker"].read_text()

        # 2 回目: anomaly → ok で recovered 通知
        proc = self._run_with_state(fake_env, active="active", sub="running", result="success")
        assert proc.returncode == 0
        assert fake_env["called_marker"].exists(), "anomaly → ok の復帰で notify が呼ばれていない（recovered 通知欠損）"
        full_text = fake_env["called_marker"].read_text()
        new_text = full_text[len(first_text) :]
        assert "recovered" in new_text, f"recovered メッセージが notify に渡されていない: {new_text!r}"
        assert "ok" in new_text, f"recovered メッセージに復帰先 'ok' が含まれない: {new_text!r}"

    def test_initial_ok_does_not_call_notify(self, fake_env):
        """Given last_status ファイル不在（VPS 再構築直後など）
        When healthcheck.sh を初回 ok 状態で実行する
        Then notify.sh は呼ばれない（unknown → ok は同種類扱い、initial state confirmation）。
        """
        assert not (fake_env["state_dir"] / "last_status").exists(), "前提: last_status が事前に存在してはいけない"
        proc = self._run_with_state(fake_env, active="active", sub="running", result="success")
        assert proc.returncode == 0
        assert not fake_env["called_marker"].exists(), "初回 ok で notify が呼ばれた（unknown→ok は無音であるべき）"

    def test_state_dir_is_created_if_missing(self, fake_env):
        """Given STATE_DIR が存在しない
        When healthcheck.sh を実行する
        Then mkdir -p で STATE_DIR が作成され、last_status が書き込まれる。
        """
        assert not fake_env["state_dir"].exists(), "前提: state_dir が事前に存在してはいけない"
        proc = self._run_with_state(fake_env, active="active", sub="running", result="success")
        assert proc.returncode == 0, f"healthcheck.sh が non-zero: {proc.stderr}"
        last_status = fake_env["state_dir"] / "last_status"
        assert last_status.exists(), "STATE_DIR/last_status が作成されていない"
        assert last_status.read_text().strip() == "ok", f"last_status の内容が想定外: {last_status.read_text()!r}"


class TestHealthcheckShOrderIndependentParse:
    """``parse_systemctl_kv`` 関数の順序非依存性。

    `systemctl show ... --value` の引数順序非保証バグの真因に対する単体検証。
    全 6 順列（3! = 6）を網羅し、どの順序でも ActiveState/SubState/Result が
    正しい変数に割り当てられることを担保する。
    """

    @pytest.mark.parametrize(
        "lines",
        [
            ("ActiveState=active", "SubState=running", "Result=success"),
            ("ActiveState=active", "Result=success", "SubState=running"),
            ("SubState=running", "ActiveState=active", "Result=success"),
            ("SubState=running", "Result=success", "ActiveState=active"),
            ("Result=success", "ActiveState=active", "SubState=running"),
            ("Result=success", "SubState=running", "ActiveState=active"),
        ],
    )
    def test_parses_kv_regardless_of_line_order(self, lines: tuple[str, str, str]):
        """Given KEY=VALUE 形式の 3 行（順序は任意）
        When parse_systemctl_kv を呼ぶ
        Then active=active, sub=running, result=success が呼び出し元 scope にセットされる。
        """
        if not _HEALTHCHECK_SH.exists():
            pytest.skip("healthcheck.sh が未作成のため skip")
        # heredoc に行を流し込んで parse_systemctl_kv を呼び、結果を 3 行 echo する
        heredoc_body = "\n".join(lines)
        snippet = (
            f'source "{_HEALTHCHECK_SH}"\n'
            f"parse_systemctl_kv <<EOF\n{heredoc_body}\nEOF\n"
            'echo "active=$active"\n'
            'echo "sub=$sub"\n'
            'echo "result=$result"\n'
        )
        proc = _run_bash(snippet)
        assert proc.returncode == 0, f"parse_systemctl_kv が non-zero: {proc.stderr}"
        out = proc.stdout
        assert "active=active" in out, f"active が正しく束ねられていない: {out!r}"
        assert "sub=running" in out, f"sub が正しく束ねられていない: {out!r}"
        assert "result=success" in out, f"result が正しく束ねられていない: {out!r}"


class TestHealthcheckShStateChange:
    """``decide_notification`` 関数の遷移判定（state-change ロジック）。

    order.md 遷移表:
      prev\\current | ok/idle/manual | anomaly
      -------------|----------------|--------
      unknown      | ""             | anomaly
      ok/idle/manual | ""           | anomaly
      anomaly      | recovered      | ""
    """

    @pytest.mark.parametrize(
        "prev,current,expected",
        [
            # 初回（last_status 不在）
            ("unknown", "ok", ""),
            ("unknown", "anomaly", "anomaly"),
            # 同種類の連続は無音
            ("ok", "ok", ""),
            ("idle", "idle", ""),
            ("manual", "manual", ""),
            # ok/idle/manual 間の遷移も無音（同 "正常" カテゴリ）
            ("ok", "idle", ""),
            ("manual", "ok", ""),
            # → anomaly は通知
            ("ok", "anomaly", "anomaly"),
            ("idle", "anomaly", "anomaly"),
            ("manual", "anomaly", "anomaly"),
            # anomaly → 正常系は recovered
            ("anomaly", "ok", "recovered"),
            ("anomaly", "idle", "recovered"),
            ("anomaly", "manual", "recovered"),
            # anomaly 連打抑止
            ("anomaly", "anomaly", ""),
        ],
    )
    def test_decide_notification(self, prev: str, current: str, expected: str):
        """Given (prev, current) の組み合わせ
        When decide_notification を呼ぶ
        Then 期待アクション（""/"anomaly"/"recovered"）を 1 行 echo する。
        """
        if not _HEALTHCHECK_SH.exists():
            pytest.skip("healthcheck.sh が未作成のため skip")
        snippet = f'source "{_HEALTHCHECK_SH}"\ndecide_notification "{prev}" "{current}"\n'
        proc = _run_bash(snippet)
        assert proc.returncode == 0, f"decide_notification が non-zero: {proc.stderr}"
        assert proc.stdout.strip() == expected, (
            f"({prev!r}, {current!r}) の判定が期待値と異なる: got={proc.stdout.strip()!r}, expected={expected!r}"
        )


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
        assert _NOTIFY_SH.exists(), ".claude/skills/streaming/references/notify.sh が存在しない"

    def test_has_bash_shebang(self):
        """Given notify.sh
        When 1 行目を読む
        Then ``#!/usr/bin/env bash`` で始まる。
        """
        first_line = read_file(_NOTIFY_SH).splitlines()[0]
        assert first_line == "#!/usr/bin/env bash", f"shebang が不正: {first_line!r}"

    def test_has_set_strict_mode(self):
        """Given notify.sh
        When 全文を読む
        Then ``set -euo pipefail`` が含まれている。
        """
        text = read_file(_NOTIFY_SH)
        assert re.search(r"^set\s+-euo\s+pipefail\s*$", text, flags=re.MULTILINE), "set -euo pipefail が無い"

    def test_loads_env_file_for_webhook(self):
        """Given notify.sh
        When 全文を読む
        Then ``/etc/youtube-stream-healthcheck.env`` を参照している。

        secret は env file で配信され notify.sh に直書きしない（plan §15）。
        """
        text = read_file(_NOTIFY_SH)
        # source / `.` / set -a + . どれでも環境変数を読み込めばよい
        assert "/etc/youtube-stream-healthcheck.env" in text, (
            "/etc/youtube-stream-healthcheck.env を参照していない（webhook を読み込めない）"
        )

    def test_does_not_source_env_file(self):
        """Given notify.sh
        When 全文を読む
        Then env ファイルを ``source`` / ``.`` で評価していない。

        issue #161: env ファイルを bash として評価すると改ざん時に root 任意コード
        実行を許す。``grep + cut`` の限定パーサで読むのが正しい経路。
        """
        text = read_file(_NOTIFY_SH)
        # `source "$ENV_FILE"` / `source /etc/...` / `. "$ENV_FILE"` / `. /etc/...` のいずれも禁止
        assert not re.search(
            r'^\s*(?:source|\.)\s+["\']?(?:\$\{?ENV_FILE\}?|/etc/youtube-stream-healthcheck\.env)',
            text,
            flags=re.MULTILINE,
        ), "env ファイルを source / . で評価している（改ざん時に root 任意コード実行のリスク）"

    def test_parses_webhook_with_grep_cut(self):
        """Given notify.sh
        When 全文を読む
        Then ``DISCORD_WEBHOOK_URL`` を ``grep + cut`` の限定パーサで取得している。

        issue #161 推奨実装: ``grep -E '^DISCORD_WEBHOOK_URL=' ... | cut -d= -f2- | tr ...``
        """
        text = read_file(_NOTIFY_SH)
        assert re.search(
            r"DISCORD_WEBHOOK_URL=\$\(\s*grep\s+-E\s+'\^DISCORD_WEBHOOK_URL=",
            text,
        ), (
            "DISCORD_WEBHOOK_URL の grep ベース限定パーサが見つからない "
            "（行頭アンカー '^' は必須: コメント内代入や行中代入を拾わないため）"
        )
        assert re.search(r"cut\s+-d=\s+-f2-", text), (
            "cut -d= -f2- が見つからない（webhook トークンに = が混じった場合に切り詰めるリスク）"
        )

    def test_does_not_hardcode_webhook_url(self):
        """Given notify.sh
        When 全文を読む
        Then ``discord.com/api/webhooks/<id>/<token>`` の実値らしきリテラルが直書きされていない。

        secret 漏洩防止の最重要要件。
        """
        text = read_file(_NOTIFY_SH)
        assert not re.search(
            r"https://discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_\-]{20,}",
            text,
        ), "Discord Webhook URL が直書きされている（secret 漏洩リスク）"

    def test_uses_curl_for_post(self):
        """Given notify.sh
        When 全文を読む
        Then ``curl`` が呼ばれ、``-X POST`` または ``--data`` 系の POST 経路がある。
        """
        text = read_file(_NOTIFY_SH)
        assert re.search(r"\bcurl\b", text), "curl が使われていない（HTTP POST する手段が無い）"

    def test_posts_json_with_content_field(self):
        """Given notify.sh
        When 全文を読む
        Then ``Content-Type: application/json`` を指定し ``content`` フィールドを含む JSON を送る。

        Discord Webhook の仕様: ``{"content": "..."}`` 形式が最低限。
        """
        text = read_file(_NOTIFY_SH)
        assert "application/json" in text, "Content-Type: application/json が指定されていない"
        assert re.search(r'"content"', text), 'Discord JSON の "content" フィールドが無い'

    def test_does_not_propagate_curl_failure_to_cron(self):
        """Given notify.sh
        When 全文を読む
        Then ``curl`` 失敗が cron まで伝播しない（``|| true`` か末尾 ``exit 0`` 等で吸収）。

        plan §「実装アプローチ 3」: HTTP エラーでも exit 0（cron を壊さない）。
        """
        text = read_file(_NOTIFY_SH)
        # curl ... || true / curl ... || : / 末尾に exit 0 / curl 行を if/||  で囲む 等
        has_or_true = re.search(r"curl[^\n]*\|\|\s*(true|:)", text)
        has_exit_zero = re.search(r"^exit\s+0\s*$", text, flags=re.MULTILINE)
        # set +e で囲む手段もあり
        has_set_plus_e = re.search(r"set\s+\+e", text)
        assert has_or_true or has_exit_zero or has_set_plus_e, (
            "curl 失敗時に cron へエラーが伝播する書き方になっている "
            "（|| true / exit 0 / set +e のいずれかで吸収すること）"
        )

    def test_validates_webhook_url_scheme_and_host(self):
        """Given notify.sh
        When 全文を読む
        Then ``^https://(discord\\.com|discordapp\\.com)/api/webhooks/`` の正規表現で
             webhook URL を検証している（Issue #166 SSRF 防御）。

        secret store 侵害時に file:// / http://169.254.169.254/... へすり替えられる
        ことを防ぐ。
        """
        text = read_file(_NOTIFY_SH)
        # bash の =~ 演算子で上記の正規表現が現れること
        # `\\.` のバックスラッシュは Python 文字列内で `\\\\\.` だが、ファイル上は `\.`
        assert re.search(
            r"=~\s*\^https://\(discord\\\.com\|discordapp\\\.com\)/api/webhooks/",
            text,
        ), (
            "notify.sh に webhook URL スキーム/ホスト検証の正規表現が無い "
            "（^https://(discord\\.com|discordapp\\.com)/api/webhooks/ を =~ で照合すること）"
        )


class TestNotifyShEnvParser:
    """notify.sh の env パーサ動作確認（issue #161 セキュリティ回帰テスト）。

    `grep + cut + tr` の限定パーサが
    - 正常な KEY=VALUE 形式から webhook を取り出せる
    - 改ざんされた env ファイル（コマンド注入を仕込んだ内容）を bash として
      評価しない（任意コード実行が起きない）
    ことを確認する。
    """

    def _extract_parser_line(self) -> str:
        """notify.sh から DISCORD_WEBHOOK_URL= の限定パーサ行を抜き出す。"""
        text = read_file(_NOTIFY_SH)
        match = re.search(r"^DISCORD_WEBHOOK_URL=\$\(.+?\)$", text, flags=re.MULTILINE)
        assert match, "DISCORD_WEBHOOK_URL の限定パーサ行が見つからない"
        return match.group(0)

    def _run_parser_with_env(self, env_file: Path) -> subprocess.CompletedProcess:
        """env_file を入力に notify.sh の限定パーサ行を bash 実行する。

        3 つのパーサ単体テストで共通の snippet 構築 + ``_run_bash`` 呼び出しを集約する
        helper（同ファイル ``_classify`` と同型の責務分離）。env_file 内容のみが差分。
        """
        snippet = f'ENV_FILE="{env_file}"\n{self._extract_parser_line()}\nprintf "%s" "$DISCORD_WEBHOOK_URL"\n'
        return _run_bash(snippet)

    def test_parses_valid_webhook(self, tmp_path: Path):
        """Given DISCORD_WEBHOOK_URL=<url> のみが書かれた env ファイル
        When notify.sh のパーサ行を実行する
        Then 値が正しく取り出される。
        """
        env_file = tmp_path / "env"
        env_file.write_text("DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/123/abc=def\n")
        proc = self._run_parser_with_env(env_file)
        assert proc.returncode == 0, f"パーサがエラー終了: stderr={proc.stderr}"
        # cut -d= -f2- が効いて、トークン側の '=' も保持される
        assert proc.stdout == "https://discord.com/api/webhooks/123/abc=def", (
            f"webhook 値が想定通り抽出されていない: {proc.stdout!r}"
        )

    def test_strips_quotes_and_cr(self, tmp_path: Path):
        """Given 引用符付き値・CRLF 改行が混入した env ファイル
        When notify.sh のパーサ行を実行する
        Then ``"`` と ``\\r`` が除去される。
        """
        env_file = tmp_path / "env"
        # CRLF + ダブルクオート両方を含める
        env_file.write_bytes(b'DISCORD_WEBHOOK_URL="https://example.com/hook"\r\n')
        proc = self._run_parser_with_env(env_file)
        assert proc.returncode == 0
        assert proc.stdout == "https://example.com/hook", f"引用符/CR が除去されていない: {proc.stdout!r}"

    def test_does_not_execute_malicious_payload(self, tmp_path: Path):
        """Given env ファイルにコマンド注入が仕込まれている
        When notify.sh のパーサ行を実行する
        Then 注入されたコマンドは実行されない（issue #161 セキュリティ要件）。

        ``source`` 経路では ``DISCORD_WEBHOOK_URL=$(touch ...)`` のような書き方で
        任意コードが走るが、``grep + cut`` パーサでは値が単なる文字列として扱われる。
        """
        env_file = tmp_path / "env"
        marker = tmp_path / "pwned"
        # source されると `touch <marker>` の戻り値が代入され marker ファイルが作られる
        env_file.write_text(f"DISCORD_WEBHOOK_URL=$(touch {marker})\nPATH=/tmp/evil:$PATH\n")
        proc = self._run_parser_with_env(env_file)
        assert proc.returncode == 0
        # marker が作られていない = コマンド置換が走っていない
        assert not marker.exists(), f"env ファイルのコマンド置換が実行された（脆弱性が残存）: {marker}"
        # 値はリテラル文字列としてそのまま取れる
        assert proc.stdout == f"$(touch {marker})", f"値がリテラルとして取れていない: {proc.stdout!r}"

    def test_full_script_exits_zero_when_webhook_key_missing(self, tmp_path: Path):
        """Given env ファイルに ``DISCORD_WEBHOOK_URL=`` 行が無い
        When notify.sh をフルスクリプトとして ``set -euo pipefail`` 込みで実行する
        Then exit 0 で終わる（cron を壊さない）。

        回帰防止: ``grep`` の non-match (exit 1) が pipefail で伝播し
        ``set -e`` で silent に script 自体を落とすバグを防ぐ。
        ``scripts/streaming/notify.sh:11-12`` の「cron を壊さないため exit 0 で吸収」方針。
        """
        env_file = tmp_path / "env"
        # DISCORD_WEBHOOK_URL= 行を含まない env ファイル（他のキーのみ）
        env_file.write_text("SOME_OTHER_KEY=value\n")
        # ENV_FILE 定数を上書きするため notify.sh 本文の ``readonly ENV_FILE=...`` 行を
        # tmp_path のパスに差し替えてから実行する（ファイル自体は変更しない）。
        notify_text = read_file(_NOTIFY_SH)
        rewritten = re.sub(
            r'^readonly\s+ENV_FILE="[^"]+"$',
            f'readonly ENV_FILE="{env_file}"',
            notify_text,
            count=1,
            flags=re.MULTILINE,
        )
        assert rewritten != notify_text, "ENV_FILE の readonly 宣言を差し替えられなかった"
        script_path = tmp_path / "notify.sh"
        script_path.write_text(rewritten)
        script_path.chmod(0o755)
        proc = _run_bash(f'"{script_path}" "test message"')
        assert proc.returncode == 0, (
            f"webhook キー未設定 env で exit 0 にならない（cron が壊れる）: "
            f"rc={proc.returncode}, stderr={proc.stderr!r}"
        )


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
        assert _HEALTHCHECK_ENV_TFTPL.exists(), "templates/youtube-stream-healthcheck.env.tftpl が存在しない"

    def test_contains_webhook_variable_assignment(self):
        """Given env tftpl
        When 全文を読む
        Then ``DISCORD_WEBHOOK_URL=${webhook}`` 行がある（terraform templatefile 変数記法）。
        """
        text = read_file(_HEALTHCHECK_ENV_TFTPL)
        assert re.search(r"^DISCORD_WEBHOOK_URL=\$\{webhook\}\s*$", text, flags=re.MULTILINE), (
            "DISCORD_WEBHOOK_URL=${webhook} 行が存在しない"
        )

    def test_value_is_not_quoted(self):
        """Given env tftpl
        When DISCORD_WEBHOOK_URL の右辺を読む
        Then 値がクォート（``"..."`` / ``'...'``）で囲まれていない。

        systemd EnvironmentFile はクォートを文字列の一部とみなす（curl URL に余計な文字が混入する）。
        """
        text = read_file(_HEALTHCHECK_ENV_TFTPL)
        assert not re.search(r"^DISCORD_WEBHOOK_URL=['\"]", text, flags=re.MULTILINE), (
            "DISCORD_WEBHOOK_URL の値がクォートされている（systemd EnvironmentFile 慣例違反）"
        )

    def test_does_not_contain_plaintext_webhook(self):
        """Given env tftpl
        When 全文を読む
        Then ``https://discord.com/api/webhooks/...`` の実値が直書きされていない。

        secret は terraform templatefile() の variables map 経由でだけ流入させる。
        """
        text = read_file(_HEALTHCHECK_ENV_TFTPL)
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
        text = strip_hcl_comments(read_file(_VARIABLES_TF))
        block = extract_block(text, r'variable\s+"discord_webhook_url"')
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
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None
        triggers = extract_block(block, r"triggers")
        assert triggers is not None, "null_resource.deploy.triggers ブロックが存在しない"
        assert re.search(
            r"nonsensitive\(\s*sha256\(\s*var\.discord_webhook_url\s*\)\s*\)",
            triggers,
        ), "triggers に nonsensitive(sha256(var.discord_webhook_url)) が無い （webhook 差し替えで再 deploy されない）"

    @pytest.mark.parametrize(
        "destination",
        [
            rf"{_INSTALL_ROOT_VAR}/bin/healthcheck\.sh",
            rf"{_INSTALL_ROOT_VAR}/bin/notify\.sh",
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
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None
        assert re.search(
            rf'destination\s*=\s*"{destination}"',
            block,
        ), f'provisioner "file" で destination="{destination}" が宣言されていない'

    def test_provisioner_file_uploads_healthcheck_env_via_templatefile(self):
        """Given main.tf
        When null_resource.deploy 内の provisioner "file" を走査する
        Then ``/tmp/youtube-stream-healthcheck.env.tmp`` への配信があり、
             ``templatefile("${path.module}/templates/youtube-stream-healthcheck.env.tftpl", ...)``
             で生成されている。

        SCP 着地後は remote-exec の ``install -m 0600 -o root -g root`` で
        ``/etc/youtube-stream-healthcheck.env`` へ原子移送される（race window 閉鎖）。
        """
        text = strip_hcl_comments(read_file(_MAIN_TF))
        block = extract_block(text, r'resource\s+"null_resource"\s+"deploy"')
        assert block is not None
        assert re.search(
            r'destination\s*=\s*"/tmp/youtube-stream-healthcheck\.env\.tmp"',
            block,
        ), '/tmp/youtube-stream-healthcheck.env.tmp への provisioner "file" destination が無い'
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
        text = read_file(_MAIN_TF)
        # 同じ行近傍に webhook = var.discord_webhook_url が現れること
        assert re.search(
            r"webhook\s*=\s*var\.discord_webhook_url",
            text,
        ), "templatefile に webhook = var.discord_webhook_url が渡されていない"

    def test_remote_exec_secures_healthcheck_env_file_perms(self):
        """Given main.tf
        When provisioner "remote-exec" の inline を読む
        Then ``/etc/youtube-stream-healthcheck.env`` を
             ``install -m 0600 -o root -g root`` で原子移送している。

        SCP 経由の ``/tmp/*.tmp`` 着地 → install で /etc/ へ rename(2) 相当の
        atomic move を行うことで、0600 root:root が確定するまでの race window を閉じる。
        webhook を読める範囲を root に限定する（secret 隔離）。
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
        assert re.search(
            r"install\s+-m\s+0600\s+-o\s+root\s+-g\s+root\s+/tmp/youtube-stream-healthcheck\.env\.tmp\s+/etc/youtube-stream-healthcheck\.env",
            inline,
        ), (
            "install -m 0600 -o root -g root /tmp/youtube-stream-healthcheck.env.tmp "
            "/etc/youtube-stream-healthcheck.env が無い（race window が閉じられていない）"
        )
        assert re.search(
            r"rm\s+-f\s+/tmp/youtube-stream-healthcheck\.env\.tmp",
            inline,
        ), (
            "rm -f /tmp/youtube-stream-healthcheck.env.tmp が無い"
            "（install 後の /tmp 上の 0644 secret が残置し race window が /tmp/ に横移しになる）"
        )

    def test_remote_exec_makes_bin_dir_and_executable(self):
        """Given main.tf
        When provisioner "remote-exec" の inline を読む
        Then ``${var.install_root}/bin`` を作成し、配置した shell スクリプトを実行可能にしている。

        ``mkdir -p ${var.install_root}/bin`` または ``install -d`` 系のいずれか + ``chmod 755`` 系。
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
        # ディレクトリ作成（mkdir -p または install -d）
        assert re.search(
            rf"(mkdir\s+-p|install\s+-d)[^\n]*{_INSTALL_ROOT_VAR}/bin\b",
            inline,
        ), "${var.install_root}/bin の作成コマンドが無い"
        # 実行権限付与（個別 chmod 755 でも /opt/.../bin/*.sh への一括でも可）
        assert re.search(
            rf"chmod\s+(?:0?7?55|\+x)[^\n]*{_INSTALL_ROOT_VAR}/bin",
            inline,
        ), "${var.install_root}/bin 配下のスクリプトに実行権限が付与されていない"

    def test_remote_exec_reloads_cron(self):
        """Given main.tf
        When provisioner "remote-exec" の inline を読む
        Then cron daemon を反映するコマンドがある（``systemctl restart cron`` / ``service cron reload`` 等）。

        cron.d は配置するだけでは即時反映されない場合があるため、明示的に再起動を呼ぶ必要がある
        （Ubuntu 24.04 の vixie-cron / cron は通常自動検知するが、明示で確実にする）。
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
        text = read_file(_CLOUD_INIT_YAML)
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
        text = strip_hcl_comments(read_file(_TFVARS_EXAMPLE))
        assert not re.search(r"^\s*discord_webhook_url\s*=", text, flags=re.MULTILINE), (
            "discord_webhook_url の代入がアクティブ行に存在する（secret 漏洩リスク）"
        )

    def test_mentions_tf_var_discord_webhook_url_in_comments(self):
        """Given terraform.tfvars.example
        When ファイル内容（コメント込み）を読む
        Then ``TF_VAR_discord_webhook_url`` の使い方がコメントに記載されている。
        """
        raw = read_file(_TFVARS_EXAMPLE)
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
        text = read_file(_STREAMING_README)
        assert "Discord" in text, "README に Discord 言及が無い（死活監視の通知手段が説明されない）"

    def test_mentions_tf_var_discord_webhook_url(self):
        """Given README
        When 全文を読む
        Then ``TF_VAR_discord_webhook_url`` 環境変数の言及がある（secret 注入の入口）。
        """
        text = read_file(_STREAMING_README)
        assert "TF_VAR_discord_webhook_url" in text, (
            "README に TF_VAR_discord_webhook_url の言及が無い（secret 注入手順が辿れない）"
        )

    def test_mentions_healthcheck_script_path(self):
        """Given README
        When 全文を読む
        Then ``healthcheck.sh`` の言及がある（運用者が cron で何が動くかを把握できる）。
        """
        text = read_file(_STREAMING_README)
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
        text = read_file(_STREAMING_README)
        if scenario_keyword == "再開":
            assert "再開" in text or "auto-restart" in text or "RestartSec" in text, (
                "README に自動再開シナリオの言及が無い"
            )
        else:
            assert scenario_keyword in text, (
                f"README に '{scenario_keyword}' シナリオの言及が無い（4 シナリオ運用手順未網羅）"
            )


# ============================================================================
# src/youtube_automation/utils/streaming/daily_archive.py — count_archives_for_date
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
        from youtube_automation.utils.streaming.daily_archive import count_archives_for_date

        service = self._make_service(search_items=[], video_items=[])
        count = count_archives_for_date(service, date(2026, 5, 1))
        assert count == 0, f"動画ゼロのとき 0 を返すべき: {count}"

    def test_counts_videos_with_actual_end_time_in_target_date(self):
        """Given target_date に actualEndTime を持つ動画 2 本
        When count_archives_for_date を呼ぶ
        Then 2 を返す。

        アーカイブ生成モードで 1 日 2 本を期待する通常系。
        """
        from youtube_automation.utils.streaming.daily_archive import count_archives_for_date

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
        from youtube_automation.utils.streaming.daily_archive import count_archives_for_date

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
        from youtube_automation.utils.streaming.daily_archive import count_archives_for_date

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
        from youtube_automation.utils.streaming.daily_archive import count_archives_for_date

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
# move 完全性: 新パス到達 / 旧パス消滅 / __init__ 非露出
# ============================================================================


class TestDailyArchiveModuleSurface:
    """`utils/streaming_archive.py` → `utils/streaming/daily_archive.py` の move 完全性。

    plan の R1–R2（新パス到達担保）と R7（旧パス shim 不残置）を構造アサーションで担保する。
    既存 5 ケース（`TestStreamingArchiveCount`）は import 文の付け替えで振る舞いを検証するが、
    パス文字列を直接 importlib で評価するアサーションを別に持つことで、move の意図を機械的に保証する。
    """

    def test_new_daily_archive_path_is_importable(self):
        """Given move 後の構成
        When `youtube_automation.utils.streaming.daily_archive` を import する
        Then モジュールが解決可能で `count_archives_for_date` を公開している。
        """
        import importlib

        mod = importlib.import_module("youtube_automation.utils.streaming.daily_archive")
        assert hasattr(mod, "count_archives_for_date"), (
            "新パス `streaming/daily_archive` が `count_archives_for_date` を公開していない"
        )

    def test_old_flat_streaming_archive_path_is_not_importable(self):
        """Given move 後の構成（後方互換 shim 不残置）
        When 旧パス `youtube_automation.utils.streaming_archive` を import する
        Then `ModuleNotFoundError` を投げる。

        order.md「move のみ（新公開 API を増やさない）」+ CLAUDE.md「後方互換コードは不要」を担保。
        """
        import importlib

        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("youtube_automation.utils.streaming_archive")


class TestStreamingPackageSurface:
    """`utils/streaming/__init__.py` の公開 API surface。

    plan R6（`__init__.py` で新公開 API を増やさない）を担保。
    `streaming/__init__.py` は定数集中モジュールであり、関数の再 export は方針として行わない。
    """

    def test_streaming_package_does_not_export_daily_count(self):
        """Given `streaming/__init__.py` は定数のみ集約する方針
        When `youtube_automation.utils.streaming` を import する
        Then `count_archives_for_date` は package 直下から見えない。

        order.md「新公開 API は増やさない」と `streaming/__init__.py` の既存方針の整合。
        """
        import youtube_automation.utils.streaming as pkg

        assert not hasattr(pkg, "count_archives_for_date"), (
            "streaming/__init__.py に count_archives_for_date を re-export してはならない"
            "（order.md: 新公開 API を増やさない）"
        )


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

    def test_expected_is_required(self):
        """Given --expected なし
        When --expected なしで main を呼ぶ
        Then 暗黙の 2 本判定を走らせず argparse error で停止する。
        """
        from youtube_automation.scripts import streaming_archive_check

        with patch.object(sys, "argv", ["yt-stream-archive-check", "--date", "2026-05-01"]):
            with pytest.raises(SystemExit) as e:
                streaming_archive_check.main()

        assert e.value.code == 2

    def test_expected_zero_is_rejected(self):
        """Given --expected 0
        When main を呼ぶ
        Then argparse error (exit 2) で停止する（期待件数 0 は無意味）。
        """
        from youtube_automation.scripts import streaming_archive_check

        with patch.object(sys, "argv", ["yt-stream-archive-check", "--date", "2026-05-01", "--expected", "0"]):
            with pytest.raises(SystemExit) as e:
                streaming_archive_check.main()

        assert e.value.code == 2, f"--expected 0 が argparse error で拒否されていない: exit code={e.value.code}"

    def test_expected_negative_is_rejected(self):
        """Given --expected -1
        When main を呼ぶ
        Then argparse error (exit 2) で停止する（負の期待件数は無意味）。
        """
        from youtube_automation.scripts import streaming_archive_check

        with patch.object(sys, "argv", ["yt-stream-archive-check", "--date", "2026-05-01", "--expected", "-1"]):
            with pytest.raises(SystemExit) as e:
                streaming_archive_check.main()

        assert e.value.code == 2, f"--expected -1 が argparse error で拒否されていない: exit code={e.value.code}"

    def test_notify_on_shortage_posts_to_discord(self):
        """Given count_archives_for_date が不足を返す + --notify-on-shortage
        When main を呼ぶ
        Then 共通 `notify()` が `content=...` / `webhook_url=...` 付きで呼ばれる。
        """
        from youtube_automation.scripts import streaming_archive_check

        webhook = "https://discord.com/api/webhooks/123/abc"
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
                return_value=webhook,
            ),
            patch.object(streaming_archive_check, "notify") as mock_notify,
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
            assert mock_notify.called, "--notify-on-shortage を指定しても notify() が呼ばれていない（通知が飛ばない）"
            kwargs = mock_notify.call_args.kwargs
            assert kwargs["content"].startswith("[youtube-stream] アーカイブ不足:"), (
                f"notify() の content prefix が想定外: {kwargs.get('content')!r}"
            )
            assert kwargs["webhook_url"] == webhook, (
                f"notify() に渡された webhook_url が DISCORD_WEBHOOK_URL ではない: {kwargs.get('webhook_url')!r}"
            )

    def test_notify_failure_returns_exit_code_2(self):
        """Given --notify-on-shortage 指定下で notify() が NotificationError を raise
        When main を呼ぶ
        Then 件数不足 (exit 1) と区別するため exit code 2 を返す。
        """
        from youtube_automation.scripts import streaming_archive_check
        from youtube_automation.utils.notification import NotificationError

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
            patch.object(
                streaming_archive_check,
                "notify",
                side_effect=NotificationError("webhook POST failed: 500"),
            ),
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
                rc = streaming_archive_check.main()
            except SystemExit as e:
                rc = e.code
        assert rc == 2, f"Discord 通知失敗時は exit 2 を期待: actual={rc!r}"


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
        text = read_file(_PYPROJECT)
        # `yt-stream-archive-check = "..."` 行が [project.scripts] にあること
        assert re.search(
            r'^yt-stream-archive-check\s*=\s*"youtube_automation\.cli_entrypoints:yt_stream_archive_check"',
            text,
            flags=re.MULTILINE,
        ), (
            "yt-stream-archive-check entry point が pyproject.toml に登録されていない "
            '（"youtube_automation.cli_entrypoints:yt_stream_archive_check" を指すこと）'
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
        text = read_file(_HEALTHCHECK_DOC)
        assert scenario_keyword in text, f"運用手順書に '{scenario_keyword}' シナリオの記載が無い"

    def test_documents_auto_restart_scenario(self):
        """Given streaming-healthcheck.md
        When 全文を読む
        Then 1 時間後の自動再開（RestartSec / auto-restart / 再開 のいずれか）の言及がある。
        """
        text = read_file(_HEALTHCHECK_DOC)
        assert "再開" in text or "RestartSec" in text or "auto-restart" in text, (
            "運用手順書に自動再開シナリオの記載が無い"
        )

    def test_documents_archive_check_as_archive_mode_only(self):
        """Given streaming-healthcheck.md
        When アーカイブ件数チェックの説明を読む
        Then 24/7 では shortage 判定対象外で、11/1 運用時だけ --expected 2 を案内する。
        """
        text = read_file(_HEALTHCHECK_DOC)
        assert "24/7 連続配信では日次アーカイブを期待しない" in text
        assert "uv run yt-stream-archive-check --date" in text
        assert "--expected 2 --notify-on-shortage" in text
