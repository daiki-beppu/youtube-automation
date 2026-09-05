from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from tests.helpers.paths import REPO_ROOT

PROVIDER_PATH = REPO_ROOT / "evals" / "providers" / "claude_code_provider.py"
ASSERTIONS_PATH = REPO_ROOT / "evals" / "assertions" / "wf_status_read_only.py"


def _load_provider():
    spec = importlib.util.spec_from_file_location("claude_code_provider", PROVIDER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"provider を load できません: {PROVIDER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_assertions():
    spec = importlib.util.spec_from_file_location("wf_status_read_only", ASSERTIONS_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"assertion を load できません: {ASSERTIONS_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_command_exposes_only_read_tools_and_exact_dry_run_cli() -> None:
    provider = _load_provider()

    command = provider._build_command("進捗を読むだけで確認して", max_turns=8)

    assert command[:3] == ["claude", "-p", "--output-format"]
    assert command[3] == "json"
    assert command[command.index("--permission-mode") + 1] == "dontAsk"
    assert command[command.index("--setting-sources") + 1] == "project"
    assert command[command.index("--tools") + 1] == "Read,Glob,Grep,Bash"
    allowed_index = command.index("--allowed-tools")
    allowed = command[allowed_index + 1 : allowed_index + 5]
    assert allowed == [
        "Read",
        "Glob",
        "Grep",
        'Bash(uv run yt-raw-master-check collections/planning/v2-prepared; echo "EXIT=$?")',
    ]
    assert all("--apply" not in argument for argument in command)
    assert all("*" not in argument for argument in allowed)
    assert "--strict-mcp-config" in command
    assert "--no-session-persistence" in command


def test_parse_result_preserves_response_and_denied_tool_attempts() -> None:
    provider = _load_provider()
    claude_result = json.dumps(
        {
            "result": "進捗は2件です",
            "permission_denials": [
                {
                    "tool_name": "Bash",
                    "tool_use_id": "tool-1",
                    "tool_input": {"command": "uv run yt-wf-next"},
                }
            ],
        }
    )

    output = json.loads(
        provider._build_output(
            claude_result,
            changed_state_files=["collections/planning/v2-prepared/workflow-state.json"],
            changed_fixture_files=["unexpected.txt"],
        )
    )

    assert output["response"] == "進捗は2件です"
    assert output["tool_calls"] == [
        {
            "name": "Bash",
            "input": {"command": "uv run yt-wf-next"},
            "denied": True,
        }
    ]
    assert output["workflow_state_unchanged"] is False
    assert output["fixture_unchanged"] is False


def test_restore_fixture_recovers_modified_deleted_and_created_files(tmp_path: Path) -> None:
    provider = _load_provider()
    state_path = tmp_path / "collections" / "planning" / "sample" / "workflow-state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text('{"phase":"prepared"}\n', encoding="utf-8")
    config_path = tmp_path / "config.json"
    config_path.write_text("{}\n", encoding="utf-8")
    snapshot = provider._snapshot_fixture(tmp_path)

    state_path.write_text('{"phase":"mastered"}\n', encoding="utf-8")
    config_path.unlink()
    created_path = tmp_path / "created.txt"
    created_path.write_text("unexpected\n", encoding="utf-8")
    created_directory = tmp_path / "created-empty-dir"
    created_directory.mkdir()

    changed = provider._changed_files(tmp_path, snapshot)
    provider._restore_fixture(tmp_path, snapshot)

    assert changed == [
        "collections/planning/sample/workflow-state.json",
        "config.json",
        "created-empty-dir",
        "created.txt",
    ]
    assert state_path.read_text(encoding="utf-8") == '{"phase":"prepared"}\n'
    assert config_path.read_text(encoding="utf-8") == "{}\n"
    assert not created_path.exists()
    assert not created_directory.exists()


def test_build_output_rejects_invalid_claude_json() -> None:
    provider = _load_provider()

    with pytest.raises(ValueError, match="Claude Code JSON"):
        provider._build_output("not-json", changed_state_files=[], changed_fixture_files=[])


def test_violation_fixture_fails_tool_state_and_fixture_assertions() -> None:
    assertions = _load_assertions()
    outputs = json.loads((PROVIDER_PATH.parents[1] / "fixtures" / "wf-status-violation.json").read_text())
    output = outputs[0]

    assert assertions.collections_reported(output, {})["pass"] is False
    assert assertions.no_execution_tool_attempts(output, {})["pass"] is False
    assert assertions.workflow_state_immutable(output, {})["pass"] is False
    assert assertions.fixture_clean(output, {})["pass"] is False


@pytest.mark.parametrize(
    ("response", "passed"),
    [
        ("", False),
        ("こんにちは", False),
        ("v1-legacy | Legacy Rain Study", False),
        ("v2-prepared | Quiet Night Focus", False),
        ("v1-legacy | Quiet Night Focus\nv2-prepared | Legacy Rain Study", False),
        ("v1-legacy-other | Legacy Rain Study\nv2-prepared | Quiet Night Focus", False),
        ("v1-legacy | Legacy Rain Study\nv2-prepared | Quiet Night Focus", True),
        ("- **v2-prepared**: Quiet Night Focus\n- **v1-legacy**: Legacy Rain Study", True),
        ("Unknown command: /wf-status\nv1-legacy | Legacy Rain Study\nv2-prepared | Quiet Night Focus", False),
    ],
)
def test_collection_results_require_both_fixture_id_name_pairs(response: str, passed: bool) -> None:
    assertions = _load_assertions()
    output = json.dumps({"response": response})

    assert assertions.collections_reported(output, {})["pass"] is passed
