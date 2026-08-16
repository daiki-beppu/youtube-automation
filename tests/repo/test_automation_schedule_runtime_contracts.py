"""Executable contracts for `/wf-new --schedule` distributed references."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.helpers.paths import REPO_ROOT

ROOT = REPO_ROOT
REFERENCES = ROOT / ".claude" / "skills" / "wf-new" / "references"


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _run(script: str, *args: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", str(REFERENCES / script), *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _load(name: str):
    path = REFERENCES / name
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_detect_runtime_executes_config_product_os_auth_and_notification_branches(tmp_path: Path) -> None:
    (tmp_path / "config" / "channel").mkdir(parents=True)
    (tmp_path / "config" / "channel" / "workflow.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "auth").mkdir()
    (tmp_path / "auth" / "token.json").write_text("{}\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(bin_dir / "uv", "#!/bin/sh\necho 'uv 0.test'\n")
    _write_executable(bin_dir / "uname", "#!/bin/sh\necho Darwin\n")
    _write_executable(bin_dir / "launchctl", "#!/bin/sh\nexit 0\n")
    _write_executable(bin_dir / "osascript", "#!/bin/sh\nexit 0\n")
    env = os.environ.copy()
    env.update({"PATH": f"{bin_dir}:/usr/bin:/bin", "CODEX_THREAD_ID": "thread"})
    env.pop("CLAUDECODE", None)

    result = _run("detect_runtime.sh", cwd=tmp_path, env=env)

    assert result.returncode == 0
    rows = {parts[1]: (parts[0], parts[2]) for line in result.stdout.splitlines() if (parts := line.split("\t", 2))}
    assert rows["config-workflow"][0] == "ok"
    assert rows["uv"][0] == "ok"
    assert rows["product-codex"][0] == "ok"
    assert "launchd 利用可" in rows["os-fallback"][1]
    assert rows["auth"][0] == "ok"
    assert rows["notification"][0] == "ok"


def test_detect_runtime_missing_required_inputs_exits_one_and_claude_linux_is_observable(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(bin_dir / "uname", "#!/bin/sh\necho Linux\n")
    env = os.environ.copy()
    env.update({"PATH": f"{bin_dir}:/usr/bin:/bin", "CLAUDECODE": "1"})
    env.pop("CODEX_THREAD_ID", None)

    result = _run("detect_runtime.sh", cwd=tmp_path, env=env)

    assert result.returncode == 1
    assert "fail\tconfig-workflow" in result.stdout
    assert "fail\tuv" in result.stdout
    assert "ok\tproduct-claude" in result.stdout
    assert "cron" in result.stdout
    assert "warn\tauth" in result.stdout


def _scheduled_env(tmp_path: Path, config: dict[str, object]) -> tuple[dict[str, str], Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "runtime-calls.txt"
    counter = tmp_path / "counter"
    _write_executable(
        bin_dir / "uv",
        """#!/bin/bash
if [[ "$*" == *"schedule_config.py show"* ]]; then
  printf '%s\n' "$SCHEDULE_JSON"
  exit "${FAKE_CONFIG_RC:-0}"
fi
if [[ "$*" == "run yt-oauth --refresh-only" ]]; then
  printf 'oauth:%s\n' "$*" >> "$RUNTIME_CALLS"
  exit "${FAKE_OAUTH_RC:-0}"
fi
if [[ "$1" == "run" && "$2" == "python" ]]; then
  shift 2
  exec python3 "$@"
fi
exit 2
""",
    )
    for runtime in ("codex", "claude"):
        _write_executable(
            bin_dir / runtime,
            f"""#!/bin/bash
