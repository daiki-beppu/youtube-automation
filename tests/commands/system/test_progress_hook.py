from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest

from tests.helpers.paths import FIXTURES_DIR
from youtube_automation.commands.system import progress_hook
from youtube_automation.domains.documents.schema_registry import RepositorySchema
from youtube_automation.infrastructure.documents.publishing import publish_json_document

_FIXTURES = FIXTURES_DIR / "progress_hook"


def _analysis_pair(reports: Path, report_date: str) -> None:
    path = reports / f"analysis_{report_date}.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "generated_at": "2026-07-20T00:00:00Z",
                "summary": "分析サマリ",
                "inputs": {},
                "cli_outputs": {},
                "vpd_ranking": {},
                "win_pattern": {},
                "strategic_improvements": [],
                "next_collection_candidates": [],
                "action_plan": [],
                "strategic_discussion": [],
            }
        ),
        encoding="utf-8",
    )
    publish_json_document(path, RepositorySchema.ANALYSIS_REPORT)


def _run(payload: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    exit_code = progress_hook.main([], stdin=io.StringIO(payload))
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def _write_collection(
    channel: Path,
    location: str,
    name: str,
    state: dict[str, object],
    *,
    modified_at: float | None = None,
) -> Path:
    collection = channel / "collections" / location / name
    collection.mkdir(parents=True)
    state_path = collection / "workflow-state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    if modified_at is not None:
        os.utime(state_path, (modified_at, modified_at))
    return collection


def _progress_message(
    channel: Path,
    capsys: pytest.CaptureFixture[str],
    *,
    command: str = "uv run yt-generate-videos-batch",
    event: str = "PreToolUse",
) -> str:
    payload = json.dumps(
        {
            "cwd": str(channel),
            "hook_event_name": event,
            "tool_name": "Bash",
            "tool_input": {"command": command, "run_in_background": True},
        }
    )
    exit_code, stdout, stderr = _run(payload, capsys)
    assert exit_code == 0
    assert stderr == ""
    return json.loads(stdout)["systemMessage"]


def test_should_emit_progress_system_message_when_background_bash_starts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"run_in_background": True}})

    exit_code, stdout, stderr = _run(payload, capsys)

    assert exit_code == 0
    message = json.loads(stdout)["systemMessage"]
    assert "▸" not in message
    assert "  ⋯  Bash" in message
    assert stderr == ""


def test_should_emit_nothing_when_foreground_bash_starts(capsys: pytest.CaptureFixture[str]) -> None:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {}})

    exit_code, stdout, stderr = _run(payload, capsys)

    assert exit_code == 0
    assert stdout == ""
    assert stderr == ""


