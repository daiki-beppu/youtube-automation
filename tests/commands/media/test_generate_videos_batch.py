from __future__ import annotations

import hashlib
import json
import re
import sys
import threading
import time
from pathlib import Path

import pytest

from tests.helpers.paths import REPO_ROOT
from youtube_automation.commands.media import generate_videos_batch as batch
from youtube_automation.core.errors import ConfigError


def _help_text(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> str:
    monkeypatch.setattr(sys, "argv", ["yt-generate-videos-batch", "--help"])

    with pytest.raises(SystemExit) as exc_info:
        batch.main()

    assert exc_info.value.code == 0
    return " ".join(capsys.readouterr().out.split())


def test_help_explains_default_stage_and_batch_target(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    help_text = _help_text(monkeypatch, capsys)

    assert "既定では collections/planning/ のみ" in help_text
    assert "--include-live で collections/live/ も含める" in help_text
    assert "assets.master_audio が設定済み" in help_text
    assert "assets.master_video: null" in help_text


def test_help_explains_max_workers_resolution_without_false_choices(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    help_text = _help_text(monkeypatch, capsys)

    assert "1 以上" in help_text
    assert "CLI > YT_VIDEOUP_MAX_WORKERS > channel skill-config > CPU 検出 > 3" in help_text
    assert "config/skills/video.yaml::generate.batch.max_workers" in help_text
    assert re.search(r"--max-workers MAX_WORKERS\b", help_text)
    assert "--max-workers {" not in help_text


def test_help_explains_success_state_update_and_partial_failure_exit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    help_text = _help_text(monkeypatch, capsys)

    assert "成功した collection のみ assets.master_video を更新" in help_text
    assert "部分失敗は non-zero" in help_text


def _collection(root: Path, stage: str, slug: str, *, audio: object, video: object) -> Path:
    collection = root / "collections" / stage / slug
    (collection / "01-master").mkdir(parents=True)
    (collection / "workflow-state.json").write_text(
        json.dumps({"assets": {"master_audio": audio, "master_video": video}, "future_section": {"keep": True}}),
        encoding="utf-8",
    )
    return collection


def test_find_batch_targets_uses_v2_assets_and_optionally_includes_live(tmp_path: Path) -> None:
    planning_target = _collection(tmp_path, "planning", "a", audio="master.mp3", video=None)
    _collection(tmp_path, "planning", "b", audio=None, video=None)
    _collection(tmp_path, "planning", "c", audio="master.mp3", video="done.mp4")
    live_target = _collection(tmp_path, "live", "d", audio="master.mp3", video=None)

    assert batch.find_batch_targets(tmp_path) == [planning_target.resolve()]
    assert batch.find_batch_targets(tmp_path, include_live=True) == [
        planning_target.resolve(),
        live_target.resolve(),
    ]


def test_find_batch_targets_defaults_to_selected_channel(monkeypatch, tmp_path: Path) -> None:
    target = _collection(tmp_path, "planning", "a", audio="master.mp3", video=None)
    monkeypatch.setattr(batch, "channel_dir", lambda: tmp_path)

    assert batch.find_batch_targets() == [target.resolve()]


def test_find_batch_targets_does_not_use_legacy_state_shape(tmp_path: Path) -> None:
    collection = _collection(tmp_path, "planning", "legacy", audio=None, video=None)
    state_path = collection / "workflow-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update({"production": {"generated": False}, "music": {"approved": True}})
    state_path.write_text(json.dumps(state), encoding="utf-8")

    assert batch.find_batch_targets(tmp_path) == []


def test_video_generate_auto_detection_matches_implementation_contract() -> None:
    skill = (REPO_ROOT / ".claude/skills/video/references/generate.md").read_text(encoding="utf-8")
    expected = "`assets.master_audio` が設定済み（`null` 以外）かつ `assets.master_video` が `null` のコレクション"
    assert expected in skill


def test_run_batch_parallel_invokes_existing_script_concurrently(monkeypatch, tmp_path: Path) -> None:
    targets = [tmp_path / name for name in ("a", "b")]
    for target in targets:
        target.mkdir()
    script = tmp_path / "generate_videos.sh"
    script.touch()
    barrier = threading.Barrier(2)
    calls: list[list[str]] = []

    class Completed:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append(command)
        barrier.wait(timeout=2)
        time.sleep(0.01)
        return Completed()

    monkeypatch.setattr(batch.subprocess, "run", fake_run)

    results = batch.run_batch_parallel(targets, max_workers=2, script_path=script)

    assert [result.collection for result in results] == [target.resolve() for target in targets]
    assert all(result.succeeded for result in results)
    assert sorted(calls) == sorted(
        [
            ["bash", str(script.resolve()), str(targets[0].resolve())],
            ["bash", str(script.resolve()), str(targets[1].resolve())],
        ]
    )


def test_update_workflow_states_records_generated_video_for_success_only(tmp_path: Path) -> None:
    success = _collection(tmp_path, "planning", "success", audio="master.mp3", video=None)
    failed = _collection(tmp_path, "planning", "failed", audio="master.mp3", video=None)
    (success / "01-master" / "Success-Master.mp4").write_bytes(b"generated video")

    updated = batch.update_workflow_states(
        [
            batch.BatchResult(success, 0),
            batch.BatchResult(failed, 1, stderr="ffmpeg failed"),
        ]
    )

    success_state = json.loads((success / "workflow-state.json").read_text(encoding="utf-8"))
    failed_state = json.loads((failed / "workflow-state.json").read_text(encoding="utf-8"))
    assert updated == {success: "Success-Master.mp4"}
    assert success_state["assets"]["master_video"] == "Success-Master.mp4"
    assert success_state["master_video_approved_digest"] == hashlib.sha256(b"generated video").hexdigest()
    assert success_state["future_section"] == {"keep": True}
    assert "updated_at" in success_state
    assert failed_state["assets"]["master_video"] is None
    assert "master_video_approved_digest" not in failed_state
    assert (success / "workflow-state.json.lock").is_file()


def test_update_workflow_states_accepts_successful_collection_paths(tmp_path: Path) -> None:
    collection = _collection(tmp_path, "planning", "success", audio="master.mp3", video=None)
    (collection / "01-master" / "Success-Master.mp4").touch()

    assert batch.update_workflow_states([collection]) == {collection: "Success-Master.mp4"}


def test_main_state_write_partial_failure_leaves_only_failed_target_for_retry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    first = _collection(tmp_path, "planning", "first", audio="master.mp3", video=None)
    second = _collection(tmp_path, "planning", "second", audio="master.mp3", video=None)
    (first / "01-master" / "First-Master.mp4").touch()
    (second / "01-master" / "Second-Master.mp4").touch()
    script = tmp_path / ".claude" / "skills" / "video" / "references" / "generate_videos.sh"
    script.parent.mkdir(parents=True)
    script.touch()
    results = [batch.BatchResult(first, 0), batch.BatchResult(second, 0)]
    monkeypatch.setattr("sys.argv", ["yt-generate-videos-batch"])
    monkeypatch.setattr(batch, "channel_dir", lambda: tmp_path)
    monkeypatch.setattr(batch, "run_batch_parallel", lambda *_args, **_kwargs: results)
    original_update = batch.update_workflow_state
    writes = 0

    def fail_second(path, updater):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("disk full")
        return original_update(path, updater)

    monkeypatch.setattr(batch, "update_workflow_state", fail_second)

    assert batch.main() == 1

    first_state = json.loads((first / "workflow-state.json").read_text(encoding="utf-8"))
    second_state = json.loads((second / "workflow-state.json").read_text(encoding="utf-8"))
    assert first_state["assets"]["master_video"] == "First-Master.mp4"
    assert second_state["assets"]["master_video"] is None
    assert batch.find_batch_targets(tmp_path) == [second.resolve()]


@pytest.mark.parametrize(
    ("cli", "env", "config", "cpu", "expected"),
    [
        (9, {batch.MAX_WORKERS_ENV: "8"}, {"batch": {"max_workers": 7}}, 6, 9),
        (None, {batch.MAX_WORKERS_ENV: "8"}, {"batch": {"max_workers": 7}}, 6, 8),
        (None, {}, {"batch": {"max_workers": 7}}, 6, 7),
        (None, {}, {}, 6, 6),
        (None, {}, {}, 0, batch.DEFAULT_MAX_WORKERS),
    ],
)
def test_resolve_max_workers_precedence(cli, env, config, cpu, expected) -> None:
    assert (
        batch.resolve_max_workers(
            cli,
            environ=env,
            skill_config=config,
            detected_cpu_count=cpu,
        )
        == expected
    )


@pytest.mark.parametrize("value", ["0", "abc", "1.5"])
def test_resolve_max_workers_rejects_invalid_env(value: str) -> None:
    with pytest.raises(ConfigError):
        batch.resolve_max_workers(
            None,
            environ={batch.MAX_WORKERS_ENV: value},
            skill_config={},
            detected_cpu_count=4,
        )
