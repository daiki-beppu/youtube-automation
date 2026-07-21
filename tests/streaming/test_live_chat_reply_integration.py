"""ライブチャット返信 daemon の streaming VPS 統合契約（#2375）。"""

from __future__ import annotations

import re
from pathlib import Path

from tests.helpers.hcl import extract_block, read_file, strip_hcl_comments
from tests.streaming._helpers import _MAIN_TF, _STREAMING_DIR, _VARIABLES_TF, _VERSIONS_TF

_REPO_ROOT = Path(__file__).resolve().parents[2]
_UNIT = _STREAMING_DIR / "templates" / "live-chat-reply.service.tftpl"
_DEPLOY_SCRIPT = _REPO_ROOT / ".claude/skills/streaming/references/deploy_live_chat.sh"


def test_terraform_requires_ephemeral_input_capable_version() -> None:
    assert 'required_version = ">= 1.10"' in read_file(_VERSIONS_TF)


def test_live_chat_is_opt_in_and_secrets_are_ephemeral() -> None:
    text = strip_hcl_comments(read_file(_VARIABLES_TF))
    enabled = extract_block(text, r'variable\s+"enable_live_chat_reply"')
    assert enabled is not None
    assert re.search(r"default\s*=\s*false", enabled)

    for name in (
        "live_chat_youtube_token_json",
        "live_chat_client_secrets_json",
        "live_chat_codex_auth_json",
    ):
        block = extract_block(text, rf'variable\s+"{name}"')
        assert block is not None
        assert re.search(r"sensitive\s*=\s*true", block)
        assert re.search(r"ephemeral\s*=\s*true", block)


def test_live_chat_resource_is_separate_and_does_not_persist_secrets() -> None:
    text = strip_hcl_comments(read_file(_MAIN_TF))
    block = extract_block(text, r'resource\s+"null_resource"\s+"live_chat_reply"')
    assert block is not None
    assert re.search(r"count\s*=\s*var\.enable_live_chat_reply\s*\?\s*1\s*:\s*0", block)
    assert "depends_on = [null_resource.deploy]" in block

    triggers = extract_block(block, r"triggers")
    assert triggers is not None
    assert "live_chat_youtube_token_json" not in triggers
    assert "live_chat_client_secrets_json" not in triggers
    assert "live_chat_codex_auth_json" not in triggers
    assert "credentials         = var.live_chat_credentials_revision" in triggers

    assert "install -m 0600 -o live-chat-reply -g live-chat-reply" in block
    assert "systemctl is-active --quiet live-chat-reply" in block
    assert "systemctl disable --now live-chat-reply" in block
    assert "rm -rf /var/lib/live-chat-reply ${self.triggers.install_root}" in block


def test_systemd_unit_restarts_without_coupling_stream_lifecycle() -> None:
    unit = read_file(_UNIT)
    assert "User=live-chat-reply" in unit
    assert "Restart=on-failure" in unit
    assert "NoNewPrivileges=true" in unit
    assert "ProtectSystem=strict" in unit
    assert "ReadWritePaths=${state_root}" in unit
    assert "Requires=youtube-stream.service" not in unit
    assert "PartOf=youtube-stream.service" not in unit


def test_deploy_script_reads_1password_and_cleans_ephemeral_env() -> None:
    script = read_file(_DEPLOY_SCRIPT)
    assert _DEPLOY_SCRIPT.stat().st_mode & 0o111
    assert "set -euo pipefail" in script
    assert 'op read "$OP_LIVE_CHAT_TOKEN_REF"' in script
    assert 'op read "$OP_LIVE_CHAT_CLIENT_SECRETS_REF"' in script
    assert 'op read "$OP_CODEX_AUTH_REF"' in script
    assert "export TF_VAR_live_chat_youtube_token_json" in script
    assert "export TF_VAR_live_chat_credentials_revision" in script
    assert "trap cleanup EXIT HUP INT TERM" in script
    assert 'terraform -chdir="$TF_DIR" plan' in script
    assert 'terraform -chdir="$TF_DIR" apply' in script
    assert "set -x" not in script
