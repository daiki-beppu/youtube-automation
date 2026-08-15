"""automation-update の doctor JSON 判定を実 shell 手順で検証する。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.helpers.paths import REPO_ROOT

SKILL_PATH = REPO_ROOT / ".claude/skills/automation/references/update.md"
LEGACY_EXIT_CODE_ONLY_PROCEDURE = "uv run yt-doctor\nuv run yt-channel-status"


def _doctor_procedure() -> str:
    skill = SKILL_PATH.read_text(encoding="utf-8")
    step = skill.split("### Step 3-3. 追加の動作確認（判断を伴うもの）", 1)[1]
    return step.split("```bash\n", 1)[1].split("\n```", 1)[0]


def _write_fake_uv(bin_dir: Path) -> None:
    uv = bin_dir / "uv"
    uv.write_text(
        """#!/bin/sh
if [ "$1 $2 $3" = "run yt-doctor --json" ]; then
  /bin/cat "$DOCTOR_STDOUT"
  /bin/cat "$DOCTOR_STDERR" >&2
  exit "$DOCTOR_EXIT"
fi
if [ "$1 $2" = "run yt-doctor" ]; then
  /bin/cat "$DOCTOR_STDOUT"
  /bin/cat "$DOCTOR_STDERR" >&2
  exit "$DOCTOR_EXIT"
fi
if [ "$1 $2" = "run yt-channel-status" ]; then
  echo channel-status >> "$CALL_LOG"
  exit 0
