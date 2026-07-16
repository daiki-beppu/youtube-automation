"""Terraform の validation と state transition を実 plan で検証する。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.streaming._helpers import _STREAMING_DIR


@pytest.fixture(scope="module")
def terraform_dir() -> Path:
    assert shutil.which("terraform") is not None, "Terraform is required for streaming runtime contract tests"
    result = subprocess.run(
        ["terraform", "init", "-backend=false", "-input=false", "-no-color"],
        cwd=_STREAMING_DIR,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "TF_IN_AUTOMATION": "1"},
    )
    assert result.returncode == 0, result.stderr
    return _STREAMING_DIR


def _terraform_test(terraform_dir: Path, test_file: str) -> list[dict[str, object]]:
    result = subprocess.run(
        ["terraform", "test", "-json", "-verbose", f"-filter={test_file}"],
        cwd=terraform_dir,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "TF_IN_AUTOMATION": "1"},
    )
    events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    if result.returncode != 0:
        messages = [str(event.get("@message", "")) for event in events[-20:]]
        pytest.fail("terraform test failed:\n" + "\n".join(messages) + "\n" + result.stderr)
    return events


def _actions_by_run(events: list[dict[str, object]]) -> dict[str, dict[str, list[str]]]:
    actions: dict[str, dict[str, list[str]]] = {}
    for event in events:
        if event.get("type") != "test_plan":
            continue
        run_name = str(event["@testrun"])
        test_plan = event["test_plan"]
        assert isinstance(test_plan, dict)
        resource_changes = test_plan["resource_changes"]
        assert isinstance(resource_changes, list)
        actions[run_name] = {
            str(change["address"]): list(change["change"]["actions"])
            for change in resource_changes
            if change["address"] in {"vultr_instance.this", "null_resource.deploy"}
        }
    return actions


def test_plan_actions_preserve_or_replace_the_intended_resources(terraform_dir: Path) -> None:
    events = _terraform_test(terraform_dir, "tests/state_transitions.tftest.hcl")
    actions = _actions_by_run(events)

    assert actions["plan_cloud_init_change"] == {
        "null_resource.deploy": ["no-op"],
        "vultr_instance.this": ["no-op"],
    }
    assert actions["plan_host_key_change"] == {
        "null_resource.deploy": ["delete", "create"],
        "vultr_instance.this": ["delete", "create"],
    }
    assert actions["plan_install_root_change"] == {
        "null_resource.deploy": ["delete", "create"],
        "vultr_instance.this": ["no-op"],
    }


def test_install_root_validation_executes_all_acceptance_and_rejection_cases(terraform_dir: Path) -> None:
    events = _terraform_test(terraform_dir, "tests/install_root_validation.tftest.hcl")
    summary = next(event["test_summary"] for event in events if event.get("type") == "test_summary")

    assert summary == {"status": "pass", "passed": 8, "failed": 0, "errored": 0, "skipped": 0}
