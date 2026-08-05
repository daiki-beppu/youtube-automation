"""Contracts for the bounded codex image batch launcher (#2028)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.paths import REPO_ROOT
from youtube_automation.core.errors import ConfigError
from youtube_automation.infrastructure.media.image_provider.config import parse_image_generation_config

ROOT = REPO_ROOT
BATCH = ROOT / ".claude/skills/thumbnail/references/codex-image-batch.sh"


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _mock_tools(tmp_path: Path) -> tuple[Path, Path, Path]:
    tools = tmp_path / "bin"
    tools.mkdir()
    codex_log = tmp_path / "codex.log"
    _write_executable(
        tools / "codex",
        """#!/usr/bin/env python3
import json, os, pathlib, re, sys
args = sys.argv[1:]
if args == ["--version"]:
    print("codex-cli 1.2.3")
elif args[:2] == ["login", "status"]:
    print("Logged in using ChatGPT")
elif args and args[0] == "exec":
    with pathlib.Path(os.environ["MOCK_CODEX_LOG"]).open("a") as handle:
        handle.write(("preflight" if args[-1] == "Reply with exactly codex-model-compat-ok." else "generation") + "\\n")
    if args[-1] != "Reply with exactly codex-model-compat-ok.":
        match = re.search(r"copy the produced PNG to (.+?)\\. Then reply", args[-1])
        if not match:
            raise SystemExit(8)
        output = pathlib.Path(match.group(1))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"\\x89PNG\\r\\n\\x1a\\n")
        print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": str(output)}}))
else:
    raise SystemExit(9)
""",
    )
    state = tmp_path / "runner-state.json"
    _write_executable(
        tools / "runner",
        """#!/usr/bin/env python3
import fcntl, json, os, pathlib, sys, time
args = sys.argv[1:]
if args and args[0] == "--require-reference":
    args = args[1:]
prompt, output = args[:2]
state_path = pathlib.Path(os.environ["MOCK_RUNNER_STATE"])
lock_path = state_path.with_suffix(".lock")
lock_path.touch()
def update(delta):
    with lock_path.open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = json.loads(state_path.read_text()) if state_path.exists() else {"active": 0, "max": 0, "calls": []}
        state["active"] += delta
        state["max"] = max(state["max"], state["active"])
        if delta > 0:
            state["calls"].append(prompt)
        state_path.write_text(json.dumps(state))
        fcntl.flock(lock, fcntl.LOCK_UN)
update(1)
try:
    time.sleep(0.12)
    if prompt.startswith("FAIL"):
        raise SystemExit(7)
    path = pathlib.Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\\x89PNG\\r\\n\\x1a\\n")
finally:
    update(-1)
