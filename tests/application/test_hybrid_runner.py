from __future__ import annotations

import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from tests.helpers.paths import REPO_ROOT
from youtube_automation.application.hybrid_runner import (
    MediaHandoffRequest,
    PipelineStagePolicy,
    SandwichRequest,
    SandwichResult,
    run_sandwich,
)
from youtube_automation.application.media_handoff import HandoffSource, pull_handoff, push_handoff
from youtube_automation.core.errors import ResourceLimitError, StateSyncError
from youtube_automation.domains.hybrid_resource_guard import GIB, HybridResourceSnapshot
from youtube_automation.domains.media_handoff_manifest import HandoffIdentity
from youtube_automation.domains.post_publish import mark_complete
from youtube_automation.infrastructure.media_store.local import LocalMediaStore


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, text=True)


def _git_output(path: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, text=True).stdout.strip()


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


class PassingResourceProbe:
    def inspect(self) -> HybridResourceSnapshot:
        return HybridResourceSnapshot(
            disk_free_bytes=3 * GIB,
            r2_retained_bytes=0,
            generation_cost_usd=Decimal("0"),
            monthly_run_count=0,
            estimated_run_minutes=60,
        )


def test_pipeline_stage_policy_resolves_media_prompt_verify_and_control_allowlist(tmp_path: Path) -> None:
    store = LocalMediaStore(tmp_path / "store")
    source = tmp_path / "song.mp3"
    source.write_bytes(b"verified input")
    manifest = push_handoff(
        store,
        HandoffIdentity("003ch", "demo", "suno-download"),
        (HandoffSource(source, "song.mp3"),),
    )
    _, _, worker = _repositories(
        tmp_path,
        "003ch/demo/suno-download/manifest.json",
        manifest.root_sha256,
    )
    request = SandwichRequest(
        channel_dir=worker,
        channel="003ch",
        collection="demo",
        agent="claude",
        prompt="/wf-new --auto",
        commit_message="chore: runner state",
        media_handoff=MediaHandoffRequest(
            collection_dir="collections/planning/demo",
            input_handoff="suno-download",
            input_destination="media",
            output_handoff="master",
            output_root="outputs",
            output_files=("Master.mp4",),
        ),
    )
    policy = PipelineStagePolicy(request, store)

    policy.resolve()
    assert (worker / "media" / "song.mp3").read_bytes() == b"verified input"
    assert policy.prompt_for() == "/wf-new --auto"
    (worker / "outputs").mkdir()
    (worker / "outputs" / "Master.mp4").write_bytes(b"output")
    assert policy.verify() == "demo"
    pulled = tmp_path / "pulled"
    pull_handoff(store, HandoffIdentity("003ch", "demo", "master"), pulled)
    assert (pulled / "Master.mp4").read_bytes() == b"output"
    policy.allows(worker, {"collections/planning/demo/workflow-state.json"})
    with pytest.raises(StateSyncError, match="Git制御面state以外"):
        policy.allows(worker, {"unexpected.json"})


def test_pipeline_stage_policy_resolve_rejects_manifest_mismatch(tmp_path: Path) -> None:
    store = LocalMediaStore(tmp_path / "store")
    source = tmp_path / "song.mp3"
    source.write_bytes(b"verified input")
    push_handoff(
        store,
        HandoffIdentity("003ch", "demo", "suno-download"),
        (HandoffSource(source, "song.mp3"),),
    )
    _, _, worker = _repositories(tmp_path, "003ch/demo/suno-download/manifest.json", "0" * 64)
    request = SandwichRequest(
        channel_dir=worker,
        channel="003ch",
        collection="demo",
        agent="claude",
        prompt="/wf-new --auto",
        commit_message="chore: runner state",
        media_handoff=MediaHandoffRequest(
            collection_dir="collections/planning/demo",
            input_handoff="suno-download",
            input_destination="media",
        ),
    )

    with pytest.raises(StateSyncError, match="workflow-state handoff参照"):
        PipelineStagePolicy(request, store).resolve()