printf '{runtime}:%s\n' "$*" >> "$RUNTIME_CALLS"
count=0
[[ -f "$RUNTIME_COUNTER" ]] && count="$(cat "$RUNTIME_COUNTER")"
count=$((count + 1))
printf '%s' "$count" > "$RUNTIME_COUNTER"
[[ "$count" -le "${{RUNTIME_FAILS:-0}}" ]] && exit 7
exit 0
""",
        )
    _write_executable(bin_dir / "sleep", '#!/bin/bash\nprintf \'sleep:%s\\n\' "$*" >> "$RUNTIME_CALLS"\n')
    _write_executable(bin_dir / "osascript", '#!/bin/bash\nprintf \'notify:%s\\n\' "$*" >> "$RUNTIME_CALLS"\n')
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "SCHEDULE_JSON": json.dumps(config),
            "RUNTIME_CALLS": str(calls),
            "RUNTIME_COUNTER": str(counter),
        }
    )
    return env, calls, counter


def _config(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "enabled": True,
        "target_workflow": "wf-new --auto",
        "max_retries": 0,
        "retry_delay_seconds": 3,
        "prevent_concurrent_runs": True,
        "notification": "terminal",
        "allow_external_publish": False,
    }
    value.update(overrides)
    return value


def test_run_scheduled_skips_disabled_and_live_lock_without_runtime_call(tmp_path: Path) -> None:
    env, calls, _ = _scheduled_env(tmp_path, _config(enabled=False))
    disabled = _run(
        "run_scheduled.sh",
        "--channel-dir",
        str(tmp_path),
        "--runtime",
        "codex",
        cwd=tmp_path,
        env=env,
    )
    assert disabled.returncode == 0
    assert not calls.exists()

    env["SCHEDULE_JSON"] = json.dumps(_config())
    lock = tmp_path / ".automation-schedule" / "lock"
    lock.mkdir(parents=True)
    (lock / "pid").write_text(str(os.getpid()), encoding="utf-8")
    live = _run(
        "run_scheduled.sh",
        "--channel-dir",
        str(tmp_path),
        "--runtime",
        "codex",
        cwd=tmp_path,
        env=env,
    )
    assert live.returncode == 0
    assert not calls.exists()
    assert lock.exists()


def test_run_scheduled_recovers_stale_lock_retries_and_preserves_publish_gate(tmp_path: Path) -> None:
    env, calls, counter = _scheduled_env(tmp_path, _config(max_retries=1))
    env["RUNTIME_FAILS"] = "1"
    lock = tmp_path / ".automation-schedule" / "lock"
    lock.mkdir(parents=True)
    (lock / "pid").write_text("99999999", encoding="utf-8")

    result = _run(
        "run_scheduled.sh",
        "--channel-dir",
        str(tmp_path),
        "--runtime",
        "codex",
        cwd=tmp_path,
        env=env,
    )

    assert result.returncode == 0
    assert counter.read_text(encoding="utf-8") == "2"
    call_text = calls.read_text(encoding="utf-8")
    assert call_text.count("oauth:run yt-oauth --refresh-only") == 1
    assert call_text.count("codex:exec") == 2
    assert call_text.index("oauth:") < call_text.index("codex:exec")
    assert "YouTube への書き込み" in call_text
    assert "sleep:3" in call_text
    assert "notify:" in call_text
    assert not lock.exists()
    log = next((tmp_path / ".automation-schedule" / "logs").iterdir()).read_text(encoding="utf-8")
    assert "stale lock" in log


def test_run_scheduled_stops_before_workflow_when_write_token_refresh_fails(tmp_path: Path) -> None:
    env, calls, counter = _scheduled_env(tmp_path, _config(max_retries=2))
    env["FAKE_OAUTH_RC"] = "1"

    result = _run(
        "run_scheduled.sh",
        "--channel-dir",
        str(tmp_path),
        "--runtime",
        "codex",
        cwd=tmp_path,
        env=env,
    )

    assert result.returncode == 1
    call_lines = calls.read_text(encoding="utf-8").splitlines()
    assert call_lines[0] == "oauth:run yt-oauth --refresh-only"
    assert not any(line.startswith(("codex:", "claude:")) for line in call_lines)
    assert not counter.exists()
    log = next((tmp_path / ".automation-schedule" / "logs").iterdir()).read_text(encoding="utf-8")
    assert "write token" in log
    assert "uv run yt-oauth`" in log


def test_run_scheduled_failure_and_unknown_runtime_have_nonzero_exit(tmp_path: Path) -> None:
    env, calls, counter = _scheduled_env(tmp_path, _config(max_retries=1, notification="none"))
    env["RUNTIME_FAILS"] = "9"
    failed = _run(
        "run_scheduled.sh",
        "--channel-dir",
        str(tmp_path),
        "--runtime",
        "claude",
        cwd=tmp_path,
        env=env,
    )
    assert failed.returncode == 1
    assert counter.read_text(encoding="utf-8") == "2"
    assert calls.read_text(encoding="utf-8").count("claude:-p") == 2

    other = tmp_path / "other"
    other.mkdir()
    env2, _, _ = _scheduled_env(other, _config())
    invalid = _run(
        "run_scheduled.sh",
        "--channel-dir",
        str(other),
        "--runtime",
        "other",
        cwd=other,
        env=env2,
    )
    assert invalid.returncode == 1


def test_schedule_backend_corrupt_replace_disable_and_cli_errors(tmp_path: Path, capsys) -> None:
    backend = _load("schedule_backend.py")
    state_path = tmp_path / "state.json"
    state_path.write_text("[broken", encoding="utf-8")
    assert backend.main(["--state-path", str(state_path), "show"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "error"

    state_path.write_text(
        json.dumps({"backend": "codex-automation", "external_id": "old", "status": "active"}),
        encoding="utf-8",
    )
    replaced = backend.record_state(
        state_path,
        backend="os-fallback",
        external_id="cron",
        replace_backend=True,
    )
    assert replaced["backend"] == "os-fallback"
    assert backend.main(["--state-path", str(state_path), "disable", "--backend", "codex-automation"]) == 1
    assert "not codex-automation" in json.loads(capsys.readouterr().out)["error"]


def _generate_args(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "enable": False,
        "disable": False,
        "timezone": None,
        "run_time": None,
        "cadence": None,
        "target_workflow": None,
        "max_retries": None,
        "retry_delay_seconds": None,
        "notification": None,
        "allow_external_publish": False,
        "dry_run": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_schedule_config_generate_show_dry_run_shape_and_exclusive_flags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    schedule = _load("schedule_config.py")
    workflow_path = tmp_path / "config" / "channel" / "workflow.json"
    workflow_path.parent.mkdir(parents=True)
    workflow_path.write_text('{"workflow":{"manual_baseline_minutes":{"wf-next":90}}}\n', encoding="utf-8")
    monkeypatch.setattr(schedule, "_workflow_path", lambda: workflow_path)

    args = _generate_args(
        enable=True,
        run_time="08:45",
        cadence="mon,fri",
        target_workflow="wf-new --auto",
        max_retries=2,
        retry_delay_seconds=10,
        notification="none",
        dry_run=True,
    )
    before = workflow_path.read_bytes()
    assert schedule.cmd_generate(args) == 0
    assert workflow_path.read_bytes() == before
    captured = capsys.readouterr()
    assert "scheduled_automation" in captured.out
    assert "--dry-run" in captured.err

    args.dry_run = False
    assert schedule.cmd_generate(args) == 0
    payload = json.loads(workflow_path.read_text(encoding="utf-8"))
    assert payload["workflow"]["manual_baseline_minutes"] == {"wf-next": 90}
    assert payload["workflow"]["scheduled_automation"]["cadence"] == ["mon", "fri"]
    assert payload["workflow"]["scheduled_automation"]["allow_external_publish"] is False

    workflow_path.write_text("[]\n", encoding="utf-8")
    with pytest.raises(schedule.ConfigError, match="object"):
        schedule.cmd_generate(_generate_args())
    with pytest.raises(SystemExit) as error:
        schedule.main(["generate", "--enable", "--disable"])
    assert error.value.code == 2


def _scheduler_env(tmp_path: Path, *, fail_crontab: bool = False) -> tuple[dict[str, str], Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv_calls = tmp_path / "uv-calls.txt"
    cron = tmp_path / "cron.txt"
    _write_executable(bin_dir / "uname", "#!/bin/sh\necho Linux\n")
    _write_executable(
        bin_dir / "uv",
        """#!/bin/bash
