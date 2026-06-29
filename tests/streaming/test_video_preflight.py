"""infra/terraform/streaming/video_preflight.py の判定ロジック検証（#1299）。"""

from __future__ import annotations

import importlib.util
from types import ModuleType

from tests.streaming._helpers import _VIDEO_PREFLIGHT_PY


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("streaming_video_preflight", _VIDEO_PREFLIGHT_PY)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_check_video_skips_when_ffprobe_missing(monkeypatch, tmp_path):
    """Given ffprobe が PATH に無い
    When check_video を呼ぶ
    Then Terraform plan を壊さないよう ok=true / status=skipped を返す。
    """
    module = _load_module()
    video = tmp_path / "stream.mp4"
    video.write_bytes(b"fake")
    monkeypatch.setattr(module.shutil, "which", lambda _cmd: None)

    result = module.check_video(video)

    assert result["ok"] == "true"
    assert result["status"] == "skipped"
    assert "ffprobe not found" in result["message"]


def test_check_video_fails_low_bitrate_and_long_keyframe_interval(monkeypatch, tmp_path):
    """Given 1080p で bitrate 低すぎ + keyframe 間隔 8.3 秒
    When check_video を呼ぶ
    Then hard fail の ok=false を返す。
    """
    module = _load_module()
    video = tmp_path / "stream.mp4"
    video.write_bytes(b"fake")
    monkeypatch.setattr(module.shutil, "which", lambda _cmd: "/usr/bin/ffprobe")
    monkeypatch.setattr(
        module,
        "_video_metadata",
        lambda _path: (
            {
                "codec_name": "h264",
                "profile": "Constrained Baseline",
                "width": 1920,
                "height": 1080,
                "bit_rate": "1518000",
            },
            {"duration": "20.0"},
        ),
    )
    monkeypatch.setattr(module, "_keyframe_times", lambda _path: [0.0, 8.3, 16.6])

    result = module.check_video(video)

    assert result["ok"] == "false"
    assert result["status"] == "failed"
    assert "keyframe interval 8.30s exceeds 4s" in result["message"]
    assert "video bitrate 1518 Kbps is below 4500 Kbps" in result["message"]
    assert result["profile_ok"] == "false"
    assert "H.264 High is recommended" in result["profile_message"]


def test_check_video_accepts_1080p_h264_high_at_recommended_bitrate(monkeypatch, tmp_path):
    """Given 1080p / H.264 High / 4.5 Mbps / keyframe 2 秒
    When check_video を呼ぶ
    Then ok=true を返す。
    """
    module = _load_module()
    video = tmp_path / "stream.mp4"
    video.write_bytes(b"fake")
    monkeypatch.setattr(module.shutil, "which", lambda _cmd: "/usr/bin/ffprobe")
    monkeypatch.setattr(
        module,
        "_video_metadata",
        lambda _path: (
            {
                "codec_name": "h264",
                "profile": "High",
                "width": 1920,
                "height": 1080,
                "bit_rate": "4500000",
            },
            {"duration": "4.0"},
        ),
    )
    monkeypatch.setattr(module, "_keyframe_times", lambda _path: [0.0, 2.0, 4.0])

    result = module.check_video(video)

    assert result["ok"] == "true"
    assert result["status"] == "ok"
    assert result["profile_ok"] == "true"
    assert result["required_bitrate_kbps"] == "4500"
    assert result["max_keyframe_interval_sec"] == "2.000"


def test_check_video_uses_duration_for_single_keyframe_interval(monkeypatch, tmp_path):
    """Given 10 秒尺で keyframe が冒頭 1 つだけ
    When check_video を呼ぶ
    Then duration 末尾までの間隔を見て hard fail する。
    """
    module = _load_module()
    video = tmp_path / "stream.mp4"
    video.write_bytes(b"fake")
    monkeypatch.setattr(module.shutil, "which", lambda _cmd: "/usr/bin/ffprobe")
    monkeypatch.setattr(
        module,
        "_video_metadata",
        lambda _path: (
            {
                "codec_name": "h264",
                "profile": "High",
                "width": 1920,
                "height": 1080,
                "bit_rate": "4500000",
            },
            {"duration": "10.0"},
        ),
    )
    monkeypatch.setattr(module, "_keyframe_times", lambda _path: [0.0])

    result = module.check_video(video)

    assert result["ok"] == "false"
    assert "keyframe interval 10.00s exceeds 4s" in result["message"]
    assert result["max_keyframe_interval_sec"] == "10.000"


def test_check_video_enforces_720p_bitrate_boundary(monkeypatch, tmp_path):
    """Given 720p の bitrate 境界
    When check_video を呼ぶ
    Then 2,500 Kbps 未満は fail、以上は ok。
    """
    module = _load_module()
    video = tmp_path / "stream.mp4"
    video.write_bytes(b"fake")
    monkeypatch.setattr(module.shutil, "which", lambda _cmd: "/usr/bin/ffprobe")
    monkeypatch.setattr(module, "_keyframe_times", lambda _path: [0.0, 2.0, 4.0])

    def set_metadata(bit_rate: str):
        monkeypatch.setattr(
            module,
            "_video_metadata",
            lambda _path: (
                {
                    "codec_name": "h264",
                    "profile": "High",
                    "width": 1280,
                    "height": 720,
                    "bit_rate": bit_rate,
                },
                {"duration": "4.0"},
            ),
        )

    set_metadata("2499000")
    low_result = module.check_video(video)
    assert low_result["ok"] == "false"
    assert "below 2500 Kbps" in low_result["message"]

    set_metadata("2500000")
    ok_result = module.check_video(video)
    assert ok_result["ok"] == "true"
    assert ok_result["required_bitrate_kbps"] == "2500"