def test_pipeline_stage_policy_allows_requires_resolve_snapshot(tmp_path: Path) -> None:
    store = LocalMediaStore(tmp_path / "store")
    _, _, worker = _repositories(tmp_path, "003ch/demo/suno-download/manifest.json", "0" * 64)
    request = SandwichRequest(
        channel_dir=worker,
        channel="003ch",
        collection="demo",
        agent="claude",
        prompt="/wf-new --auto",
        commit_message="chore: runner state",
    )

    with pytest.raises(StateSyncError, match="resolveより先にallows"):
        PipelineStagePolicy(request, store).allows(worker, set())


def _planning_repository(tmp_path: Path, *, phase: str = "planning") -> tuple[Path, Path]:
    remote = tmp_path / "planning-remote.git"
    seed = tmp_path / "planning-seed"
    worker = tmp_path / "planning-worker"
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
                "phase": phase,
                "created_at": "2026-01-01T00:00:00Z",
                "planning": {"generated": phase == "prepared", "music": {"engine": "suno"}},
                "assets": {"music_prompts": phase == "prepared"},
                "upload": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    if phase == "prepared":
        docs = collection / "20-documentation"
        docs.mkdir()
        (docs / "suno-prompts.json").write_text("{}\n", encoding="utf-8")
        (docs / "suno-prompts.html").write_text("<!doctype html>\n", encoding="utf-8")
    _git(seed, "add", ".")
    _git(seed, "commit", "-m", "initial")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "main")
    subprocess.run(["git", "clone", "--branch", "main", str(remote), str(worker)], check=True, capture_output=True)
    _git(worker, "config", "user.name", "Test")
    _git(worker, "config", "user.email", "test@example.com")
    return remote, worker


