"""yt-thumbnail-correlate CLI のフォールバック挙動テスト"""

import json

import pytest

from youtube_automation.commands.thumbnail import thumbnail_correlate as mod


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


def test_engagement_metric_uses_rate_and_rejects_zero_views():
    assert (
        mod._resolve_metric(
            {"views": 20, "likes": 2, "comments": 1, "shares": 1},
            {},
            "video",
            "engagement",
        )
        == 20.0
    )
    assert mod._resolve_metric({"views": 0, "likes": 2}, {}, "video", "engagement") is None


def test_unknown_metric_is_rejected_by_cli(monkeypatch, capsys, _patched_env):
    monkeypatch.setattr("sys.argv", ["yt-thumbnail-correlate", "--metric", "unknown"])

    with pytest.raises(SystemExit) as exc_info:
        mod.main()

    assert exc_info.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_missing_metric_skips_thumbnail_fetch(monkeypatch):
    analytics = {"video_analytics": {"v1": {"title": "missing all metrics"}}}
    fetch_calls = []
    monkeypatch.setattr(mod, "_fetch_thumbnail", lambda *args: fetch_calls.append(args))

    videos = mod._collect_video_features(analytics, mod.Path("/tmp/cache"), "views")

    assert videos == []
    assert fetch_calls == []


def test_all_thumbnail_fetch_failures_produce_empty_json_result(monkeypatch, capsys, tmp_path):
    analytics = {
        "video_analytics": {
            "v1": {"title": "one", "views": 10},
            "v2": {"title": "two", "views": 20},
        }
    }
    monkeypatch.setattr(mod, "_channel_dir", lambda: tmp_path)
    monkeypatch.setattr(mod, "_load_analytics", lambda _channel: analytics)
    monkeypatch.setattr(mod, "_fetch_thumbnail", lambda *_args: (_ for _ in ()).throw(RuntimeError("offline")))

    result = _run_main(monkeypatch, capsys, ["--metric", "views"])

    assert result["metric"] == "views"
    assert result["video_count"] == 0
    assert result["videos"] == []
