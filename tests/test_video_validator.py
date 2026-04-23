"""VideoValidator のユニットテスト。

`_check_overall_consistency` が `02-Individual-music/` 配下の `.wav` 以外（特に `.m4a`）も
個別楽曲としてカウントすることを検証する。
"""

from youtube_automation.utils.video_validator import VideoValidator


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

        issues = VideoValidator()._check_overall_consistency(coll, results)

        assert not any("一致しません" in w for w in issues["warnings"])

    def test_mixed_extensions_are_counted(self, tmp_path):
        """wav / m4a / aac / mp3 / flac が混在しても全て個別楽曲としてカウントされる."""
        coll = _make_collection(
            tmp_path,
            ["01-a.wav", "02-b.m4a", "03-c.aac", "04-d.mp3", "05-e.flac"],
        )
        results = {"individual_videos": [{}, {}, {}, {}, {}]}

        issues = VideoValidator()._check_overall_consistency(coll, results)

        assert not any("一致しません" in w for w in issues["warnings"])

    def test_count_mismatch_emits_warning(self, tmp_path):
        """音声ファイル数 != 動画数のときは従来どおり warning を出す."""
        coll = _make_collection(tmp_path, ["01-track.m4a", "02-track.wav"])
        results = {"individual_videos": [{}]}  # 動画は 1 本だけ

        issues = VideoValidator()._check_overall_consistency(coll, results)

        assert any("一致しません" in w for w in issues["warnings"])

    def test_unrelated_files_are_ignored(self, tmp_path):
        """README.md や .DS_Store など AUDIO_EXTS 以外は無視される."""
        coll = _make_collection(tmp_path, ["01-track.wav"])
        (coll / "02-Individual-music" / ".DS_Store").touch()
        (coll / "02-Individual-music" / "notes.txt").touch()
        results = {"individual_videos": [{}]}

        issues = VideoValidator()._check_overall_consistency(coll, results)

        assert not any("一致しません" in w for w in issues["warnings"])
