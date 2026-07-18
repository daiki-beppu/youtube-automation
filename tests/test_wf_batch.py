"""yt-wf-batch（wf_batch.py）のユニットテスト（#1667）。

- 対象抽出フィルタリング（discover_targets / select_targets）
- 1 件失敗時の後続続行
- summary.json / per-collection log の生成
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from youtube_automation.scripts import wf_batch
from youtube_automation.utils.exceptions import ValidationError


def _state(
    phase: str = "prepared",
    music_prompts: bool = True,
    raw_master: str | None = None,
    url: str | None = "https://suno.com/playlist/abc123",
) -> dict:
    return {
        "collection_name": "test-collection",
        "phase": phase,
        "stage": "planning",
        "assets": {
            "thumbnail": True,
            "loop_video": False,
            "music_prompts": music_prompts,
            "raw_master": raw_master,
            "master_audio": None,
            "master_video": None,
            "description": False,
        },
        "planning": {"music": {"engine": "suno", "suno_playlist_url": url}},
        "updated_at": "2026-07-01T00:00:00.000Z",
    }


def _make_collection(
    planning_root: Path,
    slug: str,
    state: dict | str,
    audio_files: tuple[str, ...] = ("01-track.mp3",),
) -> Path:
    coll = planning_root / slug
    for sub in ("01-master", "02-Individual-music", "10-assets", "20-documentation"):
        (coll / sub).mkdir(parents=True)
    for name in audio_files:
        (coll / "02-Individual-music" / name).write_bytes(b"audio")
    payload = state if isinstance(state, str) else json.dumps(state, ensure_ascii=False, indent=2) + "\n"
    (coll / "workflow-state.json").write_text(payload, encoding="utf-8")
    return coll


class TestDiscoverTargets:
    def test_prepared_with_url_and_audio_is_target(self, tmp_path):
        _make_collection(tmp_path, "001-a-collection", _state())

        targets, excluded = wf_batch.discover_targets(tmp_path)

        assert [t.slug for t in targets] == ["001-a-collection"]
        assert excluded == []

    def test_missing_url_is_excluded_with_warning(self, tmp_path):
        _make_collection(tmp_path, "001-a-collection", _state(url=None))

        targets, excluded = wf_batch.discover_targets(tmp_path)

        assert targets == []
        assert len(excluded) == 1
        assert excluded[0].slug == "001-a-collection"
        assert "suno_playlist_url" in excluded[0].reason

    def test_missing_audio_is_excluded_with_warning(self, tmp_path):
        _make_collection(tmp_path, "001-a-collection", _state(), audio_files=())

        targets, excluded = wf_batch.discover_targets(tmp_path)

        assert targets == []
        assert len(excluded) == 1
        assert "02-Individual-music" in excluded[0].reason

    def test_missing_url_and_audio_reports_both_reasons(self, tmp_path):
        _make_collection(tmp_path, "001-a-collection", _state(url=None), audio_files=())

        _, excluded = wf_batch.discover_targets(tmp_path)

        assert "suno_playlist_url" in excluded[0].reason
        assert "02-Individual-music" in excluded[0].reason

    def test_non_prepared_phase_is_silently_skipped(self, tmp_path):
        _make_collection(tmp_path, "001-a-collection", _state(phase="mastered"))

        targets, excluded = wf_batch.discover_targets(tmp_path)

        assert targets == []
        assert excluded == []

    def test_raw_master_recorded_is_silently_skipped(self, tmp_path):
        _make_collection(tmp_path, "001-a-collection", _state(raw_master="master.mp3"))

        targets, excluded = wf_batch.discover_targets(tmp_path)

        assert targets == []
        assert excluded == []

    def test_music_prompts_false_is_silently_skipped(self, tmp_path):
        _make_collection(tmp_path, "001-a-collection", _state(music_prompts=False))

        targets, excluded = wf_batch.discover_targets(tmp_path)

        assert targets == []
        assert excluded == []

    def test_broken_state_is_excluded_with_warning(self, tmp_path):
        _make_collection(tmp_path, "001-a-collection", "{broken json")

        targets, excluded = wf_batch.discover_targets(tmp_path)

        assert targets == []
        assert "workflow-state.json" in excluded[0].reason

    def test_targets_are_sorted_by_slug(self, tmp_path):
        _make_collection(tmp_path, "002-b-collection", _state())
        _make_collection(tmp_path, "001-a-collection", _state())

        targets, _ = wf_batch.discover_targets(tmp_path)

        assert [t.slug for t in targets] == ["001-a-collection", "002-b-collection"]

    def test_missing_planning_root_returns_empty(self, tmp_path):
        targets, excluded = wf_batch.discover_targets(tmp_path / "nope")

        assert targets == []
        assert excluded == []


def _targets(*slugs: str) -> list[wf_batch.WfBatchTarget]:
    return [wf_batch.WfBatchTarget(slug=s, path=Path("/tmp") / s) for s in slugs]


class TestSelectTargets:
    def test_only_filters_by_slug(self):
        selected = wf_batch.select_targets(_targets("a", "b", "c"), only=["a", "c"])

        assert [t.slug for t in selected] == ["a", "c"]

    def test_only_unknown_slug_raises(self):
        with pytest.raises(ValidationError, match="--only"):
            wf_batch.select_targets(_targets("a"), only=["a", "zzz"])

    def test_from_resumes_at_slug(self):
        selected = wf_batch.select_targets(_targets("a", "b", "c"), from_slug="b")

        assert [t.slug for t in selected] == ["b", "c"]

    def test_from_unknown_slug_raises(self):
        with pytest.raises(ValidationError, match="--from"):
            wf_batch.select_targets(_targets("a"), from_slug="zzz")

    def test_limit_truncates(self):
        selected = wf_batch.select_targets(_targets("a", "b", "c"), limit=2)

        assert [t.slug for t in selected] == ["a", "b"]

    def test_limit_below_one_raises(self):
        with pytest.raises(ValidationError, match="--limit"):
            wf_batch.select_targets(_targets("a"), limit=0)

    def test_filters_compose_in_order(self):
        selected = wf_batch.select_targets(
            _targets("a", "b", "c", "d"),
            only=["b", "c", "d"],
            from_slug="c",
            limit=1,
        )

        assert [t.slug for t in selected] == ["c"]


@pytest.fixture
def channel(tmp_path, monkeypatch):
    """CHANNEL 相当の一時ディレクトリ（skill reference の stub 込み）を組み立てる。"""
    root = tmp_path / "channel"
    (root / "collections" / "planning").mkdir(parents=True)
    for rel in (
        "wf-next/references/master_audio_transition.py",
        "videoup/references/generate_videos.sh",
    ):
        script = root / ".claude" / "skills" / rel
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("# test stub\n", encoding="utf-8")

    monkeypatch.setattr(wf_batch, "channel_dir", lambda: root)
    monkeypatch.setattr(
        wf_batch,
        "_wf_next_settings",
        lambda: wf_batch.WfNextSettings(
            skip_manual_mastering=True,
            approval_gate_audio=False,
            approval_gate_upload=False,
        ),
    )
    return root


def _make_runner(channel_root: Path, failures: dict | None = None, transition_action: str = "adopted"):
    """_run_command の代替。step ごとの成果物生成・live 移行を最小限シミュレートする。"""
    failures = failures or {}
    calls: list[tuple[str, str]] = []

    def runner(cmd: list[str], log_path: Path, cwd: Path) -> tuple[int, str]:
        head = Path(cmd[0]).name
        if head == "yt-upload-collection":
            step = "yt-upload-collection"
            slug = cmd[cmd.index("-c") + 1]
            coll = channel_root / "collections" / "planning" / slug
        elif head == "bash":
            step = "generate-videos"
            coll = Path(cmd[-1])
            slug = coll.name
        elif cmd[0] == sys.executable:
            step = "master-audio-transition"
            coll = Path(cmd[2])
            slug = coll.name
        else:
            step = head
            coll = Path(cmd[1])
            slug = coll.name

        calls.append((slug, step))
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"$ {' '.join(cmd)}\n")

        code = failures.get((slug, step), 0)
        if code != 0:
            return code, "simulated failure\n"

        if step == "master-audio-transition":
            return 0, json.dumps({"action": transition_action}) + "\n"
        if step == "generate-videos":
            (coll / "01-master" / "master.mp4").write_bytes(b"video")
        if step == "yt-upload-collection":
            live = channel_root / "collections" / "live" / slug
            live.parent.mkdir(parents=True, exist_ok=True)
            coll.rename(live)
            state_path = live / "workflow-state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["upload"] = {
                "video_id": f"vid-{slug}",
                "video_url": f"https://youtu.be/vid-{slug}",
            }
            state["phase"] = "complete"
            state["stage"] = "live"
            state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 0, "ok\n"

    return runner, calls


def _summary(channel_root: Path) -> tuple[dict, Path]:
    report_dirs = sorted((channel_root / "reports").glob("wf-batch-*"))
    assert len(report_dirs) == 1
    summary_path = report_dirs[0] / "summary.json"
    return json.loads(summary_path.read_text(encoding="utf-8")), report_dirs[0]


class TestMainDryRun:
    def test_dry_run_lists_targets_and_warnings_without_processing(self, channel, monkeypatch, capsys):
        planning = channel / "collections" / "planning"
        _make_collection(planning, "001-a-collection", _state())
        _make_collection(planning, "002-b-collection", _state(url=None))

        def _explode(*args, **kwargs):
            raise AssertionError("dry-run で実処理が呼ばれました")

        monkeypatch.setattr(wf_batch, "_run_command", _explode)

        rc = wf_batch.main(["--dry-run"])

        assert rc == 0
        captured = capsys.readouterr()
        assert "001-a-collection" in captured.out
        assert "[dry-run]" in captured.out
        assert "002-b-collection" in captured.err
        assert "suno_playlist_url" in captured.err
        assert not (channel / "reports").exists()


class TestMainBatchRun:
    def test_all_success_writes_summary_and_logs(self, channel, monkeypatch):
        planning = channel / "collections" / "planning"
        _make_collection(planning, "001-a-collection", _state())
        _make_collection(planning, "002-b-collection", _state())
        runner, _calls = _make_runner(channel)
        monkeypatch.setattr(wf_batch, "_run_command", runner)

        rc = wf_batch.main([])

        assert rc == 0
        summary, report_dir = _summary(channel)
        assert summary["total"] == 2
        assert summary["success"] == 2
        assert summary["failed"] == 0
        assert isinstance(summary["elapsed_sec"], (int, float))
        for slug in ("001-a-collection", "002-b-collection"):
            entry = next(r for r in summary["results"] if r["slug"] == slug)
            assert entry["status"] == "success"
            assert entry["video_id"] == f"vid-{slug}"
            assert entry["video_url"] == f"https://youtu.be/vid-{slug}"
            assert entry["live_path"] == str(channel / "collections" / "live" / slug)
            assert (report_dir / f"{slug}.log").is_file()

    def test_one_failure_continues_to_next_collection(self, channel, monkeypatch):
        planning = channel / "collections" / "planning"
        _make_collection(planning, "001-a-collection", _state())
        _make_collection(planning, "002-b-collection", _state())
        runner, calls = _make_runner(
            channel,
            failures={("001-a-collection", "yt-generate-master"): 1},
        )
        monkeypatch.setattr(wf_batch, "_run_command", runner)

        rc = wf_batch.main([])

        assert rc == 2
        summary, _ = _summary(channel)
        assert summary["total"] == 2
        assert summary["success"] == 1
        assert summary["failed"] == 1
        failed = next(r for r in summary["results"] if r["slug"] == "001-a-collection")
        assert failed["status"] == "failed"
        assert "generate-master" in failed["error"]
        # 失敗した collection の後続 step は打ち切られ、次の collection は処理されている
        assert ("001-a-collection", "yt-raw-master-check") not in calls
        assert ("002-b-collection", "yt-upload-collection") in calls

    def test_transition_not_adopted_fails_collection(self, channel, monkeypatch):
        planning = channel / "collections" / "planning"
        _make_collection(planning, "001-a-collection", _state())
        runner, _ = _make_runner(channel, transition_action="wait_for_master")
        monkeypatch.setattr(wf_batch, "_run_command", runner)

        rc = wf_batch.main([])

        assert rc == 2
        summary, _ = _summary(channel)
        failed = summary["results"][0]
        assert failed["status"] == "failed"
        assert "wait_for_master" in failed["error"]

    def test_only_and_limit_filter_processed_collections(self, channel, monkeypatch):
        planning = channel / "collections" / "planning"
        for slug in ("001-a-collection", "002-b-collection", "003-c-collection"):
            _make_collection(planning, slug, _state())
        runner, calls = _make_runner(channel)
        monkeypatch.setattr(wf_batch, "_run_command", runner)

        rc = wf_batch.main(["--only", "002-b-collection,003-c-collection", "--limit", "1"])

        assert rc == 0
        processed = {slug for slug, _ in calls}
        assert processed == {"002-b-collection"}

    def test_from_resumes_processing(self, channel, monkeypatch):
        planning = channel / "collections" / "planning"
        for slug in ("001-a-collection", "002-b-collection"):
            _make_collection(planning, slug, _state())
        runner, calls = _make_runner(channel)
        monkeypatch.setattr(wf_batch, "_run_command", runner)

        rc = wf_batch.main(["--from", "002-b-collection"])

        assert rc == 0
        processed = {slug for slug, _ in calls}
        assert processed == {"002-b-collection"}

    def test_unknown_only_slug_exits_1(self, channel, capsys):
        rc = wf_batch.main(["--only", "zzz"])

        assert rc == 1
        assert "--only" in capsys.readouterr().err

    def test_approval_gates_enabled_exits_1(self, channel, monkeypatch, capsys):
        planning = channel / "collections" / "planning"
        _make_collection(planning, "001-a-collection", _state())
        monkeypatch.setattr(
            wf_batch,
            "_wf_next_settings",
            lambda: wf_batch.WfNextSettings(
                skip_manual_mastering=False,
                approval_gate_audio=True,
                approval_gate_upload=False,
            ),
        )

        rc = wf_batch.main([])

        assert rc == 1
        assert "approval_gates" in capsys.readouterr().err

    def test_no_targets_exits_0_without_reports(self, channel, capsys):
        rc = wf_batch.main([])

        assert rc == 0
        assert "処理対象の collection がありません" in capsys.readouterr().out
        assert not (channel / "reports").exists()
