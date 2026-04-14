import pytest

from youtube_automation.utils.thumbnail_correlation import compute_correlations


def test_compute_correlations_perfect_positive():
    videos = [
        {"video_id": "v1", "ctr": 1.0, "features": {"brightness": 10, "contrast": 5}},
        {"video_id": "v2", "ctr": 2.0, "features": {"brightness": 20, "contrast": 3}},
        {"video_id": "v3", "ctr": 3.0, "features": {"brightness": 30, "contrast": 1}},
    ]
    corr = compute_correlations(videos)
    assert corr["brightness_vs_ctr"]["pearson"] == pytest.approx(1.0, abs=0.01)
    assert corr["brightness_vs_ctr"]["n"] == 3
    assert corr["contrast_vs_ctr"]["pearson"] == pytest.approx(-1.0, abs=0.01)


def test_compute_correlations_ignores_missing_ctr():
    videos = [
        {"video_id": "v1", "ctr": 1.0, "features": {"brightness": 10}},
        {"video_id": "v2", "ctr": None, "features": {"brightness": 20}},
        {"video_id": "v3", "ctr": 3.0, "features": {"brightness": 30}},
    ]
    corr = compute_correlations(videos)
    assert corr["brightness_vs_ctr"]["n"] == 2


def test_compute_correlations_requires_min_samples():
    videos = [{"video_id": "v1", "ctr": 1.0, "features": {"brightness": 10}}]
    corr = compute_correlations(videos, min_samples=3)
    assert corr["brightness_vs_ctr"]["pearson"] is None
    assert corr["brightness_vs_ctr"]["note"] == "サンプル不足"
