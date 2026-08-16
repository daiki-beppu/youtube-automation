"""Native scheduler backend contract tests (#2369)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from types import SimpleNamespace

import pytest

from tests.helpers.paths import REPO_ROOT

ROOT = REPO_ROOT
REFERENCE_DIR = ROOT / ".claude" / "skills" / "wf-new" / "references"


def _load_backend_module():
    path = REFERENCE_DIR / "schedule_backend.py"
    spec = importlib.util.spec_from_file_location("schedule_backend", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


backend = _load_backend_module()


@pytest.mark.parametrize(
    ("overlays_enabled", "expected"),
    [
        (
            True,
            {
                "planning": "cloud",
                "prompt": "cloud",
                "suno": "local",
                "media": "local",
                "publish": "local",
            },
        ),
        (
            False,
            {
                "planning": "cloud",
                "prompt": "cloud",
                "suno": "local",
                "media": "cloud",
                "publish": "cloud",
            },
        ),
    ],
)
def test_capability_boundary_matches_heavy_and_light_channel_regimes(overlays_enabled, expected):
    assert {
        stage: backend.classify_dependency_mode(stage=stage, overlays_enabled=overlays_enabled)[0]
        for stage in backend.EXECUTION_STAGES
    } == expected


def test_capability_boundary_rejects_unknown_stage():
    with pytest.raises(backend.BackendError, match="unsupported execution stage"):
        backend.classify_dependency_mode(stage="oauth", overlays_enabled=False)


def test_skill_self_describes_capability_boundary_without_removed_dependency_list():
    skill = (ROOT / ".claude" / "skills" / "wf-new" / "SKILL.md").read_text(encoding="utf-8")
    schedule = (REFERENCE_DIR / "schedule.md").read_text(encoding="utf-8")
    contract = skill + schedule

    assert "人間のブラウザ工程（Suno UI）" in contract
    assert "overlays.enabled: true" in contract
    assert "企画・プロンプト" in contract
    assert "軽量レジーム" in contract
    assert "ローカルファイル、OAuth、Chrome、Suno Helper、ffmpeg、ローカル media" not in contract


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
        target_workflow="wf-new --auto",
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
        lambda: SimpleNamespace(
            workflow=SimpleNamespace(scheduled_automation=scheduled),
            youtube=SimpleNamespace(overlays=SimpleNamespace(enabled=False)),
        ),
    )
    monkeypatch.setattr(backend, "channel_dir", lambda: tmp_path)

    plan = backend.build_plan(
        product="codex",
        stage="suno",
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
    assert plan["target_workflow"] == "wf-new --auto"
    assert plan["prompt"].index("uv run yt-oauth --refresh-only") < plan["prompt"].index("/wf-new --auto")
    assert "YouTube Data API を呼び出さない" in plan["prompt"]
    assert "uv run yt-oauth`" in plan["prompt"]
    assert "/automation-schedule" not in plan["prompt"]
    assert "/wf-auto" not in plan["prompt"]
    assert plan["dependency_mode"] == "local"
    assert "local dependencies require desktop local project" in plan["management"]


def test_cloud_plan_does_not_require_local_write_token_maintenance(tmp_path, monkeypatch):
    scheduled = SimpleNamespace(
        target_workflow="wf-new --auto",
        allow_external_publish=False,
        timezone="Asia/Tokyo",
        run_time="09:05",
        cadence=("mon",),
        max_retries=0,
        retry_delay_seconds=300,
        prevent_concurrent_runs=True,
        notification="none",
    )
    monkeypatch.setattr(
        backend,
        "load_config",
        lambda: SimpleNamespace(
            workflow=SimpleNamespace(scheduled_automation=scheduled),
            youtube=SimpleNamespace(overlays=SimpleNamespace(enabled=False)),
        ),
    )
    monkeypatch.setattr(backend, "channel_dir", lambda: tmp_path)

    plan = backend.build_plan(product="claude", stage="planning")

    assert plan["prompt"].startswith("/wf-new --auto")
    assert "yt-oauth" not in plan["prompt"]


def test_plan_derives_dependency_mode_from_stage_and_overlay_regime(tmp_path, monkeypatch):
    scheduled = SimpleNamespace(
        target_workflow="wf-new --auto",
        allow_external_publish=False,
        timezone="Asia/Tokyo",
        run_time="09:05",
        cadence=("mon",),
        max_retries=0,
        retry_delay_seconds=300,
        prevent_concurrent_runs=True,
        notification="none",
    )
    monkeypatch.setattr(
        backend,
        "load_config",
        lambda: SimpleNamespace(
            workflow=SimpleNamespace(scheduled_automation=scheduled),
            youtube=SimpleNamespace(overlays=SimpleNamespace(enabled=True)),
        ),
    )
    monkeypatch.setattr(backend, "channel_dir", lambda: tmp_path)

    plan = backend.build_plan(product="claude", stage="media")

    assert plan["dependency_mode"] == "local"
    assert plan["execution_stage"] == "media"
    assert plan["boundary_reason"] == "heavy_overlay_temporary_exception"
    assert plan["backend"] == "claude-cowork-local"


@pytest.mark.parametrize("removed_target", ["automation-run", "wf-auto"])
def test_plan_rejects_removed_target_override(tmp_path, monkeypatch, removed_target):
    scheduled = SimpleNamespace(
        target_workflow="wf-new --auto",
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
        lambda: SimpleNamespace(
            workflow=SimpleNamespace(scheduled_automation=scheduled),
            youtube=SimpleNamespace(overlays=SimpleNamespace(enabled=False)),
        ),
    )
    monkeypatch.setattr(backend, "channel_dir", lambda: tmp_path)

    with pytest.raises(backend.BackendError, match=rf"{removed_target}.*wf-new --auto"):
        backend.build_plan(
            product="codex",
            stage="planning",
            overrides={"target_workflow": removed_target},
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


def test_scheduler_entrypoint_reports_status_and_disables_recorded_backend(tmp_path, capsys):
    state_path = tmp_path / "state.json"
    common = ["--channel-dir", str(tmp_path), "--state-path", str(state_path)]

    assert backend.main([*common, "show"]) == 0
    assert json.loads(capsys.readouterr().out) == {"status": "unconfigured"}

    backend.record_state(state_path, backend="codex-automation", external_id="task-1")
    assert backend.main([*common, "disable", "--backend", "codex-automation"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["backend"] == "codex-automation"
    assert output["external_id"] == "task-1"
    assert output["status"] == "disabled"
    assert backend.read_state(state_path)["status"] == "disabled"


def test_runtime_detection_never_promotes_os_scheduler_to_required_native_backend():
    script = (REFERENCE_DIR / "detect_runtime.sh").read_text(encoding="utf-8")
    assert "product-codex" in script
    assert "product-claude" in script
    assert "report warn os-fallback" in script
    assert "report fail scheduler" not in script
