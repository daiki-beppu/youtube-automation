"""yt-raw-master-check（assets.raw_master と 01-master/ 実ファイルの整合チェック）のテスト。

issue #1668:
- yt-generate-master 直接実行は workflow-state.json を更新しない（現状仕様の回帰固定）
- 実ファイルと assets.raw_master の不整合を検知・警告し、承認時のみ更新する
"""

import json
from pathlib import Path

import pytest

from youtube_automation.scripts import check_raw_master, generate_master
from youtube_automation.utils.exceptions import ValidationError


def _make_collection(
    tmp_path: Path,
    *,
    raw_master: str | None = None,
    master_files: list[str] | None = None,
) -> Path:
    coll = tmp_path / "001-test-collection"
    (coll / "01-master").mkdir(parents=True)
    (coll / "02-Individual-music").mkdir(parents=True)
    for name in master_files or []:
        (coll / "01-master" / name).write_bytes(b"audio")
    state = {
        "collection_name": "test-collection",
        "updated_at": "2026-01-01T00:00:00.000Z",
        "phase": "prepared",
        "assets": {
            "raw_master": raw_master,
            "master_audio": None,
        },
    }
    (coll / "workflow-state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return coll


def _read_state(coll: Path) -> dict:
    return json.loads((coll / "workflow-state.json").read_text(encoding="utf-8"))


class TestGenerateMasterDoesNotTouchState:
    """要件 1: yt-generate-master 直接実行は raw_master を更新しない（回帰固定）。"""

    def test_single_mp3_copy_path_leaves_raw_master_null(self, tmp_path, monkeypatch):
        coll = _make_collection(tmp_path)
        (coll / "02-Individual-music" / "01-track.mp3").write_bytes(b"mp3data")
        monkeypatch.setattr(generate_master.shutil, "which", lambda _: "/usr/bin/ffmpeg")

        output = generate_master.generate_master(coll, 1.0, "192k", no_loop=True, quiet=True)

        assert output == coll / "01-master" / "master.mp3"
        assert output.is_file()
        # workflow-state.json は一切更新されない（不整合が発生する = 検知 CLI の存在意義）
        state = _read_state(coll)
        assert state["assets"]["raw_master"] is None
        assert state["updated_at"] == "2026-01-01T00:00:00.000Z"


class TestCheckRawMaster:
    def test_consistent_when_recorded_file_exists(self, tmp_path):
        coll = _make_collection(tmp_path, raw_master="master.mp3", master_files=["master.mp3"])
        result = check_raw_master.check_raw_master(coll)
        assert result.is_consistent
        assert result.recorded == "master.mp3"

    def test_consistent_when_nothing_generated(self, tmp_path):
        coll = _make_collection(tmp_path)
        result = check_raw_master.check_raw_master(coll)
        assert result.is_consistent
        assert result.recorded is None
        assert result.candidate is None

    def test_mismatch_when_null_but_file_exists(self, tmp_path):
        """要件 2: 実ファイルがあるのに raw_master = null → 不整合検知。"""
        coll = _make_collection(tmp_path, master_files=["master.mp3"])
        result = check_raw_master.check_raw_master(coll)
        assert not result.is_consistent
        assert result.candidate == "master.mp3"
        assert "更新しますか" in result.message

    def test_mismatch_when_recorded_file_missing(self, tmp_path):
        """要件 2: raw_master が実ファイル名と不一致（記録先が消失）→ 候補を提案。"""
        coll = _make_collection(tmp_path, raw_master="old-master.mp3", master_files=["master.mp3"])
        result = check_raw_master.check_raw_master(coll)
        assert not result.is_consistent
        assert result.recorded == "old-master.mp3"
        assert result.candidate == "master.mp3"

    def test_mismatch_without_candidate(self, tmp_path):
        coll = _make_collection(tmp_path, raw_master="master.mp3")
        result = check_raw_master.check_raw_master(coll)
        assert not result.is_consistent
        assert result.candidate is None

    def test_rain_output_recorded_is_consistent_even_with_extra_mp3(self, tmp_path):
        """raw_master が雨レイヤー出力（wav）でも実在すれば整合（誤警告しない）。"""
        coll = _make_collection(tmp_path, raw_master="master-rain.wav", master_files=["master-rain.wav", "master.mp3"])
        result = check_raw_master.check_raw_master(coll)
        assert result.is_consistent

    def test_missing_workflow_state_raises(self, tmp_path):
        coll = tmp_path / "001-no-state"
        (coll / "01-master").mkdir(parents=True)
        with pytest.raises(ValidationError):
            check_raw_master.check_raw_master(coll)

    def test_broken_json_raises_and_is_not_modified(self, tmp_path):
        coll = _make_collection(tmp_path, master_files=["master.mp3"])
        (coll / "workflow-state.json").write_text("{broken", encoding="utf-8")
        with pytest.raises(ValidationError):
            check_raw_master.check_raw_master(coll)
        assert (coll / "workflow-state.json").read_text(encoding="utf-8") == "{broken"

    def test_path_traversal_in_recorded_value_raises(self, tmp_path):
        coll = _make_collection(tmp_path, raw_master="../evil.mp3", master_files=["master.mp3"])
        with pytest.raises(ValidationError):
            check_raw_master.check_raw_master(coll)


class TestApplyRawMaster:
    def test_apply_updates_raw_master_and_updated_at(self, tmp_path):
        """要件 3: 承認後の更新で raw_master と updated_at が書き込まれる。"""
        coll = _make_collection(tmp_path, master_files=["master.mp3"])
        check_raw_master.apply_raw_master(coll, "master.mp3")

        state = _read_state(coll)
        assert state["assets"]["raw_master"] == "master.mp3"
        assert state["updated_at"] != "2026-01-01T00:00:00.000Z"
        # 他のフィールドは保持される
        assert state["phase"] == "prepared"
        assert state["assets"]["master_audio"] is None
        # 更新後は整合と判定される
        assert check_raw_master.check_raw_master(coll).is_consistent

    def test_apply_rejects_missing_candidate_file(self, tmp_path):
        coll = _make_collection(tmp_path, master_files=["master.mp3"])
        with pytest.raises(ValidationError):
            check_raw_master.apply_raw_master(coll, "no-such.mp3")
        # 非破壊: state は変更されない
        assert _read_state(coll)["assets"]["raw_master"] is None

    def test_apply_does_not_leave_tmp_files(self, tmp_path):
        coll = _make_collection(tmp_path, master_files=["master.mp3"])
        check_raw_master.apply_raw_master(coll, "master.mp3")
        leftovers = [p for p in coll.iterdir() if p.name.startswith(".workflow-state.")]
        assert leftovers == []


class TestMainCli:
    def _run(self, monkeypatch, argv: list[str]) -> int:
        monkeypatch.setattr("sys.argv", ["yt-raw-master-check", *argv])
        return check_raw_master.main()

    def test_consistent_exits_0(self, tmp_path, monkeypatch, capsys):
        coll = _make_collection(tmp_path, raw_master="master.mp3", master_files=["master.mp3"])
        assert self._run(monkeypatch, [str(coll)]) == 0
        assert "OK" in capsys.readouterr().out

    def test_mismatch_dry_run_exits_2_and_warns(self, tmp_path, monkeypatch, capsys):
        """要件 2: 既定は検知のみ（書き込まない）で警告を表示する。"""
        coll = _make_collection(tmp_path, master_files=["master.mp3"])
        assert self._run(monkeypatch, [str(coll)]) == 2
        captured = capsys.readouterr()
        assert "WARNING" in captured.err
        assert _read_state(coll)["assets"]["raw_master"] is None

    def test_mismatch_repeats_warning_until_applied(self, tmp_path, monkeypatch):
        """要件 4: 承認しない限り state は変わらず、次回も同じ警告（exit 2）。"""
        coll = _make_collection(tmp_path, master_files=["master.mp3"])
        assert self._run(monkeypatch, [str(coll)]) == 2
        assert self._run(monkeypatch, [str(coll)]) == 2
        assert _read_state(coll)["assets"]["raw_master"] is None

    def test_apply_exits_0_and_updates(self, tmp_path, monkeypatch, capsys):
        """要件 3: --apply（承認済み経路）で更新され exit 0。"""
        coll = _make_collection(tmp_path, master_files=["master.mp3"])
        assert self._run(monkeypatch, [str(coll), "--apply"]) == 0
        assert "Updated" in capsys.readouterr().out
        assert _read_state(coll)["assets"]["raw_master"] == "master.mp3"

    def test_apply_without_candidate_exits_2_non_destructive(self, tmp_path, monkeypatch, capsys):
        coll = _make_collection(tmp_path, raw_master="gone.mp3")
        before = (coll / "workflow-state.json").read_text(encoding="utf-8")
        assert self._run(monkeypatch, [str(coll), "--apply"]) == 2
        assert "ERROR" in capsys.readouterr().err
        assert (coll / "workflow-state.json").read_text(encoding="utf-8") == before

    def test_broken_state_exits_1(self, tmp_path, monkeypatch, capsys):
        coll = _make_collection(tmp_path, master_files=["master.mp3"])
        (coll / "workflow-state.json").write_text("{broken", encoding="utf-8")
        assert self._run(monkeypatch, [str(coll)]) == 1
        assert "ERROR" in capsys.readouterr().err
