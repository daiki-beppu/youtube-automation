"""VideoValidator のユニットテスト。

`_check_overall_consistency` が `02-Individual-music/` 配下の `.wav` 以外（特に `.m4a`）も
個別楽曲としてカウントすることを検証する。
"""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from youtube_automation.commands.analytics import video_validator as vv_module
from youtube_automation.domains.media.video_validator import VideoValidator


def _validator() -> VideoValidator:
    return VideoValidator(lambda _path: None)


def _make_collection(tmp_path, audio_filenames):
    coll = tmp_path / "20260423-test-collection"
    audio_dir = coll / "02-Individual-music"
    audio_dir.mkdir(parents=True)
    for name in audio_filenames:
        (audio_dir / name).touch()
    return coll


class TestCheckOverallConsistencyAudioCount:
    """音声ファイル数と個別動画数の整合性チェック."""

    def test_m4a_files_are_counted(self, tmp_path):
        """.m4a 個別楽曲が動画数と一致すれば warning が出ない."""
        coll = _make_collection(tmp_path, ["01-track.m4a", "02-track.m4a"])
        results = {"individual_videos": [{}, {}]}

        issues = _validator()._check_overall_consistency(coll, results)

        assert not any("一致しません" in w for w in issues["warnings"])


def test_unexpected_metadata_reader_error_is_not_converted_to_validation_result(tmp_path):
    """Unexpected implementation errors must remain visible to callers."""
    video = tmp_path / "video.mp4"
    video.touch()
    validator = VideoValidator(lambda _path: (_ for _ in ()).throw(RuntimeError("bug")))

    with pytest.raises(RuntimeError, match="bug"):
        validator._validate_single_video(video, "individual")


