"""generate_music_dj のセグメント分割生成テスト。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from generate_music_dj import build_segment_compositions


def make_composition(phases_count=6, total_min=60):
    """テスト用 composition を生成。"""
    interval = total_min / phases_count
    phases = [
        {"at_min": round(i * interval, 1), "name": f"phase_{i+1}", "prompt": f"prompt {i+1}"}
        for i in range(phases_count)
    ]
    return {
        "title": "Test",
        "total_duration_min": total_min,
        "base": {"prompt_prefix": "celtic folk", "bpm": 90},
        "phases": phases,
        "transition_sec": 30,
    }


class TestBuildSegmentCompositions:
    def test_returns_correct_number_of_segments(self):
        comp = make_composition(phases_count=6, total_min=60)
        segments = build_segment_compositions(comp)
        assert len(segments) == 6

    def test_segment_durations_sum_to_total(self):
        comp = make_composition(phases_count=6, total_min=60)
        segments = build_segment_compositions(comp)
        total = sum(s["total_duration_min"] for s in segments)
        assert abs(total - 60) < 0.01

    def test_each_segment_has_single_phase_at_zero(self):
        comp = make_composition(phases_count=6, total_min=60)
        segments = build_segment_compositions(comp)
        for seg in segments:
            assert len(seg["phases"]) == 1
            assert seg["phases"][0]["at_min"] == 0

    def test_segments_preserve_base(self):
        comp = make_composition()
        segments = build_segment_compositions(comp)
        for seg in segments:
            assert seg["base"] == comp["base"]

    def test_segments_preserve_title_with_index(self):
        comp = make_composition(phases_count=3, total_min=30)
        segments = build_segment_compositions(comp)
        for i, seg in enumerate(segments):
            assert f"[{i+1}/{3}]" in seg["title"]

    def test_uneven_phases(self):
        """at_min が不均等な場合も正しく分割される。"""
        comp = {
            "title": "Uneven",
            "total_duration_min": 60,
            "base": {"prompt_prefix": "test"},
            "phases": [
                {"at_min": 0, "name": "intro", "prompt": "a"},
                {"at_min": 5, "name": "main", "prompt": "b"},
                {"at_min": 50, "name": "outro", "prompt": "c"},
            ],
            "transition_sec": 30,
        }
        segments = build_segment_compositions(comp)
        assert len(segments) == 3
        assert segments[0]["total_duration_min"] == 5
        assert segments[1]["total_duration_min"] == 45
        assert segments[2]["total_duration_min"] == 10
