"""ctr_resolver の優先順テスト。"""

from __future__ import annotations

from youtube_automation.utils.ctr_resolver import index_reporting_per_video, resolve_ctr_summary


def test_resolve_prefers_reporting_api():
    data = {
        "reporting_api": {
            "impressions_summary": {
                "source": "youtubereporting.v1/channel_basic_a2",
                "aggregated_ctr_percentage": 4.2,
            }
        },
        "ctr_analysis": {"impressions_summary": {"aggregated_ctr_percentage": 9.9}},
        "channel_ctr": {"average_ctr": 0.05},
    }
    result = resolve_ctr_summary(data)
    assert result is not None
    assert result["aggregated_ctr_percentage"] == 4.2
    assert result["source"].startswith("youtubereporting")


def test_resolve_falls_back_to_legacy_ctr_analysis():
    data = {
        "ctr_analysis": {"impressions_summary": {"aggregated_ctr_percentage": 3.1}},
        "channel_ctr": {"average_ctr": 0.05},
    }
    result = resolve_ctr_summary(data)
    assert result is not None
    assert result["aggregated_ctr_percentage"] == 3.1


def test_resolve_falls_back_to_channel_ctr():
    data = {"channel_ctr": {"average_ctr": 0.025}}
    result = resolve_ctr_summary(data)
    assert result is not None
    assert result["aggregated_ctr_percentage"] == 2.5
    assert result["source"] == "fallback:channel_ctr"


def test_resolve_returns_none_when_no_source():
    assert resolve_ctr_summary({}) is None
    assert resolve_ctr_summary({"channel_ctr": {"average_ctr": 0}}) is None


def test_resolve_skips_reporting_when_ctr_is_none():
    """reporting_api キーはあるが aggregated_ctr_percentage が None なら次にフォールバック。"""
    data = {
        "reporting_api": {"impressions_summary": {"aggregated_ctr_percentage": None}},
        "channel_ctr": {"average_ctr": 0.04},
    }
    result = resolve_ctr_summary(data)
    assert result is not None
    assert result["source"] == "fallback:channel_ctr"
    assert result["aggregated_ctr_percentage"] == 4.0


def test_index_reporting_per_video_from_analytics_data():
    data = {
        "reporting_api": {
            "impressions_summary": {
                "per_video": [
                    {"video_id": "v1", "ctr_percentage": 5.0},
                    {"video_id": "v2", "ctr_percentage": 3.0},
                ]
            }
        }
    }
    idx = index_reporting_per_video(data)
    assert idx == {"v1": {"video_id": "v1", "ctr_percentage": 5.0}, "v2": {"video_id": "v2", "ctr_percentage": 3.0}}


def test_index_reporting_per_video_from_summary_directly():
    summary = {"per_video": [{"video_id": "v1", "ctr_percentage": 5.0}]}
    idx = index_reporting_per_video(summary)
    assert "v1" in idx


def test_index_reporting_per_video_handles_invalid_inputs():
    assert index_reporting_per_video(None) == {}
    assert index_reporting_per_video({}) == {}
    assert index_reporting_per_video({"reporting_api": "broken"}) == {}
    assert index_reporting_per_video({"per_video": [{"no_video_id": "x"}, {}]}) == {}
