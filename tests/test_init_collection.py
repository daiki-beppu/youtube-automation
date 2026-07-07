"""yt-init-collection の scaffold 回帰テスト（issue #1494）

テスト対象: scripts/init_collection.py
標準骨格 4 ディレクトリ + workflow-state.json が必ず作られることを検証する。
conftest.py が CHANNEL_DIR を tmp コピーへ向けるため fixture を汚染しない。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from youtube_automation.scripts.init_collection import main
from youtube_automation.utils.collection_paths import REQUIRED_SUBDIRS
from youtube_automation.utils.config import channel_dir


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
            assert "bunx tayk collection-preflight" in err
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
            assert "bunx tayk collection-preflight" in err
            assert "quote scaffold-collection'" in err
        finally:
            import shutil

            shutil.rmtree(collection)