printf '%s\n' "$*" >> "$UV_CALLS"
if [[ "$1" == "run" && "$2" == "python" && "$3" == "-c" ]]; then
  shift 2
  exec python3 "$@"
elif [[ "$*" == *"schedule_config.py show"* ]]; then
  printf '%s\n' "$SCHEDULE_JSON"
elif [[ "$*" == *" show"* ]]; then
  printf '{"backend":"os-fallback","status":"active"}\n'
fi
exit "${UV_RC:-0}"
""",
    )
    _write_executable(
        bin_dir / "crontab",
        """#!/bin/bash
[[ "${CRONTAB_FAIL:-0}" == 1 ]] && exit 9
if [[ "${1:-}" == "-l" ]]; then
  [[ -f "$CRON_FILE" ]] && cat "$CRON_FILE"
else
  cat > "$CRON_FILE"
fi
""",
    )
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(tmp_path / "home"),
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "UV_CALLS": str(uv_calls),
            "CRON_FILE": str(cron),
            "CRONTAB_FAIL": "1" if fail_crontab else "0",
            "SCHEDULE_JSON": json.dumps(
                {
                    "enabled": True,
                    "run_time": "09:05",
                    "timezone": "Etc/UTC",
                    "cadence": ["mon", "fri"],
                }
            ),
        }
    )
    return env, uv_calls, cron


def test_scheduler_job_cron_install_status_disable_and_failure(tmp_path: Path) -> None:
    env, uv_calls, cron = _scheduler_env(tmp_path)
    install = _run(
        "scheduler_job.sh",
        "install",
        "--backend",
        "os-fallback",
        "--confirm-os-fallback",
        "--runtime",
        "codex",
        cwd=tmp_path,
        env=env,
    )
    assert install.returncode == 0, install.stderr
    cron_line = cron.read_text(encoding="utf-8")
    assert "5 9 * * 1,5" in cron_line, (
        install.stdout,
        install.stderr,
        uv_calls.read_text(encoding="utf-8"),
        cron_line,
    )
    assert "--runtime codex" in cron_line
    assert "record --backend os-fallback" in uv_calls.read_text(encoding="utf-8")

    status = _run(
        "scheduler_job.sh",
        "status",
        "--backend",
        "os-fallback",
        cwd=tmp_path,
        env=env,
    )
    assert status.returncode == 0
    assert "backend identity" in status.stdout
    assert "com.youtube-automation" in status.stdout

    disabled = _run(
        "scheduler_job.sh",
        "disable",
        "--backend",
        "os-fallback",
        cwd=tmp_path,
        env=env,
    )
    assert disabled.returncode == 0
    assert "com.youtube-automation" not in cron.read_text(encoding="utf-8")

    other = tmp_path / "failure"
    other.mkdir()
    fail_env, _, _ = _scheduler_env(other, fail_crontab=True)
    failed = _run(
        "scheduler_job.sh",
        "install",
        "--backend",
        "os-fallback",
        "--confirm-os-fallback",
        cwd=other,
        env=fail_env,
    )
    assert failed.returncode == 9
