from __future__ import annotations

import os
from pathlib import Path

from bench import bench_cost_tracker
from youtube_automation import configuration


def test_scoped_channel_dir_resets_configuration_before_and_after(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []
    monkeypatch.setattr(configuration, "reset", lambda: calls.append("reset"))
    monkeypatch.setenv("CHANNEL_DIR", "original-channel")

    with bench_cost_tracker._scoped_channel_dir(tmp_path):
        assert os.environ["CHANNEL_DIR"] == str(tmp_path)

    assert os.environ["CHANNEL_DIR"] == "original-channel"
    assert calls == ["reset", "reset"]
