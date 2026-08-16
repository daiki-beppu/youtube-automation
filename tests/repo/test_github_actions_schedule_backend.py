"""Executable GitHub Actions schedule backend contracts (#4055)."""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest
import yaml

from tests.helpers.paths import REPO_ROOT

_REFERENCE = REPO_ROOT / ".claude/skills/wf-new/references/github_actions_schedule.py"
_TEMPLATE = REPO_ROOT / "src/youtube_automation/infrastructure/resources/channel/youtube-automation.yml"
_WORKFLOW = Path(".github/workflows/youtube-automation.yml")


def _load_module():
    spec = importlib.util.spec_from_file_location("github_actions_schedule", _REFERENCE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _channel(tmp_path: Path) -> Path:
    target = tmp_path / _WORKFLOW
    target.parent.mkdir(parents=True)
    shutil.copyfile(_TEMPLATE, target)
    return tmp_path


def test_configure_status_disable_preserves_workflow_outside_owned_block(tmp_path: Path) -> None:
    backend = _load_module()
    channel = _channel(tmp_path)
    target = channel / _WORKFLOW
    original = target.read_text(encoding="utf-8")
    prefix, remainder = original.split(backend.SCHEDULE_BEGIN, maxsplit=1)
    _, suffix = remainder.split(backend.SCHEDULE_END, maxsplit=1)

    configured = backend.configure_schedule(channel, cron="5 0 * * 1,3,5")
    configured_text = target.read_text(encoding="utf-8")

    assert configured == {
        "backend": "github-actions",
        "status": "active",
        "cron": "5 0 * * 1,3,5",
        "workflow": str(_WORKFLOW),
    }
    assert configured_text.startswith(prefix + backend.SCHEDULE_BEGIN)
    assert configured_text.endswith(backend.SCHEDULE_END + suffix)
    document = yaml.load(configured_text, Loader=yaml.BaseLoader)
    assert document["on"]["schedule"] == [{"cron": "5 0 * * 1,3,5"}]
    assert backend.schedule_status(channel) == configured

    disabled = backend.disable_schedule(channel)

    assert disabled == {
        "backend": "github-actions",
        "status": "disabled",
        "workflow": str(_WORKFLOW),
    }
    assert backend.schedule_status(channel) == disabled
    assert target.read_text(encoding="utf-8").startswith(prefix + backend.SCHEDULE_BEGIN)
    assert target.read_text(encoding="utf-8").endswith(backend.SCHEDULE_END + suffix)


def test_configure_is_idempotent_and_replaces_only_owned_cron(tmp_path: Path) -> None:
    backend = _load_module()
    channel = _channel(tmp_path)

    backend.configure_schedule(channel, cron="0 0 * * *")
    first = (channel / _WORKFLOW).read_bytes()
    backend.configure_schedule(channel, cron="0 0 * * *")

    assert (channel / _WORKFLOW).read_bytes() == first


@pytest.mark.parametrize("cron", ["", "0 0 * *", "@daily", "60 0 * * *", "0 24 * * *", "0 0 * * MON"])
def test_configure_rejects_invalid_cron_without_changing_workflow(tmp_path: Path, cron: str) -> None:
    backend = _load_module()
    channel = _channel(tmp_path)
    target = channel / _WORKFLOW
    original = target.read_bytes()

    with pytest.raises(backend.ScheduleWorkflowError):
        backend.configure_schedule(channel, cron=cron)

    assert target.read_bytes() == original


def test_configure_rejects_missing_markers_and_symlink_without_writing(tmp_path: Path) -> None:
    backend = _load_module()
    channel = _channel(tmp_path)
    target = channel / _WORKFLOW
    target.write_text("name: unmanaged\n", encoding="utf-8")
    original = target.read_bytes()

    with pytest.raises(backend.ScheduleWorkflowError, match="management markers"):
        backend.configure_schedule(channel, cron="0 0 * * *")
    assert target.read_bytes() == original

    target.unlink()
    outside = tmp_path / "outside.yml"
    outside.write_text("outside\n", encoding="utf-8")
    target.symlink_to(outside)
    with pytest.raises(backend.ScheduleWorkflowError, match="symlink"):
        backend.configure_schedule(channel, cron="0 0 * * *")
    assert outside.read_text(encoding="utf-8") == "outside\n"


def test_cli_status_configure_disable_returns_json_without_external_calls(tmp_path: Path, capsys) -> None:
    backend = _load_module()
    channel = _channel(tmp_path)

    assert backend.main(["--channel-dir", str(channel), "status"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "disabled"
    assert backend.main(["--channel-dir", str(channel), "configure", "--cron", "15 3 * * 2"]) == 0
    assert json.loads(capsys.readouterr().out)["cron"] == "15 3 * * 2"
    assert backend.main(["--channel-dir", str(channel), "disable"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "disabled"