def _post_publish_repository(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "post-remote.git"
    seed = tmp_path / "post-seed"
    worker = tmp_path / "post-worker"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(tmp_path, "init", "-b", "main", str(seed))
    _git(seed, "config", "user.name", "Test")
    _git(seed, "config", "user.email", "test@example.com")
    collection = seed / "collections" / "live" / "demo"
    collection.mkdir(parents=True)
    (seed / ".gitignore").write_text(
        "*\n!.gitignore\n!collections/\n!collections/live/\n!collections/live/demo/\n!collections/live/demo/workflow-state.json\n!post_publish_history.json\n!pinned_comment_history.json\n",
        encoding="utf-8",
    )
    (collection / "workflow-state.json").write_text(
        json.dumps(
            {
                "phase": "complete",
                "stage": "live",
                "created_at": "2026-01-01T00:00:00Z",
                "assets": {},
                "upload": {"video_id": "video-1"},
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
    return remote, worker


def test_cloud_planning_commits_prompt_artifacts_and_prepared_state_as_single_writer(tmp_path: Path) -> None:
    remote, worker = _planning_repository(tmp_path)

    def agent(agent: str, prompt: str, cwd: Path) -> None:
        assert (agent, prompt) == ("claude", "/wf-new --auto")
        collection = cwd / "collections" / "planning" / "demo"
        docs = collection / "20-documentation"
        docs.mkdir()
        (docs / "plan_proposals.json").write_text("{}\n", encoding="utf-8")
        (docs / "plan_proposals.html").write_text("<!doctype html>\n", encoding="utf-8")
        (docs / "suno-prompts.json").write_text("{}\n", encoding="utf-8")
        (docs / "suno-prompts.html").write_text("<!doctype html>\n", encoding="utf-8")
        state_path = collection / "workflow-state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["phase"] = "prepared"
        state["planning"]["generated"] = True
        state["assets"]["music_prompts"] = True
        state_path.write_text(json.dumps(state) + "\n", encoding="utf-8")

    result = run_sandwich(
        SandwichRequest(
            channel_dir=worker,
            channel="003ch",
            collection="",
            agent="claude",
            prompt="/wf-new --auto",
            commit_message="chore: cloud planning",
            stage="planning",
        ),
        LocalMediaStore(tmp_path / "store"),
        resource_probe=PassingResourceProbe(),
        agent_runner=agent,
    )

    assert result == SandwichResult("completed", "demo")
    verify = tmp_path / "planning-verify"
    subprocess.run(["git", "clone", "--branch", "main", str(remote), str(verify)], check=True, capture_output=True)
    collection = verify / "collections" / "planning" / "demo"
    assert (collection / "20-documentation" / "plan_proposals.json").is_file()
    assert json.loads((collection / "workflow-state.json").read_text(encoding="utf-8"))["phase"] == "prepared"


def test_cloud_planning_waits_without_agent_or_commit_after_planning_phase(tmp_path: Path) -> None:
    remote, worker = _planning_repository(tmp_path, phase="prepared")
    called = False

    def agent(_agent: str, _prompt: str, _cwd: Path) -> None:
        nonlocal called
        called = True

    result = run_sandwich(
        SandwichRequest(
            channel_dir=worker,
            channel="003ch",
            collection="",
            agent="claude",
            prompt="/wf-new --auto",
            commit_message="chore: cloud planning",
            stage="planning",
        ),
        LocalMediaStore(tmp_path / "store"),
        resource_probe=PassingResourceProbe(),
        agent_runner=agent,
    )

    assert result == SandwichResult("waiting", "demo")
    assert called is False
    assert _git_output(worker, "rev-parse", "HEAD") == _git_output(
        tmp_path, "--git-dir", str(remote), "rev-parse", "refs/heads/main"
    )


def test_cloud_post_publish_commits_only_verified_tracking(tmp_path: Path) -> None:
    remote, worker = _post_publish_repository(tmp_path)

    def agent(agent: str, prompt: str, cwd: Path) -> None:
        assert agent == "claude"
        assert prompt.startswith("/wf-new --auto\nCloud post-publish target is collection 'demo'.")
        collection = cwd / "collections" / "live" / "demo"
        for step in ("playlist-assignment", "pinned-comment", "metadata-audit"):
            mark_complete(cwd, collection, step)
        (cwd / "pinned_comment_history.json").write_text(
            json.dumps({"schema_version": 1, "posted": {"video-1": {"comment_id": "comment-1"}}}) + "\n",
            encoding="utf-8",
        )

    result = run_sandwich(
        SandwichRequest(
            channel_dir=worker,
            channel="003ch",
            collection="",
            agent="claude",
            prompt="/wf-new --auto",
            commit_message="chore: cloud post publish",
            stage="post-publish",
        ),
        LocalMediaStore(tmp_path / "store"),
        resource_probe=PassingResourceProbe(),
        agent_runner=agent,
    )

    assert result == SandwichResult("completed", "demo")
    verify = tmp_path / "post-verify"
    subprocess.run(["git", "clone", "--branch", "main", str(remote), str(verify)], check=True, capture_output=True)
    history = json.loads((verify / "post_publish_history.json").read_text(encoding="utf-8"))
    assert set(history["videos"]["video-1"]["completed"]) == {
        "playlist-assignment",
        "pinned-comment",
        "metadata-audit",
    }


def test_cloud_post_publish_rejects_tracking_without_pinned_actual_artifact(tmp_path: Path) -> None:
    _, worker = _post_publish_repository(tmp_path)

    def agent(_agent: str, _prompt: str, cwd: Path) -> None:
        collection = cwd / "collections" / "live" / "demo"
        for step in ("playlist-assignment", "pinned-comment", "metadata-audit"):
            mark_complete(cwd, collection, step)

    with pytest.raises(StateSyncError, match="pinned comment actual artifact"):
        run_sandwich(
            SandwichRequest(
                channel_dir=worker,
                channel="003ch",
                collection="",
                agent="claude",
                prompt="/wf-new --auto",
                commit_message="chore: cloud post publish",
                stage="post-publish",
            ),
            LocalMediaStore(tmp_path / "store"),
            resource_probe=PassingResourceProbe(),
            agent_runner=agent,
        )


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
        channel="003ch",
        collection="demo",
        agent="claude",
        prompt="/wf-new --auto",
        commit_message="chore: runner state",
        media_handoff=MediaHandoffRequest(
            collection_dir="collections/planning/demo",
            input_handoff="suno-download",
            input_destination="media",
            output_handoff="master",
            output_root="outputs",
            output_files=("Master.mp4",),
        ),
    )

    run_sandwich(request, store, resource_probe=PassingResourceProbe(), agent_runner=agent)

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
    assert "uv run --frozen yt-human-tasks" in script
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
        channel="003ch",
        collection="demo",
        agent="claude",
        prompt="/wf-new --auto",
        commit_message="chore: runner state",
        media_handoff=MediaHandoffRequest(
            collection_dir="collections/planning/demo",
            input_handoff="suno-download",
            input_destination="media",
        ),
    )

    with pytest.raises(StateSyncError, match="manifestが一致しません"):
        run_sandwich(request, store, resource_probe=PassingResourceProbe(), agent_runner=agent)

    assert called is False


def test_runner_emits_rejection_and_has_no_git_media_or_agent_side_effect_when_resource_limit_exceeded(
    tmp_path: Path,
) -> None:
    store = LocalMediaStore(tmp_path / "store")
    manifest_key = "003ch/demo/suno-download/manifest.json"
    _, _, worker = _repositories(tmp_path, manifest_key, "0" * 64)
    head_before = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=worker, check=True, capture_output=True, text=True
    ).stdout.strip()
    calls: list[str] = []
    events = []

    class RejectedResourceProbe:
        def inspect(self) -> HybridResourceSnapshot:
            return HybridResourceSnapshot(
                disk_free_bytes=int(2.5 * GIB) - 1,
                r2_retained_bytes=0,
                generation_cost_usd=Decimal("0"),
                monthly_run_count=0,
                estimated_run_minutes=60,
            )

    request = SandwichRequest(
        channel_dir=worker,
        channel="003ch",
        collection="demo",
        agent="claude",
        prompt="/wf-new --auto",
        commit_message="chore: runner state",
        media_handoff=MediaHandoffRequest(
            collection_dir="collections/planning/demo",
            input_handoff="suno-download",
            input_destination="media",
        ),
    )

    with pytest.raises(ResourceLimitError, match="resource guard rejected"):
        run_sandwich(
            request,
            store,
            resource_probe=RejectedResourceProbe(),
            agent_runner=lambda *_args: calls.append("agent"),
            on_resource_event=events.append,
        )

    assert calls == []
    assert not (worker / "media").exists()
    assert (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=worker, check=True, capture_output=True, text=True
        ).stdout.strip()
        == head_before
    )
    assert len(events) == 1
    assert "disk" in events[0].detail


