"""generate_music_dj のセグメント分割生成テスト。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from generate_music_dj import (
    CHANNELS,
    SAMPLE_RATE,
    SAMPLE_WIDTH,
    build_segment_compositions,
    generate_segmented,
    write_wav,
)


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


def make_pcm(duration_sec: float) -> bytes:
    """指定秒数のサイレント PCM データを生成。"""
    num_bytes = int(duration_sec * SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH)
    return b'\x00' * num_bytes


class TestGenerateSegmented:
    def test_generates_all_segments_and_joins(self, tmp_path):
        """全セグメント成功時、結合された master.wav が出力される。"""
        comp = make_composition(phases_count=3, total_min=30)
        output = tmp_path / "master.wav"
        seg_pcm = make_pcm(5)  # 各セグメント5秒

        mock_client = MagicMock()
        mock_types = MagicMock()

        with patch("generate_music_dj.generate_dj", new_callable=AsyncMock, return_value=seg_pcm):
            result = asyncio.run(generate_segmented(mock_client, mock_types, comp, output, max_retries=0))

        assert result is not None
        assert output.exists()

    def test_skips_existing_segments(self, tmp_path):
        """既存の seg_NNN.wav がある場合はスキップする。"""
        comp = make_composition(phases_count=3, total_min=30)
        output = tmp_path / "master.wav"
        seg_pcm = make_pcm(5)

        # seg_001.wav を事前に作成
        write_wav(seg_pcm, tmp_path / "seg_001.wav")

        mock_client = MagicMock()
        mock_types = MagicMock()
        call_count = 0

        async def mock_generate_dj(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return seg_pcm

        with patch("generate_music_dj.generate_dj", side_effect=mock_generate_dj):
            result = asyncio.run(generate_segmented(mock_client, mock_types, comp, output, max_retries=0))

        assert call_count == 2  # seg_001 スキップ、seg_002 と seg_003 を生成
        assert result is not None

    def test_retries_on_failure(self, tmp_path):
        """失敗時にリトライする。"""
        comp = make_composition(phases_count=2, total_min=20)
        output = tmp_path / "master.wav"
        seg_pcm = make_pcm(5)

        mock_client = MagicMock()
        mock_types = MagicMock()
        attempts = []

        async def mock_generate_dj(*args, **kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                return None  # 1回目失敗
            return seg_pcm

        with patch("generate_music_dj.generate_dj", side_effect=mock_generate_dj):
            result = asyncio.run(generate_segmented(mock_client, mock_types, comp, output, max_retries=3))

        assert result is not None
        assert len(attempts) == 3  # seg1 失敗→リトライ成功、seg2 成功

    def test_fails_after_max_retries(self, tmp_path):
        """最大リトライ超過で None を返す。"""
        comp = make_composition(phases_count=2, total_min=20)
        output = tmp_path / "master.wav"

        mock_client = MagicMock()
        mock_types = MagicMock()

        with patch("generate_music_dj.generate_dj", new_callable=AsyncMock, return_value=None):
            result = asyncio.run(generate_segmented(mock_client, mock_types, comp, output, max_retries=2))

        assert result is None

    def test_cleans_up_segment_files(self, tmp_path):
        """成功後にセグメントファイルが削除される。"""
        comp = make_composition(phases_count=2, total_min=20)
        output = tmp_path / "master.wav"
        seg_pcm = make_pcm(5)

        mock_client = MagicMock()
        mock_types = MagicMock()

        with patch("generate_music_dj.generate_dj", new_callable=AsyncMock, return_value=seg_pcm):
            asyncio.run(generate_segmented(mock_client, mock_types, comp, output, max_retries=0))

        seg_files = list(tmp_path.glob("seg_*.wav"))
        assert len(seg_files) == 0

    def test_parallel_generates_all_segments(self, tmp_path):
        """workers>0 で並列生成が全セグメント完了する。"""
        comp = make_composition(phases_count=4, total_min=40)
        output = tmp_path / "master.wav"
        seg_pcm = make_pcm(5)

        mock_client = MagicMock()
        mock_types = MagicMock()

        with patch("generate_music_dj.generate_dj", new_callable=AsyncMock, return_value=seg_pcm):
            result = asyncio.run(generate_segmented(mock_client, mock_types, comp, output, max_retries=0, workers=4))

        assert result is not None
        assert output.exists()
        seg_files = list(tmp_path.glob("seg_*.wav"))
        assert len(seg_files) == 0  # クリーンアップ済み

    def test_parallel_with_semaphore(self, tmp_path):
        """workers < segments で Semaphore が機能する。"""
        comp = make_composition(phases_count=4, total_min=40)
        output = tmp_path / "master.wav"
        seg_pcm = make_pcm(5)

        mock_client = MagicMock()
        mock_types = MagicMock()

        with patch("generate_music_dj.generate_dj", new_callable=AsyncMock, return_value=seg_pcm):
            result = asyncio.run(generate_segmented(mock_client, mock_types, comp, output, max_retries=0, workers=2))

        assert result is not None
        assert output.exists()

    def test_parallel_partial_failure(self, tmp_path):
        """並列生成で一部失敗時に None を返す。"""
        comp = make_composition(phases_count=3, total_min=30)
        output = tmp_path / "master.wav"
        seg_pcm = make_pcm(5)
        call_count = 0

        mock_client = MagicMock()
        mock_types = MagicMock()

        async def mock_generate_dj(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return None  # 2番目のセグメントが失敗
            return seg_pcm

        with patch("generate_music_dj.generate_dj", side_effect=mock_generate_dj):
            result = asyncio.run(generate_segmented(mock_client, mock_types, comp, output, max_retries=0, workers=3))

        assert result is None