def test_should_keep_fixed_pipeline_when_repository_has_no_collections(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    message = _progress_message(tmp_path, capsys, command="gh pr checks 42")

    assert "  ✓  マスター化" in message
    assert "  ○  動画化" in message
    assert "  ⋯  gh" in message


def test_should_mark_real_asset_stages_from_workflow_state(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state = json.loads((_FIXTURES / "workflow-state-mastered.json").read_text(encoding="utf-8"))
    _write_collection(tmp_path, "planning", "mastered-collection", state)

    message = _progress_message(tmp_path, capsys)

    assert "  ✓  企画" in message
    assert "  ✓  音源生成" in message
    assert "  ✓  マスター化" in message
    assert "  ▸  動画化" in message
    assert "  ✓  サムネイル" in message
    assert "  ○  アップロード" in message


def test_should_leave_source_and_later_stages_incomplete_without_raw_master(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_collection(
        tmp_path,
        "planning",
        "new-collection",
        {
            "phase": "prepared",
            "assets": {"raw_master": None, "master_audio": None, "video": None, "thumbnail": None},
        },
    )

    message = _progress_message(tmp_path, capsys, command="uv run yt-generate-master")

    assert "  ✓  企画" in message
    assert "  ○  音源生成" in message
    assert "  ▸  マスター化" in message
    assert "  ○  動画化" in message


def test_should_use_raw_master_for_mastering_when_manual_mastering_is_skipped(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_collection(
        tmp_path,
        "planning",
        "raw-final",
        {
            "phase": "prepared",
            "assets": {"raw_master": "raw.wav", "master_audio": None},
        },
    )
    config_dir = tmp_path / "config" / "channel"
    config_dir.mkdir(parents=True)
    (config_dir / "workflow.json").write_text(
        json.dumps({"workflow": {"wf_next": {"skip_manual_mastering": True}}}),
        encoding="utf-8",
    )

    message = _progress_message(tmp_path, capsys, command="uv run yt-generate-videos-batch")

    assert "  ✓  マスター化" in message


def test_should_prefer_named_collection_across_planning_and_live(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_collection(
        tmp_path,
        "planning",
        "newer-incomplete",
        {"phase": "prepared", "assets": {"raw_master": None}},
        modified_at=200,
    )
    _write_collection(
        tmp_path,
        "live",
        "selected-live",
        {
            "phase": "complete",
            "assets": {"raw_master": "raw.wav", "master_audio": "master.wav", "video": "video.mp4"},
        },
        modified_at=100,
    )

    message = _progress_message(
        tmp_path,
        capsys,
        command="uv run yt-analytics collections/live/selected-live",
    )

    assert "  ✓  アップロード" in message
    assert "  ▸  分析" in message


def test_should_use_latest_workflow_state_when_command_does_not_name_collection(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_collection(
        tmp_path,
        "planning",
        "older-complete",
        {"phase": "complete", "assets": {"raw_master": "raw.wav"}},
        modified_at=100,
    )
    _write_collection(
        tmp_path,
        "live",
        "newer-incomplete",
        {"phase": "planning", "assets": {"raw_master": None}},
        modified_at=200,
    )

    message = _progress_message(tmp_path, capsys, command="uv run yt-generate-master")

    assert "  ○  企画" in message
    assert "  ▸  マスター化" in message


def test_should_mark_post_publish_and_analysis_from_channel_artifacts(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    collection = _write_collection(
        tmp_path,
        "live",
        "published",
        {
            "phase": "complete",
            "assets": {"raw_master": "raw.wav", "master_audio": "master.wav", "video": "video.mp4"},
            "upload": {"video_id": "video-123", "publish_at": "2026-07-20T12:00:00+09:00"},
        },
    )
    assert collection.is_dir()
    (collection / "20-documentation").mkdir()
    (collection / "20-documentation" / "community-post.txt").write_text("published", encoding="utf-8")
    config_dir = tmp_path / "config" / "channel"
    config_dir.mkdir(parents=True)
    (config_dir / "pinned-comment.json").write_text(
        json.dumps({"pinned_comment": {"history_file": "pinned_comment_history.json"}}), encoding="utf-8"
    )
    (tmp_path / "pinned_comment_history.json").write_text(
        json.dumps({"schema_version": 1, "posted": {"video-123": {"posted_at": "done"}}}), encoding="utf-8"
    )
    reports = tmp_path / "reports"
    reports.mkdir()
    _analysis_pair(reports, "20260719")
    _analysis_pair(reports, "20260720")

    message = _progress_message(
        tmp_path,
        capsys,
        command="uv run yt-analytics published",
        event="PostToolUse",
    )

    assert "  ✓  公開後処理" in message
    assert "  ✓  分析" in message


def test_should_not_complete_post_publish_for_other_video_or_analysis_before_publish(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    collection = _write_collection(
        tmp_path,
        "live",
        "published",
        {
            "phase": "complete",
            "assets": {},
            "upload": {"video_id": "target-video", "publish_at": "2026-07-20T12:00:00+09:00"},
        },
    )
    (collection / "20-documentation").mkdir()
    (collection / "20-documentation" / "community-post.txt").write_text("published", encoding="utf-8")
    config_dir = tmp_path / "config" / "channel"
    config_dir.mkdir(parents=True)
    (config_dir / "pinned-comment.json").write_text(
        json.dumps({"pinned_comment": {"history_file": "pinned_comment_history.json"}}), encoding="utf-8"
    )
    (tmp_path / "pinned_comment_history.json").write_text(
        json.dumps({"schema_version": 1, "posted": {"other-video": {"posted_at": "done"}}}), encoding="utf-8"
    )
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "analysis_20261340.json").write_text("{}", encoding="utf-8")
    _analysis_pair(reports, "20260719")

    message = _progress_message(tmp_path, capsys, command="gh pr checks 42")

    assert "  ○  公開後処理" in message
    assert "  ○  分析" in message


@pytest.mark.parametrize("bad_state", ["not-json", "[]", '{"phase":"prepared","assets":[]}'])
def test_should_fall_back_to_fixed_pipeline_when_workflow_state_is_invalid(
    tmp_path: Path,
    bad_state: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    collection = tmp_path / "collections" / "planning" / "broken"
    collection.mkdir(parents=True)
    (collection / "workflow-state.json").write_text(bad_state, encoding="utf-8")

    message = _progress_message(tmp_path, capsys, command="gh pr checks 42")

    assert "  ✓  企画" in message
    assert "  ✓  マスター化" in message
    assert "  ○  動画化" in message
    assert "  ⋯  gh" in message


@pytest.mark.parametrize(
    ("command", "stage"),
    [
        ("uv run yt-generate-lyria-master", "音源生成"),
        ("uv run yt-generate-suno", "音源生成"),
        ("uv run yt-suno-unattended-request", "音源生成"),
        ("uv run yt-generate-master", "マスター化"),
        ("uv run yt-finalize-master", "マスター化"),
        ("uv run yt-generate-videos-batch", "動画化"),
        ("uv run yt-generate-loop-video", "動画化"),
        ("ffmpeg -i input.mp3 output.mp4", "動画化"),
        ("uv run yt-generate-image", "サムネイル"),
        ("uv run yt-thumbnail-text", "サムネイル"),
        ("uv run yt-upload-collection", "アップロード"),
        ("uv run yt-upload-auto", "アップロード"),
        ("uv run yt-upload-shorts", "アップロード"),
        ("uv run yt-pinned-comment", "公開後処理"),
        ("uv run yt-metadata-audit", "公開後処理"),
        ("uv run yt-comments-reply", "公開後処理"),
        ("uv run yt-analytics", "分析"),
        ("uv run yt-benchmark-collect", "分析"),
        ("uv run yt-benchmark-comments", "分析"),
        ("uv run yt-video-analyze", "分析"),
    ],
)
def test_should_mark_classified_stage_for_long_foreground_command(
    command: str,
    stage: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}})

    exit_code, stdout, stderr = _run(payload, capsys)

    message = json.loads(stdout)["systemMessage"]
    assert exit_code == 0
    assert f"  ▸  {stage} — {command.split()[2] if command.startswith('uv run ') else command.split()[0]}" in message
    assert message.count("▸") == 1
    assert stderr == ""


def test_should_emit_unclassified_agent_work_with_description(
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Agent",
            "tool_input": {"subagent_type": "Explore", "description": "hook 定義箇所を調査"},
        }
    )

    exit_code, stdout, stderr = _run(payload, capsys)

    message = json.loads(stdout)["systemMessage"]
    assert exit_code == 0
    assert "▸" not in message
    assert "  ⋯  Explore — hook 定義箇所を調査" in message
    assert stderr == ""


@pytest.mark.parametrize(
    ("tool_name", "tool_input", "expected"),
    [
        ("Task", {"subagent_type": "general-purpose"}, "general-purpose"),
        ("Workflow", {}, "Workflow"),
        ("Bash", {"run_in_background": True, "command": "gh pr checks 42"}, "gh"),
    ],
)
def test_should_use_nonempty_fallback_for_unclassified_work(
    tool_name: str,
    tool_input: dict[str, object],
    expected: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool_name, "tool_input": tool_input})

    exit_code, stdout, stderr = _run(payload, capsys)

    message = json.loads(stdout)["systemMessage"]
    assert exit_code == 0
    assert f"  ⋯  {expected}" in message
    assert stderr == ""


def test_should_mark_classified_stage_complete_after_displayed_command_returns(
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = json.dumps(
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "ffmpeg -i input.mp3 output.mp4"},
        }
    )

    exit_code, stdout, stderr = _run(payload, capsys)

    message = json.loads(stdout)["systemMessage"]
    assert exit_code == 0
    assert "  ✓  動画化 — ffmpeg" in message
    assert "▸" not in message
    assert stderr == ""


def test_should_emit_nothing_after_unclassified_foreground_command_returns(
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}})

    exit_code, stdout, stderr = _run(payload, capsys)

    assert exit_code == 0
    assert stdout == ""
    assert stderr == ""


@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        json.dumps({"tool_name": "Bash", "tool_input": []}),
        json.dumps({"tool_name": "Bash", "tool_input": {"run_in_background": "true"}}),
    ],
)
def test_should_emit_nothing_when_payload_is_invalid_or_unsupported(
    payload: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code, stdout, stderr = _run(payload, capsys)

    assert exit_code == 0
    assert stdout == ""
    assert stderr == ""
