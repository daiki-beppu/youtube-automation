"""Native scheduler backend contract tests (#2369)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_DIR = ROOT / ".claude" / "skills" / "automation-schedule" / "references"


def _load_backend_module():
    path = REFERENCE_DIR / "schedule_backend.py"
    spec = importlib.util.spec_from_file_location("schedule_backend", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


backend = _load_backend_module()


@pytest.mark.parametrize(
    ("product", "dependency_mode", "os_fallback", "expected"),
    [
        ("codex", "cloud", False, "codex-automation"),
        ("codex", "local", False, "codex-automation"),
        ("claude", "cloud", False, "claude-code-cloud"),
        ("claude", "local", False, "claude-cowork-local"),
        ("codex", "local", True, "os-fallback"),
    ],
)
def test_native_backend_selection(product, dependency_mode, os_fallback, expected):
    assert backend.select_backend(product=product, dependency_mode=dependency_mode, os_fallback=os_fallback) == expected


def test_plan_is_dry_run_and_preserves_external_publish_gate(tmp_path, monkeypatch):
    scheduled = SimpleNamespace(
        target_workflow="wf-auto",
        allow_external_publish=False,
        timezone="Asia/Tokyo",
        run_time="09:05",
        cadence=("mon", "wed", "fri"),
        max_retries=2,
        retry_delay_seconds=300,
        prevent_concurrent_runs=True,
        notification="terminal",
    )
    monkeypatch.setattr(
        backend,
        "load_config",
        lambda: SimpleNamespace(workflow=SimpleNamespace(scheduled_automation=scheduled)),
    )
    monkeypatch.setattr(backend, "channel_dir", lambda: tmp_path)

    plan = backend.build_plan(
        product="codex",
        dependency_mode="local",
        overrides={"run_time": "10:15", "cadence": "tue,thu", "max_retries": 4},
    )

    assert plan["dry_run"] is True
    assert plan["backend"] == "codex-automation"
    assert plan["recurrence"] == "RRULE:FREQ=WEEKLY;BYDAY=TU,TH;BYHOUR=10;BYMINUTE=15"
    assert "YouTube への書き込みは実行せず" in plan["prompt"]
    assert plan["cwd"] == str(tmp_path)
    assert plan["max_retries"] == 4
    assert plan["retry_delay_seconds"] == 300
    assert "最大 4 回再試行" in plan["prompt"]
    assert plan["prevent_concurrent_runs"] is True
    assert plan["target_workflow"] == "wf-auto"
    assert plan["prompt"].startswith("/wf-auto")


def test_plan_rejects_removed_automation_run_override(tmp_path, monkeypatch):
    scheduled = SimpleNamespace(
        target_workflow="wf-auto",
        allow_external_publish=False,
        timezone="Asia/Tokyo",
        run_time="09:05",
        cadence=("mon",),
        max_retries=0,
        retry_delay_seconds=300,
        prevent_concurrent_runs=True,
        notification="terminal",
    )
    monkeypatch.setattr(
        backend,
        "load_config",
        lambda: SimpleNamespace(workflow=SimpleNamespace(scheduled_automation=scheduled)),
    )
    monkeypatch.setattr(backend, "channel_dir", lambda: tmp_path)

    with pytest.raises(backend.BackendError, match=r"automation-run.*wf-auto"):
        backend.build_plan(
            product="codex",
            dependency_mode="local",
            overrides={"target_workflow": "automation-run"},
        )


def test_backend_identity_is_idempotent_and_blocks_duplicates(tmp_path):
    state_path = tmp_path / "state.json"
    first = backend.record_state(state_path, backend="codex-automation", external_id="task-1")
    updated = backend.record_state(state_path, backend="codex-automation", external_id="task-1")
    assert first["backend"] == updated["backend"] == "codex-automation"
    assert json.loads(state_path.read_text(encoding="utf-8"))["external_id"] == "task-1"

    with pytest.raises(backend.BackendError, match="disable it before"):
        backend.ensure_backend_available(state_path, backend="os-fallback")
    with pytest.raises(backend.BackendError, match="disable it before"):
        backend.record_state(state_path, backend="claude-code-cloud", external_id="job-2")


def test_disable_must_target_recorded_backend(tmp_path):
    state_path = tmp_path / "state.json"
    backend.record_state(state_path, backend="claude-cowork-local", external_id="local-1")
    with pytest.raises(backend.BackendError, match="not os-fallback"):
        backend.disable_state(state_path, backend="os-fallback")
    state = backend.disable_state(state_path, backend="claude-cowork-local")
    assert state["status"] == "disabled"


def test_os_scheduler_install_refuses_implicit_fallback():
    script = REFERENCE_DIR / "scheduler_job.sh"
    result = subprocess.run(
        ["bash", str(script), "install", "--backend", "os-fallback", "--runtime", "codex"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "--confirm-os-fallback" in result.stderr


def test_skill_covers_native_status_disable_and_local_dependency_gate():
    skill = (REFERENCE_DIR.parent / "SKILL.md").read_text(encoding="utf-8")
    for backend_name in backend.BACKENDS:
        assert backend_name in skill
    for command in ("setup / update", "status", "disable"):
        assert command in skill
    for local_dependency in ("Chrome", "Suno Helper", "ffmpeg", "OAuth"):
        assert local_dependency in skill
    assert "/loop" in skill and "最長 3 日" in skill
    assert "--confirm-os-fallback" in skill


def test_runtime_detection_never_promotes_os_scheduler_to_required_native_backend():
    script = (REFERENCE_DIR / "detect_runtime.sh").read_text(encoding="utf-8")
    assert "product-codex" in script
    assert "product-claude" in script
    assert "report warn os-fallback" in script
    assert "report fail scheduler" not in script
