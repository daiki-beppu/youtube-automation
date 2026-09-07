"""Drift CLI の exit-code と Discord 公開境界 (#4932)。"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tests.helpers.paths import REPO_ROOT

_SCRIPT = REPO_ROOT / ".github/scripts/terraform-drift.sh"


@pytest.mark.parametrize(
    ("event", "plan_exit", "kind", "exit_code", "init_exit", "curl_exit"),
    [
        ("schedule", 2, "drift 検知", 0, 0, 0),
        ("workflow_dispatch", 2, "drift 検知", 0, 0, 0),
        ("push", 2, "apply 待ち", 0, 0, 0),
        ("schedule", 1, "job 失敗", 1, 0, 0),
        ("schedule", 0, None, 0, 0, 0),
        ("schedule", 0, "job 失敗", 1, 1, 0),
        ("schedule", 2, "drift 検知", 22, 0, 22),
    ],
)
def test_drift_notification(
    tmp_path: Path, event: str, plan_exit: int, kind: str | None, exit_code: int, init_exit: int, curl_exit: int
) -> None:
    terraform = tmp_path / "terraform"
    terraform.write_text(
        '#!/bin/bash\nprintf "%s\\n" "$*" >> "$COMMANDS"\n'
        'if [[ "$1" == init ]]; then exit "$INIT_EXIT"; fi\n'
        'echo "PRIVATE_PLAN_BODY"\nexit "$PLAN_EXIT"\n'
    )
    terraform.chmod(0o755)
    curl = tmp_path / "curl"
    curl.write_text('#!/bin/bash\nprintf "%s\\n" "$@" > "$CURL_ARGS"\nexit "$CURL_EXIT"\n')
    curl.chmod(0o755)
    result = subprocess.run(
        ["bash", str(_SCRIPT)],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "HOME": str(tmp_path),
            "TFSTATE_BUCKET": "test-bucket",
            "GITHUB_EVENT_NAME": event,
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_REPOSITORY": "example/repo",
            "GITHUB_RUN_ID": "123",
            "DISCORD_WEBHOOK_URL": "https://discord.invalid/webhook",
            "COMMANDS": str(tmp_path / "commands"),
            "CURL_ARGS": str(tmp_path / "curl_args"),
            "PLAN_EXIT": str(plan_exit),
            "INIT_EXIT": str(init_exit),
            "CURL_EXIT": str(curl_exit),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == exit_code, result.stderr
    commands = ["init -backend-config=bucket=test-bucket -input=false"]
    if init_exit == 0:
        commands.append("plan -detailed-exitcode -lock=false -input=false")
    assert (tmp_path / "commands").read_text().splitlines() == commands
    if kind is None:
        assert not (tmp_path / "curl_args").exists()
        return
    args = (tmp_path / "curl_args").read_text().splitlines()
    payload = json.loads(args[args.index("--data") + 1])
    assert payload == {"content": f"{kind} https://github.com/example/repo/actions/runs/123"}
    assert args[-1] == "https://discord.invalid/webhook"
