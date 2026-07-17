"""yt-thumbnail-correlate CLI のフォールバック挙動テスト"""

import json

import pytest

from youtube_automation.scripts import thumbnail_correlate as mod


@pytest.fixture
def _patched_env(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "_channel_dir", lambda: tmp_path)
    monkeypatch.setattr(mod, "_load_analytics", lambda channel_dir: {})


def _run_main(monkeypatch, capsys, argv: list[str]) -> dict:
    monkeypatch.setattr("sys.argv", ["yt-thumbnail-correlate", *argv])
    assert mod.main() == 0
    return json.loads(capsys.readouterr().out)


def test_ctr_missing_falls_back_to_views(monkeypatch, capsys, _patched_env):
    def fake_collect(analytics, cache_dir, metric):
        if metric == "ctr":
            return []
        return [{"video_id": "v1", "title": "", "ctr": 100.0, "features": {"brightness": 10.0}}]

    monkeypatch.setattr(mod, "_collect_video_features", fake_collect)
    result = _run_main(monkeypatch, capsys, [])
    assert result["metric"] == "views"
    assert result["metric_fallback"]["from"] == "ctr"
    assert result["metric_fallback"]["to"] == "views"
    assert result["metric_fallback"]["reason"]
    assert result["video_count"] == 1


def test_explicit_metric_ctr_does_not_fall_back(monkeypatch, capsys, _patched_env):
    monkeypatch.setattr(mod, "_collect_video_features", lambda *a: [])
    result = _run_main(monkeypatch, capsys, ["--metric", "ctr"])
    assert result["metric"] == "ctr"
    assert result["metric_fallback"] is None
    assert result["video_count"] == 0


def test_ctr_present_does_not_fall_back(monkeypatch, capsys, _patched_env):
    videos = [{"video_id": "v1", "title": "", "ctr": 4.2, "features": {"brightness": 10.0}}]
    monkeypatch.setattr(mod, "_collect_video_features", lambda *a: list(videos))
    result = _run_main(monkeypatch, capsys, [])
    assert result["metric"] == "ctr"
    assert result["metric_fallback"] is None
