"""YouTube broadcast recovery timer deployment contract (#3675)."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from tests.helpers.hcl import extract_block, read_file, strip_hcl_comments
from tests.repo.streaming._helpers import _MAIN_TF, _STREAMING_DIR, _VARIABLES_TF

_UNIT = _STREAMING_DIR / "templates" / "youtube-broadcast-recovery.service.tftpl"
_TIMER = _STREAMING_DIR / "templates" / "youtube-broadcast-recovery.timer.tftpl"
_RUNNER = _STREAMING_DIR / "scripts" / "run-broadcast-recovery.sh"
_NOTIFIER = _STREAMING_DIR / "scripts" / "notify-broadcast-recovery.sh"
_DEPLOY = _STREAMING_DIR.parents[2] / ".claude/skills/streaming/references/deploy_broadcast_recovery.sh"


def test_variables_are_opt_in_validated_and_secrets_are_ephemeral() -> None:
    text = strip_hcl_comments(read_file(_VARIABLES_TF))
    enabled = extract_block(text, r'variable\s+"enable_broadcast_recovery"')
    assert enabled is not None
    assert re.search(r"default\s*=\s*false", enabled)

    interval = extract_block(text, r'variable\s+"broadcast_recovery_interval_seconds"')
    assert interval is not None
    assert re.search(r"default\s*=\s*120", interval)
    assert "floor(var.broadcast_recovery_interval_seconds)" in interval

    for name in (
        "broadcast_recovery_youtube_token_json",
        "broadcast_recovery_client_secrets_json",
    ):
        block = extract_block(text, rf'variable\s+"{name}"')
        assert block is not None
        assert re.search(r"sensitive\s*=\s*true", block)
        assert re.search(r"ephemeral\s*=\s*true", block)


def test_resource_is_24_7_only_and_redeploys_without_instance_replacement() -> None:
    text = strip_hcl_comments(read_file(_MAIN_TF))
    block = extract_block(text, r'resource\s+"null_resource"\s+"broadcast_recovery"')
    assert block is not None
    assert re.search(
        r"count\s*=\s*var\.enable_broadcast_recovery\s*&&\s*var\.stream_hours\s*==\s*0\s*\?\s*1\s*:\s*0",
        block,
    )
    assert "depends_on = [null_resource.deploy]" in block

    triggers = extract_block(block, r"triggers")
    assert triggers is not None
    assert re.search(r"credentials\s*=\s*var\.broadcast_recovery_credentials_revision", triggers)
    assert re.search(r"automation_git_ref\s*=\s*var\.broadcast_recovery_automation_git_ref", triggers)
    assert re.search(r"interval_seconds\s*=\s*tostring\(var\.broadcast_recovery_interval_seconds\)", triggers)
    assert "youtube-broadcast-recovery.service.tftpl" in triggers
    assert "youtube-broadcast-recovery.timer.tftpl" in triggers
    assert "run-broadcast-recovery.sh" in triggers
    assert "notify-broadcast-recovery.sh" in triggers
    assert "broadcast_recovery_youtube_token_json" not in triggers
    assert "broadcast_recovery_client_secrets_json" not in triggers


def test_deployment_uses_dedicated_user_0600_credentials_and_safe_cleanup() -> None:
    block = extract_block(
        strip_hcl_comments(read_file(_MAIN_TF)),
        r'resource\s+"null_resource"\s+"broadcast_recovery"',
    )
    assert block is not None
    assert "useradd --system" in block
    assert "youtube-broadcast-recovery" in block
    assert "install -m 0600 -o youtube-broadcast-recovery -g youtube-broadcast-recovery" in block
    assert "/auth/token_streaming.json" in block
    assert "/auth/client_secrets.json" in block
    assert "systemctl enable --now youtube-broadcast-recovery.timer" in block
    assert "systemctl disable --now youtube-broadcast-recovery.timer" in block
    assert "youtube-broadcast-recovery.service" in block
    assert "rm -rf /var/lib/youtube-broadcast-recovery ${self.triggers.install_root}" in block
    assert "rm -rf /run/youtube-broadcast-recovery" in block


def test_systemd_timer_and_service_enforce_gate_and_journal_contract() -> None:
    unit = read_file(_UNIT)
    timer = read_file(_TIMER)
    assert "Type=oneshot" in unit
    assert "User=youtube-broadcast-recovery" in unit
    assert "ExecStart=${install_root}/bin/run-broadcast-recovery.sh" in unit
    assert "ExecStartPost=+${install_root}/bin/notify-broadcast-recovery.sh" in unit
    assert "ReadWritePaths=${state_root}" in unit
    assert "OnBootSec=${interval_seconds}s" in timer
    assert "OnUnitActiveSec=${interval_seconds}s" in timer
    assert "Persistent=false" in timer

    runner = read_file(_RUNNER)
    assert "systemctl is-active --quiet youtube-stream.service" in runner
    assert "yt-stream-broadcast-recover" in runner
    assert "systemd-cat --identifier=youtube-broadcast-recovery" in runner
    assert '--stream-id "$BROADCAST_RECOVERY_STREAM_ID"' in runner
    assert '--title "$BROADCAST_RECOVERY_TITLE"' in runner
    assert "set -x" not in runner

    notifier = read_file(_NOTIFIER)
    assert '"status"[[:space:]]*:[[:space:]]*"recovered"' in notifier
    assert "notify.sh" in notifier
    assert "systemd-cat --identifier=youtube-broadcast-recovery" in notifier


def test_deploy_wrapper_reads_1password_and_unsets_secrets() -> None:
    script = read_file(_DEPLOY)
    assert _DEPLOY.stat().st_mode & 0o111
    assert 'op read "$OP_BROADCAST_RECOVERY_TOKEN_REF"' in script
    assert 'op read "$OP_BROADCAST_RECOVERY_CLIENT_SECRETS_REF"' in script
    assert "export TF_VAR_broadcast_recovery_youtube_token_json" in script
    assert "export TF_VAR_broadcast_recovery_client_secrets_json" in script
    assert "export TF_VAR_broadcast_recovery_credentials_revision" in script
    assert "trap cleanup EXIT HUP INT TERM" in script
    assert 'terraform -chdir="$TF_DIR" plan' in script
    assert 'terraform -chdir="$TF_DIR" apply' in script
    assert "set -x" not in script


def _executable(path: Path, body: str) -> Path:
    path.write_text(f"#!/usr/bin/env bash\nset -eu\n{body}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _runner_env(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    journal = tmp_path / "journal.log"
    cli_calls = tmp_path / "cli-calls.log"
    _executable(bin_dir / "systemd-cat", f"cat >>{journal}")
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "BROADCAST_RECOVERY_RESULT": str(tmp_path / "last-result.json"),
            "BROADCAST_RECOVERY_STREAM_ID_B64": "c3RyZWFtLTE=",
            "BROADCAST_RECOVERY_TITLE_B64": "Q2hhbm5lbCBsaXZl",
            "CLI_CALLS": str(cli_calls),
        }
    )
    return env, journal, cli_calls


def test_runner_is_noop_when_ffmpeg_service_is_inactive(tmp_path: Path) -> None:
    env, journal, cli_calls = _runner_env(tmp_path)
    bin_dir = Path(env["PATH"].split(":", 1)[0])
    _executable(bin_dir / "systemctl", "exit 3")
    cli = _executable(bin_dir / "recover-cli", 'printf "%s\\n" "$*" >>"$CLI_CALLS"')
    env["BROADCAST_RECOVERY_CLI"] = str(cli)

    completed = subprocess.run(["bash", str(_RUNNER)], env=env, check=False, capture_output=True, text=True)

    assert completed.returncode == 0
    result = json.loads(Path(env["BROADCAST_RECOVERY_RESULT"]).read_text(encoding="utf-8"))
    assert result["status"] == "waiting_ingest"
    assert result["action"] == "none_stream_service_inactive"
    assert not cli_calls.exists()
    assert "waiting_ingest" in journal.read_text(encoding="utf-8")


def test_runner_invokes_recovery_with_decoded_stable_identity(tmp_path: Path) -> None:
    env, journal, cli_calls = _runner_env(tmp_path)
    bin_dir = Path(env["PATH"].split(":", 1)[0])
    _executable(bin_dir / "systemctl", "exit 0")
    cli = _executable(
        bin_dir / "recover-cli",
        'printf "%s\\n" "$*" >>"$CLI_CALLS"\nprintf \'{"status":"recovered","action":"created_broadcast"}\\n\'',
    )
    env["BROADCAST_RECOVERY_CLI"] = str(cli)

    completed = subprocess.run(["bash", str(_RUNNER)], env=env, check=False, capture_output=True, text=True)

    assert completed.returncode == 0
    assert "--stream-id stream-1 --title Channel live" in cli_calls.read_text(encoding="utf-8")
    assert json.loads(Path(env["BROADCAST_RECOVERY_RESULT"]).read_text(encoding="utf-8"))["status"] == "recovered"
    assert "created_broadcast" in journal.read_text(encoding="utf-8")


def test_notifier_records_and_sends_only_recovered_result(tmp_path: Path) -> None:
    env, journal, _ = _runner_env(tmp_path)
    notify_calls = tmp_path / "notify-calls.log"
    notify = _executable(tmp_path / "notify.sh", f'printf "%s\\n" "$*" >>{notify_calls}')
    result = tmp_path / "last-result.json"
    result.write_text('{"status":"recovered"}\n', encoding="utf-8")
    env["YOUTUBE_STREAM_NOTIFY_SCRIPT"] = str(notify)

    completed = subprocess.run(["bash", str(_NOTIFIER)], env=env, check=False, capture_output=True, text=True)

    assert completed.returncode == 0
    assert "recovered automatically" in notify_calls.read_text(encoding="utf-8")
    assert "status=recovered" in journal.read_text(encoding="utf-8")
