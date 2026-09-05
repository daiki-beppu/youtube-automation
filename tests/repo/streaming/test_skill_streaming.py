"""``.claude/skills/streaming/`` 配下の SKILL.md / README の検証テスト。

- streaming SKILL.md の firewall / ssh-agent 言及
- streaming README.md の運用記述（firewall / video swap など）
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.hcl import read_file
from tests.helpers.paths import REPO_ROOT
from tests.repo.streaming._helpers import (
    _STREAMING_README,
    _STREAMING_SKILL,
    _TFSTATE_GCS_OBJECT,
)

# ============================================================================
# .claude/skills/streaming/SKILL.md — #153 allowed_ssh_cidr の operator 索引
# ============================================================================


class TestStreamingSkillFirewall:
    """``.claude/skills/streaming/SKILL.md`` の #153 ``allowed_ssh_cidr`` 言及。

    SKILL.md は operator 索引。明示しないと §1 初回構築の ``terraform apply`` が
    SSH 到達不可で詰むため、必須項目として CIDR を記載する必要がある。
    本テストは raw text のキーワード包含のみ検証する（章立て自由度を残す）。
    """

    def test_mentions_allowed_ssh_cidr(self):
        """Given SKILL.md
        When 全文を読む
        Then ``allowed_ssh_cidr`` キーワードの言及がある (R8, H12)。

        operator 索引からの到達経路。明示しないと §1 初回構築の terraform apply が
        SSH 到達不可で詰む。
        """
        text = read_file(_STREAMING_SKILL)
        assert "allowed_ssh_cidr" in text, (
            "SKILL.md に allowed_ssh_cidr の言及が無い"
            "（operator が必須項目を発見できず、§1 初回構築で SSH 到達不可になる）"
        )


# ============================================================================
# .claude/skills/streaming/SKILL.md — #154 ssh-agent 切替の operator 索引
# ============================================================================


class TestStreamingSkillSshAgent:
    """``.claude/skills/streaming/SKILL.md`` の #154 ssh-agent 経路の言及。

    SKILL.md は operator 索引。``connection.agent = true`` に切り替わったため、
    operator が ``terraform apply`` 前に ``ssh-add`` で鍵を登録する必要がある。
    本テストは raw text のキーワード包含のみ検証する（章立て自由度を残す）。
    """

    def test_does_not_mention_ssh_priv_key_path(self):
        """Given SKILL.md
        When 全文を読む
        Then ``ssh_priv_key_path`` キーワードがどこにも含まれていない。

        #154 で variables.tf から撤去された変数。SKILL.md に残ると README / SKILL.md の整合が
        崩れ、operator が古い前提に従って詰まる。
        """
        text = read_file(_STREAMING_SKILL)
        assert "ssh_priv_key_path" not in text, (
            "SKILL.md に ssh_priv_key_path の言及が残っている（撤去済み変数。README / SKILL 不整合）"
        )

    def test_mentions_ssh_add_for_agent_setup(self):
        """Given SKILL.md
        When 全文を読む
        Then ``ssh-add`` コマンドの言及がある（ssh-agent への鍵登録手順）。

        #154 で ``connection.agent = true`` に切り替えたため、operator が ``terraform apply`` 前に
        ssh-agent へ鍵を登録する必要がある。SKILL.md 経由のオペレーターも起動条件を把握できる
        必要があるため、README と同じく ``ssh-add`` の緩い包含検査で担保する。
        """
        text = read_file(_STREAMING_SKILL)
        assert "ssh-add" in text, (
            "SKILL.md に ssh-add の言及が無い"
            "（operator が ssh-agent 登録手順を SKILL.md から辿れず terraform apply が失敗する）"
        )

    def test_archive_check_requires_expected_in_skill_quick_reference(self):
        """Given SKILL.md
        When archive check の操作入口を読む
        Then 24/7 デフォルトと混同しないよう --expected 2 を明示している。
        """
        text = read_file(_STREAMING_SKILL)
        assert "yt-stream-archive-check --expected 2" in text
        assert "`stream_hours=11` / `break_hours=1` 運用" in text

    def test_skill_documents_source_video_preflight(self):
        """Given SKILL.md
        When 初回構築の操作入口を読む
        Then 配信元 MP4 の ffprobe preflight と再エンコード例が分かる。
        """
        text = read_file(_STREAMING_SKILL)

        assert "月間帯域見積もり用の MP4 実測" in text
        assert "ffprobe" in text
        assert "-c:v copy" in text
        assert "4,500 Kbps" in text
        assert "-profile:v high" in text
        assert "1.52 TB" in text
        assert "preflight 合否は `terraform plan` / `apply` の stream-level 検証" in text


class TestStreamingSkillWorkspaces:
    """Quick Reference から README 正本の workspace 手順へ到達できる契約。"""

    def test_quick_reference_indexes_workspace_operations_and_variable_warning(self):
        """workspace 操作、変数再注入警告、詳細正本への参照を確認する。"""
        text = read_file(_STREAMING_SKILL)
        match = re.search(
            r"^## Quick Reference\s*$\n(.*?)(?=^##\s|\Z)",
            text,
            flags=re.MULTILINE | re.DOTALL,
        )
        assert match is not None, "streaming SKILL.md に Quick Reference 節が無い"
        section = match.group(1)

        for required in (
            "workspace list",
            "workspace show",
            "workspace new <workspace>",
            "workspace select <workspace>",
            "jq -r '.backend.config.bucket'",
            'gcloud storage ls "gs://${bucket}/streaming/${workspace}.tfstate"',
            "TF_VAR_video_path",
            "TF_VAR_stream_key",
            "TF_VAR_discord_webhook_url",
            "再注入",
            "$TF_DIR/README.md",
            "チャンネル別 Terraform workspace 運用",
        ):
            assert required in section, f"Quick Reference に {required!r} が無い"

    @pytest.mark.parametrize("upstream_available", [True, False])
    def test_distributed_skill_resolves_upstream_readme_or_stops(self, tmp_path: Path, upstream_available: bool):
        downstream = tmp_path / "channel"
        skill_dir = downstream / ".claude/skills/streaming"
        shutil.copytree(_STREAMING_SKILL.parent, skill_dir)
        skill_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        local_links = re.findall(r"\]\(([^)]+\.md)(?:#[^)]*)?\)", skill_text)
        assert local_links
        for link in local_links:
            assert (skill_dir / link).is_file(), f"配布先から参照できない: {link}"
        reference = skill_dir / "references/upstream-checkout.md"
        assert reference.relative_to(skill_dir).as_posix() in local_links
        bash_blocks = re.findall(r"```bash\n(.*?)```", reference.read_text(encoding="utf-8"), re.DOTALL)
        assert len(bash_blocks) == 1
        upstream = REPO_ROOT if upstream_available else tmp_path / "missing-upstream"
        if not upstream_available:
            upstream.mkdir()
        result = subprocess.run(
            ["bash", "-c", bash_blocks[0] + '\nprintf "%s\\n" "$TF_DIR/README.md"'],
            cwd=downstream,
            env={"PATH": os.defpath, "AUTOMATION_ROOT": str(upstream), "CHANNEL_DIR": str(downstream)},
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        assert not (downstream / "infra").exists()
        if upstream_available:
            assert result.returncode == 0, result.stderr
            resolved_readme = Path(result.stdout.strip())
            assert resolved_readme == _STREAMING_README
            assert "## チャンネル別 Terraform workspace 運用" in resolved_readme.read_text(encoding="utf-8")
        else:
            assert result.returncode != 0
            assert "STOP:" in result.stderr
            assert result.stdout == ""


# ============================================================================
# infra/terraform/streaming/README.md — #125 新規ドキュメント
# ============================================================================


class TestStreamingReadme:
    """``infra/terraform/streaming/README.md`` の最低限の記載項目（#125）。

    order.md「secret 注入手順を README に記載」を満たし、運用者が ``terraform apply`` から
    動作確認まで辿れる導線を提供する。

    本テストは README の文章スタイルや章立て順序は問わない。**運用上クリティカルなキーワード**の
    包含のみ検証する（執筆の自由度を残す）。
    """

    def test_mentions_tf_var_stream_key(self):
        """Given README
        When 全文を読む
        Then ``TF_VAR_stream_key`` 環境変数の言及がある（secret 注入の入口）。
        """
        text = read_file(_STREAMING_README)
        assert "TF_VAR_stream_key" in text, "README に TF_VAR_stream_key の言及が無い（secret 注入手順が辿れない）"

    def test_mentions_tf_var_vultr_api_key(self):
        """Given README
        When 全文を読む
        Then ``TF_VAR_vultr_api_key`` の言及がある（既存 secret も再掲する）。
        """
        text = read_file(_STREAMING_README)
        assert "TF_VAR_vultr_api_key" in text, (
            "README に TF_VAR_vultr_api_key の言及が無い（運用者が必要 env を網羅できない）"
        )

    def test_documents_source_video_preflight(self):
        """Given README
        When 配信元動画のプリフライト説明を読む
        Then ffprobe / -c:v copy / keyframe / bitrate / 推奨再エンコード例が記載されている。
        """
        text = read_file(_STREAMING_README)

        assert "配信元動画のプリフライト" in text
        assert "ffprobe" in text
        assert "-c:v copy" in text
        assert "キーフレーム最大間隔" in text
        assert "4,500 Kbps" in text
        assert "-profile:v high" in text
        assert "1.52 TB" in text
        assert "container 全体の平均 bitrate" in text
        assert "preflight の合否確認は `terraform plan` / `apply` の stream-level 検証" in text

    def test_mentions_op_read_for_secret_injection(self):
        """Given README
        When 全文を読む
        Then ``op read`` による 1Password CLI 経由の secret 注入手順がある。
        """
        text = read_file(_STREAMING_README)
        assert "op read" in text, "README に op read（1Password CLI）の手順が無い"

    def test_mentions_terraform_apply_command(self):
        """Given README
        When 全文を読む
        Then ``terraform apply`` 実行手順が含まれている。
        """
        text = read_file(_STREAMING_README)
        assert re.search(r"terraform[^\n]*apply", text), "README に terraform apply の実行コマンドが書かれていない"

    def test_documents_encrypted_remote_tfstate_backend(self):
        """Given README
        When tfstate の説明を読む
        Then remote backend と暗号化 state の保存先が説明されている。
        """
        text = read_file(_STREAMING_README)
        assert 'backend "gcs"' in text, 'README に backend "gcs" の説明が無い'
        assert "Google 管理鍵" in text, "README に Google 管理鍵による暗号化の説明が無い"
        assert _TFSTATE_GCS_OBJECT in text, "README に streaming state object の説明が無い"
        assert 'terraform init -backend-config="bucket=<bucket-name>" -migrate-state' in text, (
            "README に GCS backend への state 移行手順が無い"
        )

    def test_documents_sensitive_is_cli_mask_only(self):
        """Given README
        When sensitive と tfstate の説明を読む
        Then sensitive=true は CLI 出力マスクのみであると説明されている。
        """
        text = read_file(_STREAMING_README)
        assert "CLI 出力マスクのみ" in text, "README に sensitive=true が CLI マスクのみである説明が無い"
        assert "tfstate JSON の値を暗号化しない" in text, (
            "README に sensitive=true が tfstate JSON を暗号化しない説明が無い"
        )

    def test_does_not_describe_nonsensitive_hash_as_unconditionally_safe(self):
        """Given README
        When nonsensitive(sha256(...)) の説明を読む
        Then hash 化の安全性を高エントロピー secret に限定している。
        """
        text = read_file(_STREAMING_README)
        assert "脱 sensitive 安全" not in text, "README が nonsensitive(sha256(...)) を常に安全と誤読させる"
        assert "高エントロピー" in text, "README に hash 化の前提が高エントロピー secret である説明が無い"
        assert "低エントロピー値" in text, "README に低エントロピー値の hash 化が secret 保護でない説明が無い"

    def test_mentions_systemctl_status_for_verification(self):
        """Given README の動作確認節
        When サービス・サイクル・ログの確認手順を読む
        Then 各確認目的と実行コマンドが同じ節で対応付く。
        """
        text = read_file(_STREAMING_README)
        match = re.search(
            r"^## 動作確認\s*$\n(.*?)(?=^##\s|\Z)",
            text,
            flags=re.MULTILINE | re.DOTALL,
        )
        assert match is not None, "README に動作確認節が無い"
        section = match.group(1)
        assert (
            "# サービス状態（active / inactive / failed）\n"
            "ssh -i ~/.ssh/yt_stream_key root@<instance_ip> systemctl status youtube-stream"
        ) in section
        assert (
            "# 配信サイクル設定が効いているか確認\n"
            "ssh -i ~/.ssh/yt_stream_key root@<instance_ip> systemctl show youtube-stream "
            "| grep -E 'RuntimeMaxUSec|RestartUSec'"
        ) in section
        assert (
            "# リアルタイムログ（ffmpeg の出力）\n"
            "ssh -i ~/.ssh/yt_stream_key root@<instance_ip> journalctl -u youtube-stream -f"
        ) in section

    def test_mentions_default_24_7_and_optional_11h_1h_streaming_cycle(self):
        """Given README
        When 全文を読む
        Then デフォルト 24/7 と任意の 11h / 1h サイクルの説明が含まれている。

        利用者が 0 / 0 と 11 / 1 の挙動差を理解できる必要がある。
        """
        text = read_file(_STREAMING_README)
        assert "24/7" in text, "README に 24/7 連続配信の説明が無い"
        assert "stream_hours=0" in text, "README に stream_hours=0 の説明が無い"
        assert "break_hours=0" in text, "README に break_hours=0 の説明が無い"
        assert "stream_hours=11" in text, "README に 11h サイクルへ切り替える説明が無い"
        assert "break_hours=1" in text, "README に 1h 休止へ切り替える説明が無い"

    def test_archive_check_is_documented_as_archive_mode_only(self):
        """Given README
        When 帯域・アーカイブ監視の説明を読む
        Then archive shortage 判定は 11/1 運用時の指標として説明されている。
        """
        text = read_file(_STREAMING_README)
        assert "月次レポート内のアーカイブ件数・稼働率は `stream_hours=11` / `break_hours=1` 運用時の指標" in text
        assert "24/7 連続配信では shortage 判定に使わない" in text

    def test_does_not_contain_plaintext_stream_key(self):
        """Given README
        When 全文を読む
        Then 実 stream key っぽいリテラル（``rtmp://...`` の URL 末尾値）が直書きされていない。

        ドキュメントとしての例示でも、実際の YouTube stream key 形式（連続英数字）を書かないこと。
        """
        text = read_file(_STREAMING_README)
        # rtmp://a.rtmp.youtube.com/live2/<英数字 8 文字以上> っぽいパターンを検出
        assert not re.search(
            r"rtmp://[\w.]+/live2/[A-Za-z0-9]{8,}",
            text,
        ), "README に実 stream key を含む rtmp URL が書かれている可能性（漏洩リスク）"

    def test_does_not_mention_ssh_priv_key_path(self):
        """Given README
        When 全文を読む
        Then ``ssh_priv_key_path`` キーワードがどこにも含まれていない。

        #154 で variables.tf から撤去された変数。README に残るとドキュメント / 実装乖離になり、
        運用者が「設定したのに反映されない」混乱を起こす。仕様準拠（README ↔ 実装）の保証。
        """
        text = read_file(_STREAMING_README)
        assert "ssh_priv_key_path" not in text, (
            "README に ssh_priv_key_path の言及が残っている（撤去済み変数。ドキュメント / 実装乖離）"
        )

    def test_mentions_ssh_add_for_agent_setup(self):
        """Given README
        When 全文を読む
        Then ``ssh-add`` コマンドの言及がある（ssh-agent への鍵登録手順）。

        #154 で ``connection.agent = true`` に切り替えたため、``terraform apply`` 成功の起動条件が
        「秘密鍵ファイルの存在」から「ssh-agent に鍵が登録されていること」に変わる。
        運用者が前提を満たせる導線として ``ssh-add`` 系コマンドの言及が必要。
        既存 ``test_mentions_*`` 系の緩い包含検査スタイルを踏襲（章立て自由度を残す）。
        """
        text = read_file(_STREAMING_README)
        assert "ssh-add" in text, (
            "README に ssh-add の言及が無い（ssh-agent 登録手順が辿れず terraform apply が失敗する）"
        )

    def test_mentions_host_key_verification(self):
        """Given README
        When 前提セクション周辺を読む
        Then host_key と ssh_keys による host 鍵固定化の説明がある。
        """
        text = read_file(_STREAMING_README)
        assert "host_key" in text, "README に host_key の言及が無い（検証有効化の説明不足）"
        assert "ssh_keys" in text, "README に ssh_keys の言及が無い（host 鍵配布経路が辿れない）"

    def test_tfstate_section_mentions_tls_private_key(self):
        """Given README
        When tfstate と secret の説明を読む
        Then tls_private_key.ssh_host.private_key_openssh の注意がある。
        """
        text = read_file(_STREAMING_README)
        assert "tls_private_key.ssh_host.private_key_openssh" in text, (
            "README の tfstate 注意書きに host 鍵秘密鍵の保存先が明記されていない"
        )


class TestStreamingReadmeWorkspaces:
    """README を正本とする、チャンネル別 Terraform workspace の安全契約。"""

    def test_documents_workspace_switch_and_fail_safe_apply_sequence(self):
        """workspace とチャンネル変数を照合した後だけ apply する手順を固定する。"""
        text = read_file(_STREAMING_README)
        match = re.search(
            r"^## チャンネル別 Terraform workspace 運用\s*$\n(.*?)(?=^##\s|\Z)",
            text,
            flags=re.MULTILINE | re.DOTALL,
        )
        assert match is not None, "README にチャンネル別 Terraform workspace 運用節が無い"
        section = match.group(1)

        for required in (
            "terraform workspace list",
            "terraform workspace new <workspace>",
            "terraform workspace select <workspace>",
            "streaming/<workspace>.tfstate",
            "TF_VAR_video_path",
            "TF_VAR_stream_key",
            "TF_VAR_discord_webhook_url",
            "terraform workspace show",
            "terraform state list",
            "terraform plan",
            "terraform apply",
            "apply しない",
        ):
            assert required in section, f"workspace 運用節に {required!r} が無い"

        show_index = section.index("terraform workspace show")
        state_index = section.index("terraform state list")
        plan_index = section.index("terraform plan")
        apply_index = section.index("terraform apply")
        assert show_index < state_index < plan_index < apply_index


class TestStreamingReadmeUnmanagedImport:
    """既存 Vultr リソースを破壊せず workspace へ import する運用契約。"""

    def test_documents_dependency_order_ids_and_stop_conditions(self):
        """import 順序・ID 形式・未管理 resource・replace 時の停止を固定する。"""
        text = read_file(_STREAMING_README)
        match = re.search(
            r"^## 既存 Vultr リソースの import\s*$\n(.*?)(?=^##\s|\Z)",
            text,
            flags=re.MULTILINE | re.DOTALL,
        )
        assert match is not None, "README に既存 Vultr リソースの import 節が無い"
        section = match.group(1)

        commands = (
            "terraform import vultr_firewall_group.stream <firewall-group-id>",
            "terraform import 'vultr_firewall_rule.ssh[\"<allowed-ssh-cidr>\"]' "
            "'<firewall-group-id>,<firewall-rule-id>'",
            "terraform import vultr_ssh_key.this <ssh-key-id>",
            "terraform import vultr_instance.this <instance-id>",
        )
        for required in (
            "terraform workspace show",
            *commands,
            "tls_private_key.ssh_host",
            "null_resource.deploy",
            "tls_private_key.ssh_host will be created",
            "null_resource.deploy will be created",
            "この 2 件の `+ create` だけ",
            "同じ plan に `vultr_instance.this must be replaced` が併記",
            "user_data",
            "host_key",
            "terraform plan",
            "apply しない",
        ):
            assert required in section, f"既存 resource の import 節に {required!r} が無い"

        positions = [section.index(command) for command in commands]
        assert section.index("terraform workspace show") < positions[0]
        assert positions == sorted(positions)
        assert positions[-1] < section.index("terraform plan")


# ============================================================================
# infra/terraform/streaming/README.md — #111 動画差し替え手順
# ============================================================================


class TestStreamingReadmeVideoSwap:
    """``infra/terraform/streaming/README.md`` 「動画の差し替え手順」セクション（#111）。

    依存 #125 で実装済みの ``null_resource.deploy`` (filemd5 trigger / current.mp4 上書き /
    systemctl restart) を運用フェーズで使うための手順ドキュメントを検証する。

    本テストは README の章立て順序や文章スタイルを問わず、運用上クリティカルなキーワードの
    包含のみ検証する（執筆の自由度を残す）。order.md「動画差し替え手順」のタスク項目と
    plan.md §write_tests ステップ指示に対応。
    """

    def test_has_video_swap_section_heading(self):
        """Given README
        When 全文を読む
        Then 「動画の差し替え」を含む Markdown 見出し（``##`` / ``###``）が存在する。

        運用者が見出しから瞬時に当該手順に到達できるよう、章として独立している必要がある。
        """
        text = read_file(_STREAMING_README)
        # ## または ### 行で「動画の差し替え」または「動画差し替え」を含む見出しがあること
        assert re.search(
            r"^#{2,3}\s+[^\n]*動画(の)?差し替え",
            text,
            flags=re.MULTILINE,
        ), "README に「動画(の)?差し替え」を含む ## / ### 見出しが無い（運用者が章を辿れない）"

    def test_mentions_tf_var_video_path(self):
        """Given README
        When 全文を読む
        Then ``TF_VAR_video_path`` 環境変数の言及がある。

        差し替え時に新しい動画パスを Terraform に渡すための env 名を運用者が
        正確に知る必要がある（typo すれば ``var.video_path is required`` で失敗する）。
        """
        text = read_file(_STREAMING_README)
        assert "TF_VAR_video_path" in text, (
            "README に TF_VAR_video_path の言及が無い（差し替え時の env 注入手順が辿れない）"
        )

    def test_mentions_terraform_plan_for_diff_check(self):
        """Given README
        When 全文を読む
        Then ``terraform ... plan`` の差分確認手順が記載されている。

        order.md「``terraform plan`` で **新動画 only** の差分が出ることの確認手順」要件。
        apply 前に意図しないリソース（``vultr_instance`` 等）の replace を察知する導線。
        """
        text = read_file(_STREAMING_README)
        assert re.search(r"terraform[^\n]*plan", text), (
            "README に terraform plan の差分確認手順が無い（apply 前の安全確認導線が欠落）"
        )

    def test_mentions_idle_window_for_zero_downtime(self):
        """Given README
        When 全文を読む
        Then 「休止」または「ダウンタイム」または「0 秒」のいずれかが書かれている。

        order.md「休止時間に実施するのが視聴者には透明」運用 tips 要件。
        運用者が「いつ apply すべきか」の判断軸を README から得られる必要がある。
        """
        text = read_file(_STREAMING_README)
        has_idle = "休止" in text
        has_downtime = "ダウンタイム" in text
        has_zero_sec = "0 秒" in text or "0秒" in text
        assert has_idle or has_downtime or has_zero_sec, (
            "README に休止時間 / ダウンタイム / 0 秒 のいずれの運用 tips も無い"
            "（視聴者影響を踏まえた実施タイミングの判断軸が欠落）"
        )

    def test_mentions_idempotency_with_filemd5(self):
        """Given README
        When 全文を読む
        Then 「filemd5」または「no-op」または「冪等」のいずれかが書かれている。

        order.md テスト第 3 項「同じ動画で再 apply → no-op（filemd5 不変）」の運用根拠。
        運用者が「動かない」と誤認しないよう、冪等性の仕組みを README から読み取れる必要がある。
        """
        text = read_file(_STREAMING_README)
        has_filemd5 = "filemd5" in text
        has_noop = "no-op" in text
        has_idempotent = "冪等" in text
        assert has_filemd5 or has_noop or has_idempotent, (
            "README に filemd5 / no-op / 冪等 のいずれの言及も無い"
            "（同一動画で再 apply した時の挙動が運用者に伝わらない）"
        )

    def test_mentions_current_mp4_overwrite(self):
        """Given README
        When 全文を読む
        Then ``current.mp4`` への上書き（旧動画削除の自然解消）に触れている。

        order.md 完了条件「旧動画は VPS 上に明示的に削除する仕組みを用意」を、
        単一ファイル方式（``provisioner "file"`` が毎回上書き）で満たす根拠を README に明記する。
        """
        text = read_file(_STREAMING_README)
        assert "current.mp4" in text, (
            "README に current.mp4 への上書きの言及が無い（旧動画が自然消去される根拠が辿れない）"
        )

    def test_mentions_swap_video_script(self):
        """Given README
        When 全文を読む
        Then ``swap_video.sh`` への到達導線（言及）が存在する。

        order.md「スクリプト化（任意）: ``scripts/streaming/swap_video.sh``」「1 コマンド
        ラッパーとして提供」要件。ラッパーを追加しても README から発見できなければ運用者は
        到達できないため、README が `swap_video.sh` という識別子に言及していることを担保する。
        """
        text = read_file(_STREAMING_README)
        assert "swap_video.sh" in text, (
            "README に swap_video.sh の言及が無い（1 コマンドラッパーへの到達導線が欠落し、運用者が発見できない）"
        )


# ============================================================================
# infra/terraform/streaming/README.md — #153 allowed_ssh_cidr の手順記載
# ============================================================================


class TestStreamingReadmeFirewall:
    """``infra/terraform/streaming/README.md`` の #153 ``allowed_ssh_cidr`` 手順言及。

    operator が CIDR 設定手順（IP 取得 → /32 化 → tfvars 記載）を辿れる導線を担保する。
    本テストは README の章立て順序や文章スタイルは問わず、運用上クリティカルなキーワード
    包含のみ検証する（執筆の自由度を残す）。
    """

    def test_mentions_allowed_ssh_cidr(self):
        """Given README
        When 全文を読む
        Then ``allowed_ssh_cidr`` キーワードの言及がある (R7, H10)。

        手順書からの到達経路。設定 key 名を README から発見できる必要がある。
        """
        text = read_file(_STREAMING_README)
        assert "allowed_ssh_cidr" in text, (
            "README に allowed_ssh_cidr の言及が無い（operator が必須項目を発見できず、CIDR 設定手順が辿れない）"
        )

    def test_mentions_ip_acquisition_path(self):
        """Given README
        When 全文を読む
        Then IP 取得導線（``/32`` / ``ifconfig.me`` / ``curl`` のいずれか）に言及している
        (R7, H11)。

        CIDR 化手順を運用者が辿れる必要がある。固定文言は要求しないが、
        「自分の IP を /32 で書く」という作業に対応するヒント語句が必須。
        """
        text = read_file(_STREAMING_README)
        has_slash_32 = "/32" in text
        has_ifconfig_me = "ifconfig.me" in text
        has_curl = "curl" in text
        assert has_slash_32 or has_ifconfig_me or has_curl, (
            "README に /32 / ifconfig.me / curl のいずれの言及も無い"
            "（CIDR 化手順 = IP 取得 → /32 化 が運用者に伝わらない）"
        )