fi
exit 64
""",
        encoding="utf-8",
    )
    uv.chmod(0o755)


def _run_procedure(
    tmp_path: Path,
    procedure: str,
    *,
    stdout: str,
    stderr: str = "",
    doctor_exit: int = 0,
    install_uv: bool = True,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if install_uv:
        _write_fake_uv(bin_dir)
    (bin_dir / "python3").symlink_to(sys.executable)
    stdout_path = tmp_path / "doctor.stdout"
    stderr_path = tmp_path / "doctor.stderr"
    call_log = tmp_path / "calls.log"
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    env = {
        "PATH": str(bin_dir),
        "DOCTOR_STDOUT": str(stdout_path),
        "DOCTOR_STDERR": str(stderr_path),
        "DOCTOR_EXIT": str(doctor_exit),
        "CALL_LOG": str(call_log),
    }

    result = subprocess.run(
        ["/bin/bash", "-eu", "-o", "pipefail", "-c", f"command -v jq >/dev/null && exit 90\n{procedure}"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    calls = call_log.read_text(encoding="utf-8").splitlines() if call_log.exists() else []
    return result, calls


def _payload(checks: object) -> str:
    return json.dumps({"checks": checks}, ensure_ascii=False)


def test_legacy_exit_code_only_procedure_reproduces_fail_open(tmp_path: Path) -> None:
    result, calls = _run_procedure(
        tmp_path,
        LEGACY_EXIT_CODE_ONLY_PROCEDURE,
        stdout=_payload([{"id": "channel_config", "status": "fail", "message": "broken config"}]),
    )

    assert result.returncode == 0
    assert calls == ["channel-status"]


@pytest.mark.parametrize("status", ["fail", "warn", "unknown", "info", "success", "OK"])
def test_doctor_procedure_stops_on_every_non_ok_channel_config_status(tmp_path: Path, status: str) -> None:
    result, calls = _run_procedure(
        tmp_path,
        _doctor_procedure(),
        stdout=_payload(
            [
                {"id": "channel_config_extra", "status": "ok", "message": "wrong id"},
                {"id": "channel_config", "status": status, "message": f"status={status}"},
            ]
        ),
    )

    assert result.returncode != 0
    assert calls == []
    assert f"status={status}" in result.stderr


@pytest.mark.parametrize(
    ("stdout", "stderr", "doctor_exit"),
    [
        ("{}", "", 0),
        (_payload({}), "", 0),
        (_payload(None), "", 0),
        (_payload([]), "", 0),
        (_payload([{"id": "other", "status": "ok", "message": "irrelevant"}]), "", 0),
        ("not-json", "diagnostic noise", 0),
        ("", "doctor command failed", 7),
        ("{broken", "doctor command failed after partial output", 7),
    ],
)
def test_doctor_procedure_stops_on_missing_malformed_or_command_failure(
    tmp_path: Path,
    stdout: str,
    stderr: str,
    doctor_exit: int,
) -> None:
    result, calls = _run_procedure(
        tmp_path,
        _doctor_procedure(),
        stdout=stdout,
        stderr=stderr,
        doctor_exit=doctor_exit,
    )

    assert result.returncode != 0
    assert calls == []


def test_doctor_procedure_stops_when_command_cannot_start(tmp_path: Path) -> None:
    result, calls = _run_procedure(
        tmp_path,
        _doctor_procedure(),
        stdout="",
        install_uv=False,
    )

    assert result.returncode != 0
    assert calls == []
    assert "起動できません" in result.stderr


@pytest.mark.parametrize("doctor_exit", [0, 9])
def test_doctor_procedure_accepts_exact_ok_even_when_other_checks_set_nonzero_exit(
    tmp_path: Path,
    doctor_exit: int,
) -> None:
    result, calls = _run_procedure(
        tmp_path,
        _doctor_procedure(),
        stdout=_payload(
            [
                {"id": "upload_ready", "status": "fail", "message": "oauth missing"},
                {"id": "channel_config", "status": "ok", "message": "config loaded"},
            ]
        ),
        stderr="other checks failed" if doctor_exit else "",
        doctor_exit=doctor_exit,
    )

    assert result.returncode == 0
    assert calls == ["channel-status"]


def test_doctor_procedure_surfaces_other_actionable_checks_and_actions(tmp_path: Path) -> None:
    result, calls = _run_procedure(
        tmp_path,
        _doctor_procedure(),
        stdout=_payload(
            [
                {"id": "channel_config", "status": "ok", "message": "config loaded"},
                {
                    "id": "upload_ready",
                    "status": "fail",
                    "message": "OAuth\nmissing \x1b[31msecret",
                    "next_action": {"kind": "human-step", "cmd": "uv run yt-doctor --apply\n--json"},
                },
                {"id": "playlist_config", "status": "warn", "message": "playlist missing"},
                {"id": "adc", "status": "unknown", "message": "ADC unknown"},
            ]
        ),
    )

    assert result.returncode == 0
    assert calls == ["channel-status"]
    assert result.stderr.splitlines() == [
        "doctor fail [upload_ready]: OAuth missing [31msecret",
        "doctor next_action [upload_ready].kind: human-step",
        "doctor next_action [upload_ready].cmd: uv run yt-doctor --apply --json",
        "doctor warn [playlist_config]: playlist missing",
        "doctor unknown [adc]: ADC unknown",
    ]
    assert "\x1b" not in result.stderr


def test_doctor_procedure_keeps_action_fields_visible_after_a_long_message(tmp_path: Path) -> None:
    result, calls = _run_procedure(
        tmp_path,
        _doctor_procedure(),
        stdout=_payload(
            [
                {"id": "channel_config", "status": "ok", "message": "config loaded"},
                {
                    "id": "upload_ready",
                    "status": "fail",
                    "message": "m" * 1000,
                    "next_action": {
                        "kind": "human-step",
                        "reason": "OAuth credentials are missing",
                        "execution_owner": "ai-or-setup",
                        "human_role": "browser-authentication",
                        "instructions": "Open the authorization URL\nthen approve access",
                        "url": "https://example.test/oauth?state=visible",
                    },
                },
            ]
        ),
    )

    assert result.returncode == 0
    assert calls == ["channel-status"]
    lines = result.stderr.splitlines()
    assert any(line.startswith("doctor fail [upload_ready]: mmm") and line.endswith("...") for line in lines)
    assert "doctor next_action [upload_ready].kind: human-step" in lines
    assert "doctor next_action [upload_ready].reason: OAuth credentials are missing" in lines
    assert "doctor next_action [upload_ready].execution_owner: ai-or-setup" in lines
    assert "doctor next_action [upload_ready].human_role: browser-authentication" in lines
    assert "doctor next_action [upload_ready].instructions: Open the authorization URL then approve access" in lines
    assert "doctor next_action [upload_ready].url: https://example.test/oauth?state=visible" in lines
    assert all(len(line) <= 240 for line in lines)


def test_doctor_procedure_renders_url_only_action_safely(tmp_path: Path) -> None:
    result, calls = _run_procedure(
        tmp_path,
        _doctor_procedure(),
        stdout=_payload(
            [
                {"id": "channel_config", "status": "ok", "message": "config loaded"},
                {
                    "id": "upload_ready",
                    "status": "warn",
                    "message": "authorization required",
                    "next_action": {
                        "kind": "human-step",
                        "url": "https://example.test/oauth\nforged\x1b[2J" + "u" * 500,
                    },
                },
            ]
        ),
    )

    assert result.returncode == 0
    assert calls == ["channel-status"]
    lines = result.stderr.splitlines()
    url_line = next(line for line in lines if ".url:" in line)
    assert url_line.startswith("doctor next_action [upload_ready].url: https://example.test/oauth forged [2J")
    assert url_line.endswith("...")
    assert "\x1b" not in url_line
    assert len(url_line) <= 240


@pytest.mark.parametrize(
    ("action", "action_check_first"),
    [
        ({"kind": 1, "instructions": []}, False),
        ({"kind": "human-step", "cmd": []}, False),
        ({"kind": "human-step", "url": []}, True),
        ({"kind": "human-step", "reason": 1}, True),
        ({"kind": "human-step", "execution_owner": {}}, True),
        ({"kind": "human-step", "human_role": False}, True),
        ({"kind": "human-step", "instructions": []}, True),
        ({"kind": "human-step", "flag": 1}, True),
    ],
)
def test_doctor_procedure_validates_every_public_action_field_before_channel_decision(
    tmp_path: Path,
    action: dict[str, object],
    action_check_first: bool,
) -> None:
    action_check = {
        "id": "adc",
        "status": "info",
        "message": "informational",
        "next_action": action,
    }
    channel_check = {"id": "channel_config", "status": "ok", "message": "config loaded"}
    checks = [action_check, channel_check] if action_check_first else [channel_check | {"next_action": action}]

    result, calls = _run_procedure(tmp_path, _doctor_procedure(), stdout=_payload(checks))

    assert result.returncode != 0
    assert calls == []
    assert "next_action" in result.stderr


@pytest.mark.parametrize(
    "checks",
    [
        [
            {"id": "channel_config", "status": "ok", "message": "first"},
            {"id": "channel_config", "status": "fail", "message": "second"},
        ],
        [
            {"id": "channel_config", "status": "fail", "message": "first"},
            {"id": "channel_config", "status": "ok", "message": "second"},
        ],
    ],
)
def test_doctor_procedure_rejects_duplicate_channel_config_independent_of_order(
    tmp_path: Path,
    checks: list[dict[str, str]],
) -> None:
    result, calls = _run_procedure(tmp_path, _doctor_procedure(), stdout=_payload(checks))

    assert result.returncode != 0
    assert calls == []
    assert "exactly 1" in result.stderr


@pytest.mark.parametrize(
    "checks",
    [
        ["not-an-object", {"id": "channel_config", "status": "ok", "message": "loaded"}],
        [{"id": 1, "status": "ok", "message": "wrong id type"}],
        [{"id": "channel_config", "status": ["ok"], "message": "wrong status type"}],
        [{"id": "channel_config", "status": "ok", "message": ["wrong message type"]}],
        [
            {"id": "channel_config", "status": "ok", "message": "loaded"},
            {"id": "adc", "status": "warn", "message": "warn", "next_action": "wrong action type"},
        ],
    ],
)
def test_doctor_procedure_rejects_malformed_check_field_types(tmp_path: Path, checks: object) -> None:
    result, calls = _run_procedure(tmp_path, _doctor_procedure(), stdout=_payload(checks))

    assert result.returncode != 0
    assert calls == []


def test_doctor_procedure_renders_success_message_bounded_and_control_safe(tmp_path: Path) -> None:
    unsafe_message = "loaded\nnext-line\x1b[31m" + "x" * 500
    result, calls = _run_procedure(
        tmp_path,
        _doctor_procedure(),
        stdout=_payload([{"id": "channel_config", "status": "ok", "message": unsafe_message}]),
    )

    assert result.returncode == 0
    assert calls == ["channel-status"]
    rendered = result.stdout.strip()
    assert "\x1b" not in rendered
    assert "\n" not in rendered
    assert rendered.startswith("loaded next-line [31m")
    assert rendered.endswith("...")
    assert len(rendered) <= 240


def test_doctor_procedure_renders_failure_message_bounded_and_control_safe(tmp_path: Path) -> None:
    unsafe_message = "broken\r\nforged\x1b[2J" + "y" * 500
    result, calls = _run_procedure(
        tmp_path,
        _doctor_procedure(),
        stdout=_payload([{"id": "channel_config", "status": "fail", "message": unsafe_message}]),
    )

    assert result.returncode != 0
    assert calls == []
    rendered = result.stderr.strip()
    assert "\x1b" not in rendered
    assert "\n" not in rendered
    assert rendered.startswith("broken forged [2J")
    assert rendered.endswith("...")
    assert len(rendered) <= 240
