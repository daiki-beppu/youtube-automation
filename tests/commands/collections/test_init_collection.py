"""yt-init-collection の scaffold 回帰テスト（issue #1494）

テスト対象: scripts/init_collection.py
標準骨格 4 ディレクトリ + workflow-state.json が必ず作られることを検証する。
conftest.py が CHANNEL_DIR を tmp コピーへ向けるため fixture を汚染しない。
"""

import json
import sys
from pathlib import Path

from tests.helpers.paths import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT))

import pytest

from youtube_automation.commands.collections.init_collection import main
from youtube_automation.configuration import channel_dir, load_config
from youtube_automation.infrastructure.media.collection_paths import REQUIRED_SUBDIRS


def _run(monkeypatch, argv: list[str]):
    monkeypatch.setattr(sys, "argv", ["yt-init-collection", *argv])
    return main()


def _created_collection() -> Path:
    planning = Path(channel_dir()) / "collections" / "planning"
    candidates = sorted(planning.glob("*-init-scaffold-collection"))
    assert candidates, f"コレクションが作成されていません: {planning}"
    return candidates[-1]


class TestScaffold:
    def test_creates_all_required_subdirs_and_state(self, monkeypatch):
        """issue #1494 回帰: 01-master を含む必須骨格が漏れなく作られること。"""
        _run(monkeypatch, ["Init Scaffold", "init-scaffold"])
        collection = _created_collection()
        try:
            for sub in REQUIRED_SUBDIRS:
                assert (collection / sub).is_dir(), f"{sub} が作成されていません"
            state = json.loads((collection / "workflow-state.json").read_text())
            assert state["theme"] == "init-scaffold"
            assert state["phase"] == "planning"
        finally:
            import shutil

            shutil.rmtree(collection)

    def test_existing_dir_fails_loud_with_preflight_hint(self, monkeypatch, capsys):
        """既存ディレクトリで再実行したら exit 1 + preflight --fix への導線を出すこと。"""
        _run(monkeypatch, ["Init Scaffold", "init-scaffold"])
        collection = _created_collection()
        try:
            with pytest.raises(SystemExit) as exc:
                _run(monkeypatch, ["Init Scaffold", "init-scaffold"])
            assert exc.value.code == 1
            err = capsys.readouterr().err
            assert "既に存在します" in err
            assert "uv run yt-collection-preflight" in err
            assert "bunx tayk collection-preflight" not in err
        finally:
            import shutil

            shutil.rmtree(collection)

    def test_existing_dir_preflight_hint_quotes_collection_dir(self, monkeypatch, capsys):
        """復旧コマンドは shell に貼れるよう collection dir を quote する。"""
        _run(monkeypatch, ["Quote Scaffold", "quote scaffold"])
        planning = Path(channel_dir()) / "collections" / "planning"
        collection = sorted(planning.glob("*-quote scaffold-collection"))[-1]
        try:
            with pytest.raises(SystemExit):
                _run(monkeypatch, ["Quote Scaffold", "quote scaffold"])
            err = capsys.readouterr().err
            assert "uv run yt-collection-preflight" in err
            assert "bunx tayk collection-preflight" not in err
            assert "quote scaffold-collection'" in err
        finally:
            import shutil

            shutil.rmtree(collection)

    def test_cli_options_are_persisted_in_workflow_state(self, monkeypatch):
        """REQ-2795-01: CLI option を workflow-state の実値として保存する."""
        _run(
            monkeypatch,
            [
                "Configured Scaffold",
                "init-scaffold",
                "--track-count",
                "7",
                "--selected-plan",
                "D",
                "--music-engine",
                "lyria",
            ],
        )
        collection = _created_collection()
        try:
            state = json.loads((collection / "workflow-state.json").read_text(encoding="utf-8"))
            assert state["collection_name"] == "Configured Scaffold"
            assert state["theme"] == "init-scaffold"
            assert state["track_count"] == 7
            assert state["selected_plan"] == "D"
            assert state["music_engine"] == "lyria"
        finally:
            import shutil

            shutil.rmtree(collection)

    def test_music_engine_falls_back_to_channel_config(self, monkeypatch):
        """REQ-2795-02: 未指定値は channel config/default から補完する."""
        expected_engine = load_config().youtube.music_engine
        _run(monkeypatch, ["Fallback Scaffold", "init-scaffold"])
        collection = _created_collection()
        try:
            state = json.loads((collection / "workflow-state.json").read_text(encoding="utf-8"))
            assert state["music_engine"] == expected_engine
            assert state["track_count"] == 12
            assert state["selected_plan"] == "A"
        finally:
            import shutil

            shutil.rmtree(collection)

    def test_minimax_music_engine_is_persisted_in_workflow_state(self, monkeypatch):
        _run(monkeypatch, ["MiniMax Scaffold", "minimax-scaffold", "--music-engine", "minimax"])
        planning = Path(channel_dir()) / "collections" / "planning"
        collection = next(planning.glob("*-minimax-scaffold-collection"))
        try:
            state = json.loads((collection / "workflow-state.json").read_text(encoding="utf-8"))
            assert state["music_engine"] == "minimax"
        finally:
            import shutil

            shutil.rmtree(collection)