""",
    )
    return tools, codex_log, state


def _manifest(tmp_path: Path, prompts: list[str]) -> Path:
    jobs = [
        {
            "id": f"job-{index}",
            "prompt": prompt,
            "output": str(tmp_path / "output" / f"{index}.png"),
        }
        for index, prompt in enumerate(prompts, start=1)
    ]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(jobs), encoding="utf-8")
    return path


def _run_batch(
    tmp_path: Path,
    manifest: Path,
    *,
    max_parallel: int | None = None,
    channel_dir: Path | None = None,
    project_environment: Path | None = None,
    runner_override: bool = True,
    cwd: Path = ROOT,
    channel_slug: str | None = None,
) -> subprocess.CompletedProcess[str]:
    tools, codex_log, state = _mock_tools(tmp_path)
    batch = BATCH
    if runner_override:
        launcher = tmp_path / "launcher"
        launcher.mkdir()
        batch = launcher / BATCH.name
        shutil.copy2(BATCH, batch)
        shutil.copy2(tools / "runner", launcher / "codex-image.sh")
    command = ["bash", str(batch), "--manifest", str(manifest)]
    if max_parallel is not None:
        command.extend(["--max-parallel", str(max_parallel)])
    env = {
        **os.environ,
        "PATH": f"{tools}:{os.environ['PATH']}",
        "MOCK_CODEX_LOG": str(codex_log),
        "MOCK_RUNNER_STATE": str(state),
        "UV_PROJECT": str(ROOT),
    }
    env.pop("CHANNEL", None)
    env.pop("CHANNEL_DIR", None)
    if channel_dir is not None:
        env["CHANNEL_DIR"] = str(channel_dir)
    if channel_slug is not None:
        env["CHANNEL"] = channel_slug
    if project_environment is not None:
        env["UV_PROJECT_ENVIRONMENT"] = str(project_environment)
    return subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, check=False)


def _workspace_channel(workspace: Path, slug: str) -> Path:
    channel = workspace / "channels" / slug
    (channel / "config" / "channel").mkdir(parents=True)
    skills = channel / "config" / "skills"
    skills.mkdir()
    (skills / "thumbnail.yaml").write_text(
        "image_generation:\n  provider: codex\n  codex:\n    max_parallel: 1\n",
        encoding="utf-8",
    )
    return channel


def test_codex_config_defaults_overrides_and_rejects_invalid_parallelism() -> None:
    default = parse_image_generation_config({"image_generation": {"provider": "codex"}})
    overridden = parse_image_generation_config(
        {"image_generation": {"provider": "codex", "codex": {"max_parallel": 4}}}
    )

    assert default.codex is not None and default.codex.max_parallel == 2
    assert overridden.codex is not None and overridden.codex.max_parallel == 4
    with pytest.raises(ConfigError, match="max_parallel"):
        parse_image_generation_config({"image_generation": {"provider": "codex", "codex": {"max_parallel": 0}}})


def test_batch_uses_config_limit_and_cli_override_and_runs_one_preflight(tmp_path: Path) -> None:
    channel = tmp_path / "channel"
    config = channel / "config/skills"
    config.mkdir(parents=True)
    (config / "thumbnail.yaml").write_text(
        "image_generation:\n  provider: codex\n  codex:\n    max_parallel: 1\n",
        encoding="utf-8",
    )
    manifest = _manifest(tmp_path, ["one", "two", "three"])

    first = _run_batch(tmp_path, manifest, channel_dir=channel)

    assert first.returncode == 0, first.stderr
    state = json.loads((tmp_path / "runner-state.json").read_text())
    assert state["max"] == 1
    assert (tmp_path / "codex.log").read_text().splitlines() == ["preflight"]

    second_root = tmp_path / "override"
    second_root.mkdir()
    manifest = _manifest(second_root, ["one", "two", "three"])
    second = _run_batch(second_root, manifest, max_parallel=2, channel_dir=channel)

    assert second.returncode == 0, second.stderr
    state = json.loads((second_root / "runner-state.json").read_text())
    assert state["max"] == 2


@pytest.mark.parametrize("partial", [False, True], ids=["fresh", "partial"])
def test_batch_syncs_worktree_local_environment_before_config_import(tmp_path: Path, partial: bool) -> None:
    """fresh / partial .venv は共有せず、通常の uv run で同期してから config を読む。"""
    project_environment = tmp_path / ".venv"
    channel = tmp_path / "channel"
    config = channel / "config/skills"
    config.mkdir(parents=True)
    (config / "thumbnail.yaml").write_text(
        "image_generation:\n  provider: codex\n  codex:\n    max_parallel: 1\n",
        encoding="utf-8",
    )
    if partial:
        subprocess.run(["uv", "venv", str(project_environment)], cwd=ROOT, check=True, capture_output=True)
    manifest = _manifest(tmp_path, ["one", "two"])

    result = _run_batch(
        tmp_path,
        manifest,
        max_parallel=None,
        channel_dir=channel,
        project_environment=project_environment,
    )

    assert result.returncode == 0, result.stderr
    assert project_environment.is_dir()
    assert not project_environment.is_symlink()
    imported = subprocess.run(
        [str(project_environment / "bin/python"), "-c", "import yaml, youtube_automation"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert imported.returncode == 0, imported.stderr


def test_batch_reports_config_failure_after_environment_is_ready(tmp_path: Path) -> None:
    channel = tmp_path / "channel"
    config = channel / "config/skills"
    config.mkdir(parents=True)
    (config / "thumbnail.yaml").write_text(
        "image_generation:\n  provider: gemini\n",
        encoding="utf-8",
    )
    manifest = _manifest(tmp_path, ["one", "two"])

    result = _run_batch(tmp_path, manifest, channel_dir=channel)

    assert result.returncode != 0
    assert "project 環境は準備済み" in result.stderr
    assert "max_parallel" in result.stderr
    assert not (tmp_path / "codex.log").exists()


@pytest.mark.parametrize(
    ("channel_slug", "diagnostic"),
    [
        (None, "workspace ルートでは --channel <slug> または CHANNEL=<slug> を指定してください"),
        ("missing", "CHANNEL='missing' に対応するチャンネルが見つかりません"),
    ],
)
def test_batch_rejects_missing_or_wrong_workspace_channel_before_jobs(
    tmp_path: Path,
    channel_slug: str | None,
    diagnostic: str,
) -> None:
    workspace = tmp_path / "workspace"
    _workspace_channel(workspace, "alpha")
    manifest = _manifest(tmp_path, ["one", "two"])

    result = _run_batch(tmp_path, manifest, cwd=workspace, channel_slug=channel_slug)

    assert result.returncode != 0
    assert diagnostic in result.stderr
    assert "候補: alpha" in result.stderr
    assert not (tmp_path / "codex.log").exists()
    assert not (tmp_path / "runner-state.json").exists()


def test_batch_resolves_channel_slug_from_workspace_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _workspace_channel(workspace, "alpha")
    manifest = _manifest(tmp_path, ["one", "two"])

    result = _run_batch(tmp_path, manifest, cwd=workspace, channel_slug="alpha")

    assert result.returncode == 0, result.stderr
    state = json.loads((tmp_path / "runner-state.json").read_text())
    assert sorted(state["calls"]) == ["one", "two"]


def test_batch_finishes_remaining_jobs_and_reports_failures(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, ["one", "FAIL two", "three"])

    result = _run_batch(tmp_path, manifest, max_parallel=2)

    assert result.returncode != 0
    assert "job-2" in result.stderr and "FAIL two" in result.stderr
    assert (tmp_path / "output/1.png").exists()
    assert not (tmp_path / "output/2.png").exists()
    assert (tmp_path / "output/3.png").exists()
    state = json.loads((tmp_path / "runner-state.json").read_text())
    assert sorted(state["calls"]) == ["FAIL two", "one", "three"]


def test_batch_reports_multiline_failure_prompt_without_corrupting_entries(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, ["one", "FAIL first\nsecond"])

    result = _run_batch(tmp_path, manifest, max_parallel=2)

    assert result.returncode != 0
    assert 'id="job-2" prompt="FAIL first\\nsecond" (exit=7)' in result.stderr
    assert result.stderr.count("  - id=") == 1


def test_default_single_image_runner_skips_child_preflight_via_batch_shim(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, ["one", "two"])
    channel = _workspace_channel(tmp_path / "workspace", "alpha")

    result = _run_batch(tmp_path, manifest, max_parallel=2, runner_override=False, channel_dir=channel)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "codex.log").read_text().splitlines() == [
        "preflight",
        "generation",
        "generation",
    ]
    assert (tmp_path / "output/1.png").exists()
    assert (tmp_path / "output/2.png").exists()


def test_batch_rejects_duplicate_outputs_before_preflight(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, ["one", "two"])
    jobs = json.loads(manifest.read_text())
    jobs[1]["output"] = jobs[0]["output"]
    manifest.write_text(json.dumps(jobs))

    result = _run_batch(tmp_path, manifest, max_parallel=2)

    assert result.returncode != 0
    assert "output" in result.stderr and "unique" in result.stderr
    assert not (tmp_path / "codex.log").exists()


def test_batch_rejects_outputs_that_alias_through_a_symlink(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, ["one", "two"])
    real_output = tmp_path / "real-output"
    real_output.mkdir()
    alias = tmp_path / "alias-output"
    alias.symlink_to(real_output, target_is_directory=True)
    jobs = json.loads(manifest.read_text())
    jobs[0]["output"] = str(real_output / "same.png")
    jobs[1]["output"] = str(alias / "same.png")
    manifest.write_text(json.dumps(jobs))

    result = _run_batch(tmp_path, manifest, max_parallel=2)

    assert result.returncode != 0
    assert "canonical output paths must be unique" in result.stderr
    assert not (tmp_path / "codex.log").exists()


def test_skill_documents_batch_usage_and_fair_use_limit() -> None:
    skill = (ROOT / ".claude/skills/thumbnail/SKILL.md").read_text()
    for phrase in (
        "codex-image-batch.sh",
        "image_generation.codex.max_parallel",
        "大量生成には使わない",
        "default `2` を維持",
        "失敗時は `1` に下げる",
        "`3` 以上はユーザーが今回の実行について明示した場合だけ",
    ):
        assert phrase in skill


def test_skill_uses_per_run_manifest_with_caller_owned_cleanup() -> None:
    """#2948: 並列 collection は固定 manifest を共有せず、自身の一時ファイルだけを消す。"""
    skill = (ROOT / ".claude/skills/thumbnail/SKILL.md").read_text()
    batch_contract = skill.split("2 件以上の候補を同時生成する場合", maxsplit=1)[1].split("同時起動数は", maxsplit=1)[0]

    assert "/tmp/codex-thumbnail-jobs.json" not in batch_contract
    assert 'manifest=$(mktemp "${TMPDIR:-/tmp}/codex-thumbnail-jobs.XXXXXX")' in batch_contract
    assert "trap 'rm -f \"$manifest\"' EXIT" in batch_contract
    assert '--manifest "$manifest"' in batch_contract
    assert 'rm -f "${TMPDIR:-/tmp}/codex-thumbnail-jobs.' not in batch_contract