def test_none_metadata_is_classified_as_invalid_error(tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")

    result = VideoValidator(lambda _path: None)._validate_single_video(video, "individual")

    assert result["valid"] is False
    assert result["errors"] == ["動画メタデータの取得に失敗しました"]
    assert result["warnings"] == []


def test_partial_metadata_is_invalid_without_exception(tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")

    result = VideoValidator(lambda _path: {"duration": 120})._validate_single_video(video, "individual")

    assert result["valid"] is False
    assert "解像度が取得できません" in result["errors"]
    assert any("サポートされていないコーデックです" in error for error in result["errors"])
    assert result["warnings"] == []


def test_valid_metadata_keeps_quality_problem_as_warning(tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    metadata = {
        "duration": 120,
        "resolution": "1920x1080",
        "codec": "h264",
        "bitrate": 1_000_000,
        "fps": 30,
    }

    result = VideoValidator(lambda _path: metadata)._validate_single_video(video, "individual")

    assert result["valid"] is True
    assert result["errors"] == []
    assert result["warnings"] == ["1080p動画のビットレートが推奨範囲外です（8-12 Mbps）"]


@pytest.mark.parametrize("error", [OSError("io"), ValueError("bad"), TypeError("shape")])
def test_expected_metadata_reader_errors_are_classified_without_propagation(tmp_path, error):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    validator = VideoValidator(lambda _path: (_ for _ in ()).throw(error))

    result = validator._validate_single_video(video, "individual")

    assert result["valid"] is False
    assert result["errors"] == [f"検証エラー: {error}"]
    assert result["warnings"] == []


def test_mixed_extensions_are_counted(tmp_path):
    coll = _make_collection(tmp_path, ["01-a.wav", "02-b.m4a", "03-c.aac", "04-d.mp3", "05-e.flac"])
    issues = _validator()._check_overall_consistency(coll, {"individual_videos": [{}, {}, {}, {}, {}]})

    assert not any("一致しません" in warning for warning in issues["warnings"])


def test_count_mismatch_emits_warning(tmp_path):
    coll = _make_collection(tmp_path, ["01-track.m4a", "02-track.wav"])
    issues = _validator()._check_overall_consistency(coll, {"individual_videos": [{}]})

    assert any("一致しません" in warning for warning in issues["warnings"])


def test_unrelated_files_are_ignored(tmp_path):
    coll = _make_collection(tmp_path, ["01-track.wav"])
    (coll / "02-Individual-music" / ".DS_Store").touch()
    (coll / "02-Individual-music" / "notes.txt").touch()
    issues = _validator()._check_overall_consistency(coll, {"individual_videos": [{}]})

    assert not any("一致しません" in warning for warning in issues["warnings"])


# ---------- argv-injection defense (Issue #186): "--" sentinel ----------


class TestGetVideoMetadataSentinel:
    """ffprobe adapter の argv に `"--"` sentinel が含まれることを検証する。

    Issue #167 で `utils/probe.py` に導入した defense-in-depth を video validator adapter
    へ横展開したリグレッションガード。`-` 始まりパスがオプションとして
    誤解釈される余地を遮断する意図を、通常パス・adversarial パスの双方で固定する。
    """

    def test_places_sentinel_before_path(self, monkeypatch):
        """通常パスでも argv 末尾は `["--", str(path)]` であること."""
        captured: dict = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return SimpleNamespace(stdout='{"streams": [], "format": {}}', returncode=0)

        monkeypatch.setattr(vv_module.subprocess, "run", fake_run)

        vv_module.read_video_metadata(Path("/fake.mp4"))

        assert captured["cmd"][-2] == "--"
        assert captured["cmd"][-1] == "/fake.mp4"

    def test_keeps_sentinel_for_dash_prefixed_path(self, monkeypatch):
        """`-` 始まりの adversarial パスでも sentinel が path の直前に保たれること."""
        captured: dict = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return SimpleNamespace(stdout='{"streams": [], "format": {}}', returncode=0)

        monkeypatch.setattr(vv_module.subprocess, "run", fake_run)

        vv_module.read_video_metadata(Path("-evil.mp4"))

        assert captured["cmd"][-2] == "--"
        assert captured["cmd"][-1] == "-evil.mp4"


class TestReadVideoMetadata:
    def _stub_run(self, monkeypatch, payload):
        monkeypatch.setattr(
            vv_module.subprocess,
            "run",
            lambda *_args, **_kwargs: SimpleNamespace(stdout=json.dumps(payload)),
        )

    def test_normalizes_ffprobe_metadata(self, monkeypatch):
        self._stub_run(
            monkeypatch,
            {
                "streams": [
                    {"codec_type": "audio"},
                    {
                        "codec_type": "video",
                        "width": 1920,
                        "height": 1080,
                        "codec_name": "h264",
                        "r_frame_rate": "30000/1001",
                    },
                ],
                "format": {"duration": "12.5", "bit_rate": "8000000"},
            },
        )

        metadata = vv_module.read_video_metadata(Path("video.mp4"))

        assert metadata == {
            "duration": 12.5,
            "resolution": "1920x1080",
            "codec": "h264",
            "bitrate": 8_000_000,
            "fps": pytest.approx(29.97002997),
        }

    def test_returns_none_without_video_stream(self, monkeypatch):
        self._stub_run(monkeypatch, {"streams": [{"codec_type": "audio"}], "format": {}})

        assert vv_module.read_video_metadata(Path("audio-only.mp4")) is None

    @pytest.mark.parametrize("frame_rate", ["0/0", "invalid"])
    def test_returns_none_for_invalid_frame_rate(self, monkeypatch, frame_rate):
        self._stub_run(
            monkeypatch,
            {
                "streams": [{"codec_type": "video", "r_frame_rate": frame_rate}],
                "format": {},
            },
        )

        assert vv_module.read_video_metadata(Path("invalid.mp4")) is None

    @pytest.mark.parametrize(
        "failure",
        [
            subprocess.CalledProcessError(1, ["ffprobe"]),
            OSError("ffprobe unavailable"),
        ],
    )
    def test_returns_none_when_ffprobe_fails(self, monkeypatch, failure):
        def fail(*_args, **_kwargs):
            raise failure

        monkeypatch.setattr(vv_module.subprocess, "run", fail)

        assert vv_module.read_video_metadata(Path("video.mp4")) is None

    def test_returns_none_for_invalid_json(self, monkeypatch):
        monkeypatch.setattr(
            vv_module.subprocess,
            "run",
            lambda *_args, **_kwargs: SimpleNamespace(stdout="{"),
        )

        assert vv_module.read_video_metadata(Path("video.mp4")) is None


class TestMain:
    def _stub_validator(self, monkeypatch, invalid):
        class StubValidator:
            def __init__(self, reader):
                assert reader is vv_module.read_video_metadata

            def validate_collection(self, path):
                assert path == "/collection"
                return {"summary": {"invalid": invalid}}

            def generate_validation_report(self, results):
                assert results["summary"]["invalid"] == invalid
                return "report"

        monkeypatch.setattr(vv_module, "VideoValidator", StubValidator)

    @pytest.mark.parametrize(("invalid", "expected"), [(0, 0), (1, 1)])
    def test_returns_status_from_validation_result(self, monkeypatch, invalid, expected):
        self._stub_validator(monkeypatch, invalid)
        monkeypatch.setattr(sys, "argv", ["video-validator", "/collection"])

        assert vv_module.main() == expected

    def test_returns_one_when_collection_argument_is_missing(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["video-validator"])

        assert vv_module.main() == 1
