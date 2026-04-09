"""generate_music_dj のセグメント分割生成テスト。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from unittest.mock import MagicMock, patch

from youtube_automation.scripts.generate_music_dj import (
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
        {"at_min": round(i * interval, 1), "name": f"phase_{i+1}",
         "name_en": f"phase_{i+1}", "prompt": f"prompt {i+1}"}
        for i in range(phases_count)
    ]
    return {
        "title": "Test",
        "total_duration_min": total_min,
        "model": "lyria-3-pro-preview",
        "base": {"prompt_prefix": "jazz piano"},
        "phases": phases,
        "crossfade_sec": 5,
    }


def make_pcm(duration_sec: float) -> bytes:
    """指定秒数のサイレント PCM データを生成。"""
    num_bytes = int(duration_sec * SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH)
    return b'\x00' * num_bytes


class TestBuildSegmentCompositions:
    def test_auto_subdivides_long_phases(self):
        """デフォルト120秒超のフェーズが自動サブ分割される。"""
        comp = make_composition(phases_count=2, total_min=10)
        # 各フェーズ5分 = 300秒 → ceil(300/120) = 3サブセグメント
        segments = build_segment_compositions(comp)
        assert len(segments) == 6  # 2フェーズ × 3サブセグメント

    def test_short_phases_not_subdivided(self):
        """2分以下のフェーズはサブ分割されない。"""
        comp = {
            "title": "Short",
            "total_duration_min": 4,
            "model": "lyria-3-pro-preview",
                "base": {"prompt_prefix": "test"},
            "phases": [
                {"at_min": 0, "name": "a", "name_en": "a", "prompt": "p1"},
                {"at_min": 2, "name": "b", "name_en": "b", "prompt": "p2"},
            ],
            "crossfade_sec": 5,
        }
        segments = build_segment_compositions(comp)
        assert len(segments) == 2

    def test_segments_have_prompt(self):
        comp = make_composition(phases_count=2, total_min=4)
        segments = build_segment_compositions(comp)
        for seg in segments:
            assert "prompt" in seg
            assert "jazz piano" in seg["prompt"]

    def test_continuation_suffix_on_sub_segments(self):
        """サブセグメントの2番目以降に continuation テキストが付く。"""
        comp = make_composition(phases_count=1, total_min=5)
        # 5分 = 300秒 → 3サブセグメント
        segments = build_segment_compositions(comp)
        assert len(segments) == 3
        assert "continuing" not in segments[0]["prompt"]
        assert "continuing" in segments[1]["prompt"]
        assert "continuing" in segments[2]["prompt"]

    def test_uneven_phases(self):
        """at_min が不均等な場合も正しく分割される。"""
        comp = {
            "title": "Uneven",
            "total_duration_min": 8,
            "model": "lyria-3-pro-preview",
                "base": {"prompt_prefix": "test"},
            "phases": [
                {"at_min": 0, "name": "intro", "name_en": "intro", "prompt": "a"},
                {"at_min": 1, "name": "main", "name_en": "main", "prompt": "b"},
                {"at_min": 6, "name": "outro", "name_en": "outro", "prompt": "c"},
            ],
            "crossfade_sec": 5,
        }
        segments = build_segment_compositions(comp)
        # intro: 1min (1seg), main: 5min (3seg), outro: 2min (1seg) = 5 segments
        assert len(segments) == 5

    def test_duration_hint_sec_respected(self):
        """duration_hint_sec がサブ分割の単位として使われる。"""
        comp = {
            "title": "Hint",
            "total_duration_min": 4,
            "model": "lyria-3-pro-preview",
                "base": {"prompt_prefix": "test"},
            "phases": [
                {"at_min": 0, "name": "a", "name_en": "a", "prompt": "p",
                 "duration_hint_sec": 60},  # 1分ごとに分割
            ],
            "crossfade_sec": 5,
        }
        segments = build_segment_compositions(comp)
        # 4分 = 240秒 / 60秒 = 4サブセグメント
        assert len(segments) == 4

    def test_large_duration_hint_prevents_subdivision(self):
        """duration_hint_sec を大きくすればサブ分割を抑制できる。"""
        comp = {
            "title": "Long",
            "total_duration_min": 10,
            "model": "lyria-3-pro-preview",
                "base": {"prompt_prefix": "test"},
            "phases": [
                {"at_min": 0, "name": "a", "name_en": "a", "prompt": "p",
                 "duration_hint_sec": 600},  # 10分 = フェーズ全体を1セグメント
            ],
            "crossfade_sec": 5,
        }
        segments = build_segment_compositions(comp)
        assert len(segments) == 1


class TestGenerateSegmented:
    def _make_mock_audio(self, duration_sec=5):
        """テスト用の WAV バイトデータを生成。"""
        pcm = make_pcm(duration_sec)
        import io
        import wave
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(SAMPLE_WIDTH)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(pcm)
        return buf.getvalue()

    def test_generates_all_segments_and_joins(self, tmp_path):
        """全セグメント成功時、結合された master.wav が出力される。"""
        comp = make_composition(phases_count=2, total_min=4)
        output = tmp_path / "master.wav"
        audio_data = self._make_mock_audio(5)

        mock_client = MagicMock()
        mock_types = MagicMock()

        with patch("youtube_automation.scripts.generate_music_dj.generate_segment", return_value=audio_data):
            result = generate_segmented(mock_client, mock_types, comp, output, max_retries=0)

        assert result is not None
        assert output.exists()

    def test_skips_existing_segments(self, tmp_path):
        """既存の seg_NNN.wav がある場合はスキップする。"""
        comp = make_composition(phases_count=2, total_min=4)
        output = tmp_path / "master.wav"
        pcm = make_pcm(5)

        # seg_001.wav を事前に作成
        write_wav(pcm, tmp_path / "seg_001.wav")

        mock_client = MagicMock()
        mock_types = MagicMock()
        call_count = 0
        audio_data = self._make_mock_audio(5)

        def mock_generate(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return audio_data

        with patch("youtube_automation.scripts.generate_music_dj.generate_segment", side_effect=mock_generate):
            result = generate_segmented(mock_client, mock_types, comp, output, max_retries=0)

        # seg_001 スキップ、残りを生成
        assert call_count == 1
        assert result is not None

    def test_retries_on_failure(self, tmp_path):
        """失敗時にリトライする。"""
        comp = make_composition(phases_count=2, total_min=4)
        output = tmp_path / "master.wav"
        audio_data = self._make_mock_audio(5)
        attempts = []

        mock_client = MagicMock()
        mock_types = MagicMock()

        def mock_generate(*args, **kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                return None  # 1回目失敗
            return audio_data

        with patch("youtube_automation.scripts.generate_music_dj.generate_segment", side_effect=mock_generate):
            with patch("youtube_automation.scripts.generate_music_dj.time") as mock_time:
                mock_time.sleep = MagicMock()
                result = generate_segmented(mock_client, mock_types, comp, output, max_retries=3)

        assert result is not None
        assert len(attempts) == 3  # seg1 失敗→リトライ成功、seg2 成功

    def test_fails_after_max_retries(self, tmp_path):
        """最大リトライ超過で None を返す。"""
        comp = make_composition(phases_count=2, total_min=4)
        output = tmp_path / "master.wav"

        mock_client = MagicMock()
        mock_types = MagicMock()

        with patch("youtube_automation.scripts.generate_music_dj.generate_segment", return_value=None):
            with patch("youtube_automation.scripts.generate_music_dj.time") as mock_time:
                mock_time.sleep = MagicMock()
                result = generate_segmented(mock_client, mock_types, comp, output, max_retries=2)

        assert result is None

    def test_renames_segment_files_by_default(self, tmp_path):
        """デフォルトではセグメントファイルがフェーズ名でリネームされる。"""
        comp = make_composition(phases_count=2, total_min=4)
        master_dir = tmp_path / "01-master"
        master_dir.mkdir()
        output = master_dir / "master.wav"
        audio_data = self._make_mock_audio(5)

        mock_client = MagicMock()
        mock_types = MagicMock()

        with patch("youtube_automation.scripts.generate_music_dj.generate_segment", return_value=audio_data):
            generate_segmented(mock_client, mock_types, comp, output, max_retries=0)

        seg_files = list(master_dir.glob("seg_*.wav"))
        assert len(seg_files) == 0
        individual_dir = tmp_path / "02-Individual-music"
        renamed_files = sorted(individual_dir.glob("*.wav"))
        assert len(renamed_files) == 2
        assert renamed_files[0].name.startswith("01_")
        assert renamed_files[1].name.startswith("02_")

    def test_cleans_up_segment_files_with_cleanup(self, tmp_path):
        """cleanup=True でセグメントファイルが削除される。"""
        comp = make_composition(phases_count=2, total_min=4)
        output = tmp_path / "master.wav"
        audio_data = self._make_mock_audio(5)

        mock_client = MagicMock()
        mock_types = MagicMock()

        with patch("youtube_automation.scripts.generate_music_dj.generate_segment", return_value=audio_data):
            generate_segmented(mock_client, mock_types, comp, output, max_retries=0, cleanup=True)

        seg_files = list(tmp_path.glob("seg_*.wav"))
        assert len(seg_files) == 0

    def test_parallel_generates_all_segments(self, tmp_path):
        """workers>0 で並列生成が全セグメント完了する。"""
        comp = make_composition(phases_count=2, total_min=4)
        master_dir = tmp_path / "01-master"
        master_dir.mkdir()
        output = master_dir / "master.wav"
        audio_data = self._make_mock_audio(5)

        mock_client = MagicMock()
        mock_types = MagicMock()

        with patch("youtube_automation.scripts.generate_music_dj.generate_segment", return_value=audio_data):
            result = generate_segmented(mock_client, mock_types, comp, output, max_retries=0, workers=4)

        assert result is not None
        assert output.exists()
        seg_files = list(master_dir.glob("seg_*.wav"))
        assert len(seg_files) == 0
        individual_dir = tmp_path / "02-Individual-music"
        renamed_files = sorted(individual_dir.glob("*.wav"))
        assert len(renamed_files) == 2

    def test_parallel_partial_failure(self, tmp_path):
        """並列生成で一部失敗時に None を返す。"""
        comp = make_composition(phases_count=2, total_min=4)
        output = tmp_path / "master.wav"
        audio_data = self._make_mock_audio(5)
        call_count = 0

        mock_client = MagicMock()
        mock_types = MagicMock()

        def mock_generate(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return None
            return audio_data

        with patch("youtube_automation.scripts.generate_music_dj.generate_segment", side_effect=mock_generate):
            with patch("youtube_automation.scripts.generate_music_dj.time") as mock_time:
                mock_time.sleep = MagicMock()
                result = generate_segmented(mock_client, mock_types, comp, output, max_retries=0, workers=3)

        assert result is None
