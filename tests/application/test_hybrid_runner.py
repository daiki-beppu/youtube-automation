from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.helpers.paths import REPO_ROOT
from youtube_automation.application.hybrid_runner import SandwichRequest, run_sandwich
from youtube_automation.application.media_handoff import HandoffSource, pull_handoff, push_handoff
from youtube_automation.core.errors import StateSyncError
from youtube_automation.domains.media_handoff_manifest import HandoffIdentity
from youtube_automation.infrastructure.media_store.local import LocalMediaStore


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, text=True)


def _repositories(tmp_path: Path, manifest_key: str, root_sha256: str) -> tuple[Path, Path, Path]:
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    worker = tmp_path / "worker"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(tmp_path, "init", "-b", "main", str(seed))
    _git(seed, "config", "user.name", "Test")
    _git(seed, "config", "user.email", "test@example.com")
    collection = seed / "collections" / "planning" / "demo"
    collection.mkdir(parents=True)
    (seed / ".gitignore").write_text("media/\noutputs/\n", encoding="utf-8")
    (collection / "workflow-state.json").write_text(
        json.dumps(
            {
                "phase": "cloud_owned",
                "planning": {"music": {"engine": "suno"}},
                "assets": {"music_downloaded": True},
                "handoff": {
                    "point": "suno_download",
                    "owner": "cloud",
                    "manifest_key": manifest_key,
                    "root_sha256": root_sha256,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _git(seed, "add", ".")
    _git(seed, "commit", "-m", "initial")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "main")
    subprocess.run(["git", "clone", "--branch", "main", str(remote), str(worker)], check=True, capture_output=True)
    _git(worker, "config", "user.name", "Test")
    _git(worker, "config", "user.email", "test@example.com")
    return remote, seed, worker


def test_runner_completes_manifest_pull_agent_push_and_state_commit(tmp_path: Path) -> None:
    store = LocalMediaStore(tmp_path / "store")
    source = tmp_path / "song.mp3"
    source.write_bytes(b"verified input")
    input_identity = HandoffIdentity("003ch", "demo", "suno-download")
    input_manifest = push_handoff(store, input_identity, (HandoffSource(source, "song.mp3"),))
    manifest_key = "003ch/demo/suno-download/manifest.json"
    remote, _, worker = _repositories(tmp_path, manifest_key, input_manifest.root_sha256)
    calls: list[tuple[str, str]] = []

    def agent(agent: str, prompt: str, cwd: Path) -> None:
        calls.append((agent, prompt))
        assert (cwd / "media" / "song.mp3").read_bytes() == b"verified input"
        output = cwd / "outputs" / "Master.mp4"
        output.parent.mkdir(parents=True)
        output.write_bytes(b"generated output")
        state_path = cwd / "collections" / "planning" / "demo" / "workflow-state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["runner_completed"] = True
        state_path.write_text(json.dumps(state) + "\n", encoding="utf-8")

    request = SandwichRequest(
        channel_dir=worker,
        collection_dir="collections/planning/demo",
        channel="003ch",
        collection="demo",
        agent="claude",
        prompt="/wf-new --auto",
        commit_message="chore: runner state",
        input_handoff="suno-download",
        input_destination="media",
        output_handoff="master",
        output_root="outputs",
        output_files=("Master.mp4",),
    )

    run_sandwich(request, store, agent_runner=agent)

    assert calls == [("claude", "/wf-new --auto")]
    checkout = tmp_path / "verify"
    subprocess.run(["git", "clone", "--branch", "main", str(remote), str(checkout)], check=True, capture_output=True)
    pushed_state = json.loads(
        (checkout / "collections" / "planning" / "demo" / "workflow-state.json").read_text(encoding="utf-8")
    )
    assert pushed_state["runner_completed"] is True
    destination = tmp_path / "roundtrip"
    pull_handoff(store, HandoffIdentity("003ch", "demo", "master"), destination)
    assert (destination / "Master.mp4").read_bytes() == b"generated output"


def test_shell_is_platform_neutral_uv_direct_and_agent_boundary_is_single() -> None:
    root = REPO_ROOT
    script = (root / ".claude/skills/wf-new/references/run-sandwich.sh").read_text(encoding="utf-8")
    owner = (root / "src/youtube_automation/application/hybrid_runner.py").read_text(encoding="utf-8")

    assert "git clone" in script
    assert "uv run --frozen yt-hybrid-runner" in script
    assert "nix" not in script.lower()
    assert "GITHUB_" not in script
    assert owner.count("subprocess.run(command") == 1


def test_runner_rejects_manifest_that_does_not_match_git_state_before_agent(tmp_path: Path) -> None:
    store = LocalMediaStore(tmp_path / "store")
    source = tmp_path / "song.mp3"
    source.write_bytes(b"verified input")
    push_handoff(
        store,
        HandoffIdentity("003ch", "demo", "suno-download"),
        (HandoffSource(source, "song.mp3"),),
    )
    _, _, worker = _repositories(
        tmp_path,
        "003ch/demo/suno-download/manifest.json",
        "0" * 64,
    )
    called = False

    def agent(_agent: str, _prompt: str, _cwd: Path) -> None:
        nonlocal called
        called = True

    request = SandwichRequest(
        channel_dir=worker,
        collection_dir="collections/planning/demo",
        channel="003ch",
        collection="demo",
        agent="claude",
        prompt="/wf-new --auto",
        commit_message="chore: runner state",
        input_handoff="suno-download",
        input_destination="media",
    )

    with pytest.raises(StateSyncError, match="manifestが一致しません"):
        run_sandwich(request, store, agent_runner=agent)

    assert called is False


def test_posix_script_completes_local_pull_run_push(tmp_path: Path) -> None:
    root = REPO_ROOT
    store = LocalMediaStore(tmp_path / "store")
    source = tmp_path / "song.mp3"
    source.write_bytes(b"script input")
    manifest = push_handoff(
        store,
        HandoffIdentity("003ch", "demo", "suno-download"),
        (HandoffSource(source, "song.mp3"),),
    )
    remote, _, _ = _repositories(tmp_path, "003ch/demo/suno-download/manifest.json", manifest.root_sha256)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(
        """#!/bin/sh
set -eu
[ "$1" = run ] && [ "$2" = --frozen ] && [ "$3" = yt-hybrid-runner ]
shift 3
git config user.name Test
git config user.email test@example.com
exec "$YTA_TEST_PYTHON" -m youtube_automation.commands.system.hybrid_runner "$@"
""",
        encoding="utf-8",
    )
    uv.chmod(0o755)
    agent_script = bin_dir / "agent.py"
    agent_script.write_text(
        """import json
from pathlib import Path

Path("outputs").mkdir()
Path("outputs/Master.mp4").write_bytes(b"script output")
state_path = Path("collections/planning/demo/workflow-state.json")
state = json.loads(state_path.read_text())
state["script_completed"] = True
state_path.write_text(json.dumps(state) + "\\n")
""",
        encoding="utf-8",
    )
    claude = bin_dir / "claude"
    claude.write_text(
        """#!/bin/sh
set -eu
exec "$YTA_TEST_PYTHON" "$YTA_AGENT_SCRIPT"
""",
        encoding="utf-8",
    )
    claude.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "YTA_TEST_PYTHON": sys.executable,
            "YTA_AGENT_SCRIPT": str(agent_script),
        }
    )

    result = subprocess.run(
        [
            str(root / ".claude/skills/wf-new/references/run-sandwich.sh"),
            "--repository-url",
            str(remote),
            "--ref",
            "main",
            "--workspace",
            str(tmp_path / "job"),
            "--",
            "--channel-slug",
            "003ch",
            "--collection",
            "demo",
            "--collection-dir",
            "collections/planning/demo",
            "--agent",
            "claude",
            "--prompt",
            "/wf-new --auto",
            "--input-handoff",
            "suno-download",
            "--input-destination",
            "media",
            "--output-handoff",
            "master",
            "--output-root",
            "outputs",
            "--output-file",
            "Master.mp4",
            "--media-store",
            "local",
            "--local-store-root",
            str(tmp_path / "store"),
        ],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    verify = tmp_path / "script-verify"
    subprocess.run(["git", "clone", "--branch", "main", str(remote), str(verify)], check=True, capture_output=True)
    state = json.loads((verify / "collections/planning/demo/workflow-state.json").read_text(encoding="utf-8"))
    assert state["script_completed"] is True
    pulled = tmp_path / "script-roundtrip"
    pull_handoff(store, HandoffIdentity("003ch", "demo", "master"), pulled)
    assert (pulled / "Master.mp4").read_bytes() == b"script output"
