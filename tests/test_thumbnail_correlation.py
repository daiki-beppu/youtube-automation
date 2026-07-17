import pytest

from youtube_automation.utils.thumbnail_correlation import (
    INSUFFICIENT_SAMPLES_NOTE,
    MIN_SAMPLES_DEFAULT,
    _benjamini_hochberg,
    _pearson_p_value,
    compute_correlations,
)


def _videos_linear(n: int, noise: list[float] | None = None) -> list[dict]:
    """brightness と ctr が線形（noise で崩せる）なダミーデータを作る。"""
    noise = noise or [0.0] * n
    return [
        {
            "video_id": f"v{i}",
            "ctr": float(i) + noise[i],
            "features": {"brightness": float(i * 10)},
        }
        for i in range(n)
    ]


def test_compute_correlations_perfect_positive():
    videos = [
        {"video_id": "v1", "ctr": 1.0, "features": {"brightness": 10, "contrast": 5}},
        {"video_id": "v2", "ctr": 2.0, "features": {"brightness": 20, "contrast": 3}},
        {"video_id": "v3", "ctr": 3.0, "features": {"brightness": 30, "contrast": 1}},
    ]
    corr = compute_correlations(videos, min_samples=3)
    assert corr["brightness_vs_ctr"]["pearson"] == pytest.approx(1.0, abs=0.01)
    assert corr["brightness_vs_ctr"]["n"] == 3
    assert corr["contrast_vs_ctr"]["pearson"] == pytest.approx(-1.0, abs=0.01)


def test_compute_correlations_ignores_missing_ctr():
    videos = [
        {"video_id": "v1", "ctr": 1.0, "features": {"brightness": 10}},
        {"video_id": "v2", "ctr": None, "features": {"brightness": 20}},
        {"video_id": "v3", "ctr": 3.0, "features": {"brightness": 30}},
    ]
    corr = compute_correlations(videos, min_samples=2)
    assert corr["brightness_vs_ctr"]["n"] == 2


def test_default_min_samples_is_ten():
    assert MIN_SAMPLES_DEFAULT == 10
    corr = compute_correlations(_videos_linear(9))
    assert corr["brightness_vs_ctr"]["pearson"] is None
    assert corr["brightness_vs_ctr"]["note"] == INSUFFICIENT_SAMPLES_NOTE
    assert "interpretation" not in corr["brightness_vs_ctr"]


def test_requires_min_samples_note():
    videos = [{"video_id": "v1", "ctr": 1.0, "features": {"brightness": 10}}]
    corr = compute_correlations(videos, min_samples=3)
    assert corr["brightness_vs_ctr"]["pearson"] is None
    assert corr["brightness_vs_ctr"]["note"] == INSUFFICIENT_SAMPLES_NOTE


def test_significant_correlation_has_p_values_and_interpretation():
    corr = compute_correlations(_videos_linear(10))
    c = corr["brightness_vs_ctr"]
    assert c["pearson"] == pytest.approx(1.0, abs=0.01)
    assert c["p_value"] < 0.001
    assert c["p_value_adjusted"] < 0.05
    assert c["significant"] is True
    assert "相関" in c["interpretation"]


def test_insignificant_correlation_suppresses_assertive_wording():
    # ジグザグの noise で相関をほぼ消す（n=10 でも p >= 0.05 になる）
    noise = [5.0, -5.0, 7.0, -7.0, 6.0, -6.0, 8.0, -8.0, 5.5, -5.5]
    corr = compute_correlations(_videos_linear(10, noise))
    c = corr["brightness_vs_ctr"]
    assert c["significant"] is False
    assert c["p_value_adjusted"] >= 0.05
    assert "有意でない" in c["interpretation"]
    assert "強い" not in c["interpretation"]


def test_pearson_p_value_matches_scipy_reference():
    # scipy.stats.pearsonr で r=0.5, n=12 のとき p≈0.09765（両側）
    assert _pearson_p_value(0.5, 12) == pytest.approx(0.09765, abs=0.001)
    assert _pearson_p_value(1.0, 10) == 0.0
    assert _pearson_p_value(0.0, 10) == pytest.approx(1.0, abs=0.001)


def test_benjamini_hochberg_adjustment():
    adjusted = _benjamini_hochberg({"a": 0.01, "b": 0.04, "c": 0.05})
    assert adjusted["a"] == pytest.approx(0.03)
    assert adjusted["b"] == pytest.approx(0.05)
    assert adjusted["c"] == pytest.approx(0.05)
    assert _benjamini_hochberg({}) == {}