def test_runner_emits_rejection_and_stops_when_resource_inspection_fails(tmp_path: Path) -> None:
    store = LocalMediaStore(tmp_path / "store")
    _, _, worker = _repositories(tmp_path, "unused/manifest.json", "0" * 64)
    events = []

    class FailingResourceProbe:
        def inspect(self) -> HybridResourceSnapshot:
            raise ResourceLimitError("capacity probe unavailable")

    request = SandwichRequest(
        channel_dir=worker,
        channel="003ch",
        collection="demo",
        agent="claude",
        prompt="/wf-new --auto",
        commit_message="chore: runner state",
        media_handoff=MediaHandoffRequest(collection_dir="collections/planning/demo"),
    )

    with pytest.raises(ResourceLimitError, match="probe unavailable"):
        run_sandwich(request, store, resource_probe=FailingResourceProbe(), on_resource_event=events.append)

    assert len(events) == 1
    assert "probe" in events[0].detail


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
[ "$1" = run ] && [ "$2" = --frozen ]
if [ "$3" = yt-human-tasks ]; then exit 0; fi
[ "$3" = yt-hybrid-runner ]
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
    assert "hybrid_resource_observed" in result.stderr
    assert "monthly_runs=1" in result.stderr
    assert "disk_free=" in result.stderr
    assert "r2_retained=" in result.stderr
    assert "projected_actions_minutes=" in result.stderr
    verify = tmp_path / "script-verify"
    subprocess.run(["git", "clone", "--branch", "main", str(remote), str(verify)], check=True, capture_output=True)
    state = json.loads((verify / "collections/planning/demo/workflow-state.json").read_text(encoding="utf-8"))
    assert state["script_completed"] is True
    pulled = tmp_path / "script-roundtrip"
    pull_handoff(store, HandoffIdentity("003ch", "demo", "master"), pulled)
    assert (pulled / "Master.mp4").read_bytes() == b"script output"
