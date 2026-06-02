"""infra/terraform/streaming に紐づくシェルスクリプトの検証テスト。

- ``.claude/skills/streaming/references/swap_video.sh``: 動画差し替え
- ``.claude/skills/streaming/references/run-ffmpeg.sh``: ffmpeg ラッパー
"""

from __future__ import annotations

import re

import pytest

from tests.helpers.hcl import read_file
from tests.streaming._helpers import (
    _REPO_ROOT,
    _RUN_FFMPEG_SCRIPT,
    _SWAP_VIDEO_SCRIPT,
)

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

    def test_script_exists(self):
        """Given リポジトリ
        When ``.claude/skills/streaming/references/swap_video.sh`` を探す
        Then 当該ファイルが存在する。

        order.md「スクリプト化（任意）: ``swap_video.sh``」要件の最低条件。
        ラッパーは README から発見可能であっても、ファイルが無ければ叩けない。
        """
        assert _SWAP_VIDEO_SCRIPT.exists(), (
            f"{_SWAP_VIDEO_SCRIPT.relative_to(_REPO_ROOT)} が存在しない（1 コマンドラッパーが未実装）"
        )

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
        既存 ``.claude/skills/channel-setup/references/gcp-terraform-apply.sh:13`` と同方針。
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

    def test_script_default_apply_is_interactive(self):
        """Given スクリプト本文
        When 全文を読む
        Then ``-auto-approve`` の付与が条件分岐配下にある（無条件付与ではない）。

        plan.md「``--auto-approve`` は off（対話確認）」要件。デフォルトで
        ``-auto-approve`` を付けると誤 apply 事故のリスクが上がる。``--auto-approve``
        フラグを明示した時のみ ``-auto-approve`` を Terraform に渡す分岐構造であること。
        """
        text = read_file(_SWAP_VIDEO_SCRIPT)
        # `--auto-approve` のフラグハンドリング（引数パース）が存在する
        assert re.search(r"--auto-approve\b", text), (
            "swap_video.sh に `--auto-approve` 引数の取り扱いが無い"
            "（plan.md 仕様: フラグ off がデフォルト / 明示時のみ非対話 apply）"
        )
        # `terraform ... apply -auto-approve` が無条件に書かれていない
        # （= 直接 1 行で `terraform apply -auto-approve` を書くのは禁止。条件分岐配下が必須）
        unconditional = re.search(
            r"^[ \t]*terraform\s+[^\n]*\bapply\b[^\n]*-auto-approve",
            text,
            flags=re.MULTILINE,
        )
        # `if` / `case` / `$AUTO_APPROVE` などのガード語が同一スクリプト内にある場合は
        # 上記マッチが分岐配下にある可能性がある。安全側で「``apply -auto-approve`` の
        # 行が出現する場合は、その上方に AUTO_APPROVE 系変数のガードがあること」を要求する。
        if unconditional is not None:
            head = text[: unconditional.start()]
            assert re.search(r"AUTO_APPROVE", head), (
                "swap_video.sh が `terraform apply -auto-approve` を無条件で実行している"
                "（AUTO_APPROVE 変数等のガードが上方に無い。誤 apply リスク）"
            )

    def test_script_supports_auto_approve_flag(self):
        """Given スクリプト本文
        When 全文を読む
        Then ``-auto-approve`` を terraform に渡す経路と ``--auto-approve`` 受け取りが対になっている。

        ユーザーが ``--auto-approve`` を渡した時に Terraform 側へ ``-auto-approve``
        が伝播する経路があること。フラグだけ受け取って何もしない実装になっていないか担保する。
        """
        text = read_file(_SWAP_VIDEO_SCRIPT)
        # ユーザー向けフラグ `--auto-approve` の取り回し
        assert re.search(r"--auto-approve\b", text), "swap_video.sh が `--auto-approve` 引数を受け取っていない"
        # terraform へ渡す `-auto-approve`（シングルダッシュ）
        assert re.search(r"-auto-approve\b", text), (
            "swap_video.sh が terraform へ `-auto-approve` を渡していない"
            "（ユーザーフラグだけ受け取って Terraform 側に伝播していない）"
        )


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

    def test_script_exists(self):
        """Given リポジトリ
        When ``scripts/streaming/run-ffmpeg.sh`` を探す
        Then 当該ファイルが存在する。

        ExecStart の差し替え先が物理的に欠落すると ``systemctl start`` が
        ``status=203/EXEC`` で fail する。最低限の存在保証。
        """
        assert _RUN_FFMPEG_SCRIPT.exists(), (
            f"{_RUN_FFMPEG_SCRIPT.relative_to(_REPO_ROOT)} が存在しない（#160 ラッパーが未実装）"
        )

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

    def test_script_execs_ffmpeg(self):
        """Given ラッパー本文
        When 全文を読む
        Then ``exec /usr/bin/ffmpeg ...`` で起動している。

        ``exec`` 必須: 中継 shell が残ると systemd の ``Restart`` /
        ``RuntimeMaxSec`` シグナルが ffmpeg に直接届かなくなる。
        plan §「実装ガイドライン」最重要項目。
        """
        text = read_file(_RUN_FFMPEG_SCRIPT)
        assert re.search(r"^\s*exec\s+/usr/bin/ffmpeg\b", text, flags=re.MULTILINE), (
            "run-ffmpeg.sh が `exec /usr/bin/ffmpeg ...` でプロセス置換していない"
            "（中継 shell が残ると systemd シグナルが ffmpeg に直接届かない）"
        )

    def test_script_ffmpeg_argv_matches_pre_wrapper_spec(self):
        """Given ラッパー本文
        When ``exec /usr/bin/ffmpeg ...`` 行を読む
        Then ``-re -stream_loop -1 -i "$VIDEO" -c:v copy -c:a copy -f flv "$RTMP_URL"``
        の引数列が宣言されている (#185 互換)。

        #185 で systemd unit 側に ``-c:v copy -c:a copy``（再エンコードなし、
        動画音声をそのまま送出）を明示分離した意図を後退させない。``-c copy``
        ショートハンドや anullsrc 復活を禁止する。``$VIDEO`` / ``$RTMP_URL`` は
        ``set -u`` 配下の word-splitting 防止のためダブルクォート必須。
        """
        text = read_file(_RUN_FFMPEG_SCRIPT)
        expected = (
            r"exec\s+/usr/bin/ffmpeg\s+-re\s+-stream_loop\s+-1\s+"
            r'-i\s+"\$VIDEO"\s+'
            r"-c:v\s+copy\s+-c:a\s+copy\s+"
            r'-f\s+flv\s+"\$RTMP_URL"\s*$'
        )
        assert re.search(expected, text, flags=re.MULTILINE), (
            "run-ffmpeg.sh の ffmpeg argv が #185 仕様"
            '（-re -stream_loop -1 -i "$VIDEO" -c:v copy -c:a copy -f flv "$RTMP_URL"）'
            "と一致しない"
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
