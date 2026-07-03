"""yt-collection-preflight のユニットテスト（issue #1494）

テスト対象: scripts/collection_preflight.py
標準骨格の検証・補完・exit code 契約を tmp_path フィクスチャで検証する。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from youtube_automation.scripts.collection_preflight import (
    _resolve_targets,
    check_collection,
    main,
)
from youtube_automation.utils.collection_paths import REQUIRED_SUBDIRS


def _make_collection(root: Path, name: str, *, subdirs=REQUIRED_SUBDIRS, with_state=True) -> Path:
    collection = root / name
    collection.mkdir(parents=True)
    for sub in subdirs:
        (collection / sub).mkdir()
    if with_state:
        (collection / "workflow-state.json").write_text("{}\n")
    return collection


# ---------------------------------------------------------------------------
# 対象解決
# ---------------------------------------------------------------------------


class TestResolveTargets:
    def test_scans_planning_root_for_collection_suffix(self, tmp_path):
        a = _make_collection(tmp_path, "20260701-tc-a-collection")
        b = _make_collection(tmp_path, "20260702-tc-b-collection")
        (tmp_path / "not-a-target").mkdir()
        assert _resolve_targets([], tmp_path) == [a, b]

    def test_empty_when_planning_root_missing(self, tmp_path):
        assert _resolve_targets([], tmp_path / "nope") == []

    def test_resolves_explicit_path(self, tmp_path):
        target = _make_collection(tmp_path, "20260702-tc-x-collection")
        assert _resolve_targets([str(target)], tmp_path / "unused") == [target]

    def test_resolves_name_under_planning_root(self, tmp_path):
        target = _make_collection(tmp_path, "20260702-tc-x-collection")
        assert _resolve_targets(["20260702-tc-x-collection"], tmp_path) == [target]

    def test_unresolvable_name_exits_2(self, tmp_path, capsys):
        with pytest.raises(SystemExit) as exc:
            _resolve_targets(["no-such-collection"], tmp_path)
        assert exc.value.code == 2
        assert "見つかりません" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# 単一コレクションの検証・補完
# ---------------------------------------------------------------------------


class TestCheckCollection:
    def test_complete_skeleton_is_ok(self, tmp_path):
        collection = _make_collection(tmp_path, "20260701-tc-ok-collection")
        ok, line = check_collection(collection, fix=False)
        assert ok
        assert line.startswith("[OK]")

    def test_missing_master_dir_is_ng(self, tmp_path):
        """issue #1494 の実事例: 01-master だけが欠落しているケース。"""
        subdirs = [s for s in REQUIRED_SUBDIRS if s != "01-master"]
        collection = _make_collection(tmp_path, "20260702-tc-ng-collection", subdirs=subdirs)
        ok, line = check_collection(collection, fix=False)
        assert not ok
        assert "01-master" in line

    def test_missing_state_is_ng(self, tmp_path):
        collection = _make_collection(tmp_path, "20260702-tc-ns-collection", with_state=False)
        ok, line = check_collection(collection, fix=False)
        assert not ok
        assert "workflow-state.json" in line

    def test_fix_creates_missing_dirs(self, tmp_path):
        subdirs = [s for s in REQUIRED_SUBDIRS if s != "01-master"]
        collection = _make_collection(tmp_path, "20260702-tc-fix-collection", subdirs=subdirs)
        ok, line = check_collection(collection, fix=True)
        assert ok
        assert line.startswith("[FIXED]")
        assert (collection / "01-master").is_dir()

    def test_fix_preserves_existing_files(self, tmp_path):
        """既存音源ファイルに触れない（非破壊）こと。"""
        subdirs = [s for s in REQUIRED_SUBDIRS if s != "01-master"]
        collection = _make_collection(tmp_path, "20260702-tc-keep-collection", subdirs=subdirs)
        track = collection / "02-Individual-music" / "track-01.mp3"
        track.write_bytes(b"audio")
        check_collection(collection, fix=True)
        assert track.read_bytes() == b"audio"

    def test_fix_does_not_create_state(self, tmp_path):
        """--fix は workflow-state.json を捏造しない（/wf-new の責務）。"""
        collection = _make_collection(tmp_path, "20260702-tc-nst-collection", with_state=False)
        ok, line = check_collection(collection, fix=True)
        assert not ok
        assert not (collection / "workflow-state.json").exists()


# ---------------------------------------------------------------------------
# main の exit code 契約
# ---------------------------------------------------------------------------


class TestMainExitCodes:
    def _run(self, monkeypatch, argv: list[str]):
        monkeypatch.setattr(sys, "argv", ["yt-collection-preflight", *argv])
        return main()

    def test_all_ok_exits_zero(self, tmp_path, monkeypatch, capsys):
        _make_collection(tmp_path, "20260701-tc-a-collection")
        self._run(monkeypatch, ["--planning-root", str(tmp_path)])
        assert "[OK]" in capsys.readouterr().out

    def test_missing_dir_exits_one_with_fix_hint(self, tmp_path, monkeypatch, capsys):
        subdirs = [s for s in REQUIRED_SUBDIRS if s != "01-master"]
        _make_collection(tmp_path, "20260702-tc-ng-collection", subdirs=subdirs)
        with pytest.raises(SystemExit) as exc:
            self._run(monkeypatch, ["--planning-root", str(tmp_path)])
        assert exc.value.code == 1
        assert "--fix" in capsys.readouterr().err

    def test_fix_repairs_and_exits_zero(self, tmp_path, monkeypatch, capsys):
        subdirs = [s for s in REQUIRED_SUBDIRS if s != "01-master"]
        collection = _make_collection(tmp_path, "20260702-tc-fix-collection", subdirs=subdirs)
        self._run(monkeypatch, ["--planning-root", str(tmp_path), "--fix"])
        assert "[FIXED]" in capsys.readouterr().out
        assert (collection / "01-master").is_dir()

    def test_no_targets_exits_zero(self, tmp_path, monkeypatch, capsys):
        self._run(monkeypatch, ["--planning-root", str(tmp_path)])
        assert "検証対象" in capsys.readouterr().out
