"""infra/terraform/streaming に紐づくシェルスクリプトの検証テスト。

- ``.claude/skills/streaming/references/swap_video.sh``: 動画差し替え
- ``.claude/skills/streaming/references/run-ffmpeg.sh``: ffmpeg ラッパー
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from tests.helpers.hcl import read_file
from tests.repo.streaming._helpers import (
    _REPO_ROOT,
    _RUN_FFMPEG_SCRIPT,
    _SELECT_CHANNEL_SCRIPT,
    _SWAP_VIDEO_SCRIPT,
)


class TestSelectChannelScript:
    """チャンネル選択と Terraform 変数注入を一体化するラッパーの契約。"""

    @staticmethod
    def _run(
        tmp_path: Path,
        workspace: str,
        *args: str,
        agent_fingerprint: str = "SHA256:test",
    ) -> tuple[subprocess.CompletedProcess[str], str]:
        tf_dir = tmp_path / "terraform"
        tf_dir.mkdir(exist_ok=True)
        (tf_dir / "main.tf").touch()
        stub_dir = tmp_path / "bin"
        stub_dir.mkdir(exist_ok=True)
        calls = tmp_path / "calls"
        terraform = stub_dir / "terraform"
        terraform.write_text(
            "#!/usr/bin/env bash\n"
            'printf "%s channel=%s video=%s\\n" "$*" "${TF_VAR_channel_slug:-}" '
            '"${TF_VAR_video_path:-}" >> "$CALLS"\n'
            'case "$*" in\n'
            '  *"workspace list"*) printf "  default\\n  002ch-deepfocus365\\n  003ch-soulful-grooves\\n" ;;\n'
            f'  *"workspace show"*) printf "%s\\n" "${{SHOW_WORKSPACE:-{workspace}}}" ;;\n'
            "esac\n",
            encoding="utf-8",
        )
        terraform.chmod(0o755)
        op = stub_dir / "op"
        op.write_text('#!/usr/bin/env bash\nprintf "secret-value\\n"\n', encoding="utf-8")
        op.chmod(0o755)
        ssh_keygen = stub_dir / "ssh-keygen"
        ssh_keygen.write_text(
            '#!/usr/bin/env bash\nprintf "256 SHA256:test operator@test (ED25519)\\n"\n',
            encoding="utf-8",
        )
        ssh_keygen.chmod(0o755)
        ssh_add = stub_dir / "ssh-add"
        ssh_add.write_text(
            f'#!/usr/bin/env bash\nprintf "256 {agent_fingerprint} operator@test (ED25519)\\n"\n',
            encoding="utf-8",
        )
        ssh_add.chmod(0o755)
        home_dir = tmp_path / "home"
        ssh_dir = home_dir / ".ssh"
        ssh_dir.mkdir(parents=True)
        (ssh_dir / "yt_stream_key.pub").write_text("stub public key\n", encoding="utf-8")
        env = {
            **os.environ,
            "HOME": str(home_dir),
            "PATH": f"{stub_dir}:{os.environ['PATH']}",
            "CALLS": str(calls),
        }
        result = subprocess.run(
            [str(_SELECT_CHANNEL_SCRIPT), workspace, *args, "--tf-dir", str(tf_dir)],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        return result, calls.read_text(encoding="utf-8") if calls.exists() else ""

    def test_rejects_unknown_workspace_before_select(self, tmp_path: Path):
        result, calls = self._run(tmp_path, "missing-channel", "show")
        assert result.returncode != 0
        assert "workspace new missing-channel" in result.stderr
        assert "002ch-deepfocus365" in result.stderr
        assert "workspace select" not in calls

    def test_selects_verifies_and_shows_state(self, tmp_path: Path):
        result, calls = self._run(tmp_path, "003ch-soulful-grooves", "show")
        assert result.returncode == 0, result.stderr
        assert "workspace select 003ch-soulful-grooves" in calls
        assert "workspace show" in calls
        assert "state list" in calls

    def test_rejects_missing_video_before_plan(self, tmp_path: Path):
        missing = tmp_path / "missing.mp4"
        result, calls = self._run(tmp_path, "003ch-soulful-grooves", "plan", "--video", str(missing))
        assert result.returncode != 0
        assert str(missing) in result.stderr
        assert " plan" not in calls

    def test_dry_run_prints_reference_not_secret(self, tmp_path: Path):
        video = tmp_path / "stream.mp4"
        video.touch()
        result, calls = self._run(
            tmp_path,
            "002ch-deepfocus365",
            "plan",
            "--video",
            str(video),
            "--dry-run",
        )
        assert result.returncode == 0, result.stderr
        assert "op://Personal/YouTube_DeepFocus365/stream_key" in result.stdout
        assert "secret-value" not in result.stdout + result.stderr
        assert calls == ""

    def test_show_dry_run_does_not_require_registered_stream_key(self, tmp_path: Path):
        result, calls = self._run(tmp_path, "unregistered-channel", "show", "--dry-run")
        assert result.returncode == 0, result.stderr
        assert "stream-key-ref" not in result.stdout
        assert "terraform show" not in result.stdout
        assert calls == ""

    def test_help_does_not_include_shell_setup(self, tmp_path: Path):
        result, calls = self._run(tmp_path, "--help")
        assert result.returncode == 0, result.stderr
        assert "set -euo pipefail" not in result.stdout
        assert calls == ""

    def test_plan_injects_channel_slug(self, tmp_path: Path):
        video = tmp_path / "stream.mp4"
        video.touch()
        result, calls = self._run(tmp_path, "003ch-soulful-grooves", "plan", "--video", str(video))
        assert result.returncode == 0, result.stderr
        assert "plan channel=003ch-soulful-grooves" in calls
        assert "secret-value" not in result.stdout + result.stderr

    def test_destroy_without_video_injects_required_video_path(self, tmp_path: Path):
        result, calls = self._run(tmp_path, "003ch-soulful-grooves", "destroy")
        assert result.returncode == 0, result.stderr
        assert "destroy channel=003ch-soulful-grooves video=/dev/null" in calls

    def test_apply_rejects_unregistered_ssh_key_before_terraform(self, tmp_path: Path):
        video = tmp_path / "stream.mp4"
        video.touch()
        result, calls = self._run(
            tmp_path,
            "003ch-soulful-grooves",
            "apply",
            "--video",
            str(video),
            agent_fingerprint="SHA256:other",
        )
        assert result.returncode != 0
        assert "ssh-agent" in result.stderr
        assert " apply" not in calls

    def test_apply_accepts_registered_ssh_key(self, tmp_path: Path):
        video = tmp_path / "stream.mp4"
        video.touch()
        result, calls = self._run(
            tmp_path,
            "003ch-soulful-grooves",
            "apply",
            "--video",
            str(video),
        )
        assert result.returncode == 0, result.stderr
        assert f"apply channel=003ch-soulful-grooves video={video}" in calls


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

    @pytest.mark.parametrize(
        ("cli_args", "expected_apply"),
        [
            ([], "apply"),
            (["--auto-approve"], "apply -auto-approve"),
        ],
    )
    def test_script_passes_auto_approve_only_when_requested(
        self,
        tmp_path: Path,
        cli_args: list[str],
        expected_apply: str,
    ):
        """Given terraform・SSH 前提を隔離 stub した環境
        When default または --auto-approve でスクリプトを実行
        Then plan 後の apply argv に利用者指定だけが反映される。
        """
        stub_dir = tmp_path / "bin"
        stub_dir.mkdir()
        calls_path = tmp_path / "terraform-calls.txt"

        stubs = {
            "terraform": '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$TERRAFORM_CALLS"\n',
            "realpath": '#!/usr/bin/env bash\nprintf "%s\\n" "$1"\n',
            "ssh-keygen": '#!/usr/bin/env bash\nprintf "256 SHA256:test operator@test (ED25519)\\n"\n',
            "ssh-add": '#!/usr/bin/env bash\nprintf "256 SHA256:test operator@test (ED25519)\\n"\n',
        }
        for name, body in stubs.items():
            path = stub_dir / name
            path.write_text(body, encoding="utf-8")
            path.chmod(0o755)

        home_dir = tmp_path / "home"
        ssh_dir = home_dir / ".ssh"
        ssh_dir.mkdir(parents=True)
        (ssh_dir / "yt_stream_key.pub").write_text("stub public key\n", encoding="utf-8")

        terraform_dir = tmp_path / "terraform"
        terraform_dir.mkdir()
        (terraform_dir / "main.tf").write_text("# stub\n", encoding="utf-8")
        video_path = tmp_path / "video.mp4"
        video_path.write_bytes(b"video")

        env = os.environ.copy()
        env.update(
            {
                "HOME": str(home_dir),
                "PATH": f"{stub_dir}:/usr/bin:/bin",
                "TERRAFORM_CALLS": str(calls_path),
            }
        )
        proc = subprocess.run(
            [
                "bash",
                str(_SWAP_VIDEO_SCRIPT),
                *cli_args,
                "--tf-dir",
                str(terraform_dir),
                str(video_path),
            ],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

        assert proc.returncode == 0, proc.stderr
        assert calls_path.read_text(encoding="utf-8").splitlines() == [
            f"-chdir={terraform_dir} plan",
            f"-chdir={terraform_dir} {expected_apply}",
        ]


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
