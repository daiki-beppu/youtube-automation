"""generate_music_dj のセグメント分割生成テスト。"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from unittest.mock import MagicMock, patch  # noqa: F401

from youtube_automation.scripts.generate_music_dj import (
    CHANNELS,
    SAMPLE_RATE,
    SAMPLE_WIDTH,
    _resolve_phase_param,
    _resolve_ref_image,
    _validate_reference_images,
    build_segment_compositions,
    generate_segmented,
    load_composition,
    write_wav,
)
from youtube_automation.utils.exceptions import ConfigError


@pytest.fixture(autouse=True)
def _isolate_channel_dir(tmp_path, monkeypatch):
    """`CHANNEL_DIR` を tmp_path に向けてフィクスチャ汚染を防ぐ。

    `generate_segmented` 経路は `cost_tracker.log_generation` →
    `cost_tracker._channel_dir()` で `CHANNEL_DIR` を直接参照し
    `CHANNEL_DIR/data/audio_costs.json` に追記する（`load_config()` は不使用）。
    conftest のセッション値 (tests/fixtures/sample_channel/) のまま走らせると
    audio_costs.json が汚染されるため env のみ差し替える。
    """
    monkeypatch.setenv("CHANNEL_DIR", str(tmp_path))


def make_composition(phases_count=6, total_min=60, *, base_extras=None, phase_extras_by_index=None):
    """テスト用 composition を生成。

    base_extras: base に追加でマージする dict
    phase_extras_by_index: {phase_index: extras_dict} で特定 phase にキー追加
    """
    phase_extras_by_index = phase_extras_by_index or {}
    interval = total_min / phases_count
    phases = []
    for i in range(phases_count):
        phase = {
            "at_min": round(i * interval, 1),
            "name": f"phase_{i + 1}",
            "name_en": f"phase_{i + 1}",
            "prompt": f"prompt {i + 1}",
        }
        if i in phase_extras_by_index:
            phase.update(phase_extras_by_index[i])
        phases.append(phase)
    base = {"prompt_prefix": "jazz piano"}
    if base_extras:
        base.update(base_extras)
    return {
        "title": "Test",
        "total_duration_min": total_min,
        "model": "lyria-3-pro-preview",
        "base": base,
        "phases": phases,
        "crossfade_sec": 5,
    }


def make_pcm(duration_sec: float) -> bytes:
    """指定秒数のサイレント PCM データを生成。"""
    num_bytes = int(duration_sec * SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH)
    return b"\x00" * num_bytes


class TestBuildSegmentCompositions:
    def test_auto_subdivides_long_phases(self):
        """デフォルト180秒超のフェーズが自動サブ分割される。"""
        comp = make_composition(phases_count=2, total_min=10)
        # 各フェーズ5分 = 300秒 → ceil(300/180) = 2サブセグメント
        segments = build_segment_compositions(comp)
        assert len(segments) == 4  # 2フェーズ × 2サブセグメント

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
        # 5分 = 300秒 → ceil(300/180) = 2サブセグメント
        segments = build_segment_compositions(comp)
        assert len(segments) == 2
        assert "continuing" not in segments[0]["prompt"]
        assert "continuing" in segments[1]["prompt"]

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
        # intro: 1min (1seg), main: 5min (ceil(300/180)=2seg), outro: 2min (1seg) = 4 segments
        assert len(segments) == 4

    def test_duration_hint_sec_respected(self):
        """duration_hint_sec がサブ分割の単位として使われる。"""
        comp = {
            "title": "Hint",
            "total_duration_min": 4,
            "model": "lyria-3-pro-preview",
            "base": {"prompt_prefix": "test"},
            "phases": [
                {"at_min": 0, "name": "a", "name_en": "a", "prompt": "p", "duration_hint_sec": 60},  # 1分ごとに分割
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
                {
                    "at_min": 0,
                    "name": "a",
                    "name_en": "a",
                    "prompt": "p",
                    "duration_hint_sec": 600,
                },  # 10分 = フェーズ全体を1セグメント
            ],
            "crossfade_sec": 5,
        }
        segments = build_segment_compositions(comp)
        assert len(segments) == 1


class TestResolvePhaseParam:
    def test_phase_value_wins(self):
        assert _resolve_phase_param({"bpm": 90}, {"bpm": 140}, "bpm") == 140

    def test_base_value_used_when_phase_missing(self):
        assert _resolve_phase_param({"bpm": 90}, {}, "bpm") == 90

    def test_returns_none_when_both_missing(self):
        assert _resolve_phase_param({}, {}, "bpm") is None

    def test_phase_explicit_none_falls_back_to_base(self):
        assert _resolve_phase_param({"bpm": 90}, {"bpm": None}, "bpm") == 90


class TestResolveRefImage:
    def test_returns_none_for_none_input(self, tmp_path):
        assert _resolve_ref_image(tmp_path, None) is None

    def test_resolves_relative_to_base_dir(self, tmp_path):
        (tmp_path / "10-assets").mkdir()
        img = tmp_path / "10-assets" / "main.png"
        img.write_bytes(b"\x89PNG")
        composition_dir = tmp_path / "20-documentation"
        composition_dir.mkdir()
        resolved = _resolve_ref_image(composition_dir, "../10-assets/main.png")
        assert resolved == img.resolve()

    def test_absolute_path_preserved(self, tmp_path):
        img = tmp_path / "main.png"
        img.write_bytes(b"\x89PNG")
        resolved = _resolve_ref_image(tmp_path / "irrelevant", str(img))
        assert resolved == img

    def test_missing_file_raises_config_error(self, tmp_path):
        with pytest.raises(ConfigError, match="参照画像が存在しません"):
            _resolve_ref_image(tmp_path, "missing.png")


class TestValidateReferenceImages:
    def test_injects_reference_image_paths(self, tmp_path):
        (tmp_path / "10-assets").mkdir()
        img = tmp_path / "10-assets" / "main.png"
        img.write_bytes(b"\x89PNG")
        comp = {
            "_composition_dir": tmp_path / "20-documentation",
            "base": {"reference_image": "../10-assets/main.png"},
            "phases": [{"reference_image": None}, {}],
        }
        (tmp_path / "20-documentation").mkdir()
        _validate_reference_images(comp)
        assert comp["base"]["_reference_image_path"] == img.resolve()
        assert comp["phases"][0]["_reference_image_path"] is None
        assert comp["phases"][1]["_reference_image_path"] is None


class TestGenerateSegmentIntegration:
    def test_lyria_client_called_with_structured_params(self):
        from youtube_automation.scripts.generate_music_dj import generate_segment

        seg = {
            "prompt": "solo piano",
            "model": "lyria-3-pro-preview",
            "phase_name": "intro",
            "bpm": 90,
            "intensity": "low",
            "mode": "instrumental",
            "lyrics": None,
            "reference_image": Path("/fake/main.png"),
        }
        with patch(
            "youtube_automation.scripts.generate_music_dj.lyria_client.generate_music", return_value=b"audio"
        ) as mock_gen:
            result = generate_segment(seg)

        assert result == b"audio"
        _, kwargs = mock_gen.call_args
        assert mock_gen.call_args[0] == ("solo piano", "lyria-3-pro-preview")
        assert kwargs == {
            "reference_image": Path("/fake/main.png"),
            "bpm": 90,
            "intensity": "low",
            "mode": "instrumental",
            "lyrics": None,
        }


class TestSegmentExtraParams:
    def test_base_bpm_propagates_to_segments(self):
        comp = make_composition(phases_count=2, total_min=4, base_extras={"bpm": 120})
        segments = build_segment_compositions(comp)
        assert all(seg["bpm"] == 120 for seg in segments)

    def test_phase_bpm_overrides_base(self):
        comp = make_composition(
            phases_count=2, total_min=4, base_extras={"bpm": 120}, phase_extras_by_index={1: {"bpm": 140}}
        )
        segments = build_segment_compositions(comp)
        # phases_count=2 total=4min → 各 phase 2 分で subdivide なし → 1 segment ずつ
        assert segments[0]["bpm"] == 120
        assert segments[1]["bpm"] == 140

    def test_phase_intensity_override(self):
        comp = make_composition(
            phases_count=2,
            total_min=4,
            base_extras={"intensity": "low"},
            phase_extras_by_index={1: {"intensity": "high"}},
        )
        segments = build_segment_compositions(comp)
        assert segments[0]["intensity"] == "low"
        assert segments[1]["intensity"] == "high"

    def test_phase_mode_override(self):
        comp = make_composition(
            phases_count=2,
            total_min=4,
            base_extras={"mode": "instrumental"},
            phase_extras_by_index={1: {"mode": "vocal", "lyrics": "la la"}},
        )
        segments = build_segment_compositions(comp)
        assert segments[0]["mode"] == "instrumental"
        assert segments[0]["lyrics"] is None
        assert segments[1]["mode"] == "vocal"
        assert segments[1]["lyrics"] == "la la"

    def test_reference_image_propagated_from_base(self, tmp_path):
        (tmp_path / "10-assets").mkdir()
        img = tmp_path / "10-assets" / "main.png"
        img.write_bytes(b"\x89PNG")
        comp = make_composition(phases_count=2, total_min=4)
        comp["_composition_dir"] = tmp_path / "20-documentation"
        comp["base"]["reference_image"] = "../10-assets/main.png"
        (tmp_path / "20-documentation").mkdir()
        _validate_reference_images(comp)
        segments = build_segment_compositions(comp)
        assert all(seg["reference_image"] == img.resolve() for seg in segments)

    def test_segments_without_extras_have_none_values(self):
        comp = make_composition(phases_count=2, total_min=4)
        segments = build_segment_compositions(comp)
        for seg in segments:
            assert seg["bpm"] is None
            assert seg["intensity"] is None
            assert seg["mode"] is None
            assert seg["lyrics"] is None
            assert seg["reference_image"] is None


class TestLoadCompositionWithReferenceImage:
    def _write_composition(self, path: Path, comp: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(comp))

    def test_load_composition_resolves_reference_image(self, tmp_path):
        (tmp_path / "10-assets").mkdir()
        img = tmp_path / "10-assets" / "main.png"
        img.write_bytes(b"\x89PNG")

        comp_path = tmp_path / "20-documentation" / "composition.json"
        self._write_composition(
            comp_path,
            {
                "title": "T",
                "total_duration_min": 4,
                "base": {"prompt_prefix": "test", "reference_image": "../10-assets/main.png"},
                "phases": [{"at_min": 0, "name": "a", "name_en": "a", "prompt": "p"}],
            },
        )

        loaded = load_composition(comp_path)
        assert loaded["base"]["_reference_image_path"] == img.resolve()

    def test_load_composition_missing_image_raises(self, tmp_path):
        comp_path = tmp_path / "20-documentation" / "composition.json"
        self._write_composition(
            comp_path,
            {
                "title": "T",
                "total_duration_min": 4,
                "base": {"prompt_prefix": "test", "reference_image": "../10-assets/missing.png"},
                "phases": [{"at_min": 0, "name": "a", "name_en": "a", "prompt": "p"}],
            },
        )
        with pytest.raises(ConfigError, match="参照画像が存在しません"):
            load_composition(comp_path)


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

        with patch("youtube_automation.scripts.generate_music_dj.generate_segment", return_value=audio_data):
            result = generate_segmented(comp, output, max_retries=0)

        assert result is not None
        assert output.exists()

    def test_skips_existing_segments(self, tmp_path):
        """既存の seg_NNN.wav がある場合はスキップする。"""
        comp = make_composition(phases_count=2, total_min=4)
        output = tmp_path / "master.wav"
        pcm = make_pcm(5)

        # seg_001.wav を事前に作成
        write_wav(pcm, tmp_path / "seg_001.wav")

        call_count = 0
        audio_data = self._make_mock_audio(5)

        def mock_generate(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return audio_data

        with patch("youtube_automation.scripts.generate_music_dj.generate_segment", side_effect=mock_generate):
            result = generate_segmented(comp, output, max_retries=0)

        # seg_001 スキップ、残りを生成
        assert call_count == 1
        assert result is not None

    def test_retries_on_failure(self, tmp_path):
        """失敗時にリトライする。"""
        comp = make_composition(phases_count=2, total_min=4)
        output = tmp_path / "master.wav"
        audio_data = self._make_mock_audio(5)
        attempts = []

        def mock_generate(*args, **kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                return None  # 1回目失敗
            return audio_data

        with patch("youtube_automation.scripts.generate_music_dj.generate_segment", side_effect=mock_generate):
            with patch("youtube_automation.scripts.generate_music_dj.time") as mock_time:
                mock_time.sleep = MagicMock()
                result = generate_segmented(comp, output, max_retries=3)

        assert result is not None
        assert len(attempts) == 3  # seg1 失敗→リトライ成功、seg2 成功

    def test_fails_after_max_retries(self, tmp_path):
        """最大リトライ超過で None を返す。"""
        comp = make_composition(phases_count=2, total_min=4)
        output = tmp_path / "master.wav"

        with patch("youtube_automation.scripts.generate_music_dj.generate_segment", return_value=None):
            with patch("youtube_automation.scripts.generate_music_dj.time") as mock_time:
                mock_time.sleep = MagicMock()
                result = generate_segmented(comp, output, max_retries=2)

        assert result is None

    def test_renames_segment_files_by_default(self, tmp_path):
        """デフォルトではセグメントファイルがフェーズ名でリネームされる。"""
        comp = make_composition(phases_count=2, total_min=4)
        master_dir = tmp_path / "01-master"
        master_dir.mkdir()
        output = master_dir / "master.wav"
        audio_data = self._make_mock_audio(5)

        with patch("youtube_automation.scripts.generate_music_dj.generate_segment", return_value=audio_data):
            generate_segmented(comp, output, max_retries=0)

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

        with patch("youtube_automation.scripts.generate_music_dj.generate_segment", return_value=audio_data):
            generate_segmented(comp, output, max_retries=0, cleanup=True)

        seg_files = list(tmp_path.glob("seg_*.wav"))
        assert len(seg_files) == 0

    def test_parallel_generates_all_segments(self, tmp_path):
        """workers>0 で並列生成が全セグメント完了する。"""
        comp = make_composition(phases_count=2, total_min=4)
        master_dir = tmp_path / "01-master"
        master_dir.mkdir()
        output = master_dir / "master.wav"
        audio_data = self._make_mock_audio(5)

        with patch("youtube_automation.scripts.generate_music_dj.generate_segment", return_value=audio_data):
            result = generate_segmented(comp, output, max_retries=0, workers=4)

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

        def mock_generate(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return None
            return audio_data

        with patch("youtube_automation.scripts.generate_music_dj.generate_segment", side_effect=mock_generate):
            with patch("youtube_automation.scripts.generate_music_dj.time") as mock_time:
                mock_time.sleep = MagicMock()
                result = generate_segmented(comp, output, max_retries=0, workers=3)

        assert result is None
