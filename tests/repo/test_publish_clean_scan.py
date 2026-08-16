"""``/publish --clean`` の pull-first 安全条件 preflight 契約。"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

import pytest

from tests.helpers.paths import REPO_ROOT
from youtube_automation.core.errors import StateSyncError
from youtube_automation.domains.collections.workflow_state import WorkflowState

SCRIPT = REPO_ROOT / ".claude" / "skills" / "publish" / "references" / "clean-scan.py"
NOW = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("publish_clean_scan", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _state(*, publish_at: object = None) -> WorkflowState:
    return WorkflowState(
        {
            "stage": "live",
            "phase": "complete",
            "upload": {"video_id": "video-123", "publish_at": publish_at},
        }
    )


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"stage": "planning", "phase": "complete", "upload": {"video_id": "v"}}, "stage_not_live"),
        ({"stage": "live", "phase": "publishing", "upload": {"video_id": "v"}}, "phase_not_complete"),
        ({"stage": "live", "phase": "complete", "upload": {"video_id": ""}}, "video_id_missing"),
    ],
)
def test_existing_cleanup_conditions_remain_fail_closed(payload: dict[str, object], reason: str) -> None:
    module = _module()

    decision = module.evaluate(WorkflowState(payload), NOW)

    assert decision.eligible is False
    assert decision.reason == reason


@pytest.mark.parametrize(
    ("publish_at", "eligible", "reason"),
    [
        (None, True, None),
        ("2026-08-16T11:59:59Z", True, None),
        ("2026-08-16T12:00:00+00:00", True, None),
        ("2026-08-16T21:00:01+09:00", False, "publish_at_not_elapsed"),
        ("not-a-time", False, "publish_at_invalid"),
        ("2026-08-16T12:00:00", False, "publish_at_invalid"),
    ],
)
def test_publish_at_is_required_to_have_elapsed_only_when_present(
    publish_at: object,
    eligible: bool,
    reason: str | None,
) -> None:
    module = _module()

    decision = module.evaluate(_state(publish_at=publish_at), NOW)

    assert decision.eligible is eligible
    assert decision.reason == reason


def _git(directory: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=directory,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _write_state(repository: Path, publish_at: str) -> None:
    state_path = repository / "collections" / "live" / "sample" / "workflow-state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "stage": "live",
                "phase": "complete",
                "upload": {"video_id": "video-123", "publish_at": publish_at},
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _repositories(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "--initial-branch=main")
    _git(seed, "config", "user.email", "test@example.com")
    _git(seed, "config", "user.name", "Test User")
    (seed / ".gitignore").write_text("\n", encoding="utf-8")
    _write_state(seed, "2099-01-01T00:00:00Z")
    _git(seed, "add", ".")
    _git(seed, "commit", "-m", "initial")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "main")
    local = tmp_path / "local"
    subprocess.run(
        ["git", "clone", str(remote), str(local)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(local, "config", "user.email", "test@example.com")
    _git(local, "config", "user.name", "Test User")
    return seed, local


def test_scan_reads_remote_state_only_after_successful_pull(tmp_path: Path) -> None:
    module = _module()
    seed, local = _repositories(tmp_path)
    _write_state(seed, "2000-01-01T00:00:00Z")
    _git(seed, "add", "collections")
    _git(seed, "commit", "-m", "published")
    _git(seed, "push")

    report = module.pull_and_scan(local, NOW)

    assert report["eligible"] == [{"collection": "sample", "video_id": "video-123"}]
    assert report["skipped"] == []
    pulled = json.loads((local / "collections/live/sample/workflow-state.json").read_text(encoding="utf-8"))
    assert pulled["upload"]["publish_at"] == "2000-01-01T00:00:00Z"


def test_scan_stops_before_classification_when_pull_fails(tmp_path: Path) -> None:
    module = _module()
    _, local = _repositories(tmp_path)
    _git(local, "remote", "set-url", "origin", str(tmp_path / "missing.git"))

    with pytest.raises(StateSyncError, match="git pull --ff-only"):
        module.pull_and_scan(local, NOW)


def test_cli_reports_pull_failure_and_returns_blocked(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _module()
    _, local = _repositories(tmp_path)
    _git(local, "remote", "set-url", "origin", str(tmp_path / "missing.git"))

    assert module.main(["--channel-dir", str(local)]) == module.EXIT_BLOCKED

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "publish clean blocked" in captured.err
    assert "git pull --ff-only" in captured.err


def test_scan_stops_when_pull_cannot_fast_forward(tmp_path: Path) -> None:
    module = _module()
    seed, local = _repositories(tmp_path)
    _write_state(local, "2050-01-01T00:00:00Z")
    _git(local, "add", "collections")
    _git(local, "commit", "-m", "local")
    _write_state(seed, "2000-01-01T00:00:00Z")
    _git(seed, "add", "collections")
    _git(seed, "commit", "-m", "remote")
    _git(seed, "push")

    with pytest.raises(StateSyncError, match="git pull --ff-only"):
        module.pull_and_scan(local, NOW)


def test_broken_state_is_reported_as_skipped_after_pull(tmp_path: Path) -> None:
    module = _module()
    seed, local = _repositories(tmp_path)
    state_path = seed / "collections/live/sample/workflow-state.json"
    state_path.write_text("{broken\n", encoding="utf-8")
    _git(seed, "add", "collections")
    _git(seed, "commit", "-m", "broken state")
    _git(seed, "push")

    report = module.pull_and_scan(local, NOW)

    assert report["eligible"] == []
    assert report["skipped"] == [{"collection": "sample", "reason": "workflow_state_invalid"}]
