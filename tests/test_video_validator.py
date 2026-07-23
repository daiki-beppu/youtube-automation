"""VideoValidator のユニットテスト。

`_check_overall_consistency` が `02-Individual-music/` 配下の `.wav` 以外（特に `.m4a`）も
個別楽曲としてカウントすることを検証する。
"""

from pathlib import Path
from types import SimpleNamespace

from youtube_automation.domains.media.video_validator import VideoValidator
from youtube_automation.scripts import video_validator as vv_module


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

    import pytest

    with pytest.raises(RuntimeError, match="bug"):
        validator._validate_single_video(video, "individual")

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
