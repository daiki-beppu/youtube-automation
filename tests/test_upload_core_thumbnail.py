"""``YouTubeUploadCore._compress_thumbnail`` のユニットテスト。

plan 020 Step 5: 全品質失敗時の temp ファイルリークと、ffmpeg が一度も
出力しなかった場合の ``FileNotFoundError`` を回帰させないためのテスト。
"""

from pathlib import Path
from unittest.mock import MagicMock, patch


def _make_core():
    with patch("youtube_automation.utils.upload_core.get_youtube"):
        from youtube_automation.utils.upload_core import YouTubeUploadCore

        return YouTubeUploadCore()


class TestCompressThumbnailFailureCleanup:
    def test_ffmpeg_receives_absolute_input_path(self, tmp_path, monkeypatch):
        """相対パスが渡されても ffmpeg の入力 argv は絶対パスにする。"""
        core = _make_core()
        monkeypatch.chdir(tmp_path)
        thumb = Path("thumb.jpg")
        thumb.write_bytes(b"x" * (3 * 1024 * 1024))
        tmp_marker = tmp_path / "compressed_tmp.jpg"

        def _fake_run(cmd, capture_output=True):
            assert Path(cmd[cmd.index("-i") + 1]).is_absolute()
            return MagicMock()

        with (
            patch("tempfile.NamedTemporaryFile") as mock_ntf,
            patch("subprocess.run", side_effect=_fake_run),
        ):
            mock_file = MagicMock()
            mock_file.name = str(tmp_marker)
            mock_ntf.return_value = mock_file

            result = core._compress_thumbnail(thumb)

        assert result == thumb

    def test_no_temp_file_leaked_when_ffmpeg_never_produces_output(self, tmp_path):
        """ffmpeg が一度も出力しなかった場合でも FileNotFoundError を起こさず、
        temp ファイルもリークしない（元パスをそのまま返す）。"""
        core = _make_core()

        thumb = tmp_path / "thumb.jpg"
        thumb.write_bytes(b"x" * (3 * 1024 * 1024))  # 3MB > 2MB

        with (
            patch(
                "tempfile.NamedTemporaryFile",
            ) as mock_ntf,
            patch("subprocess.run") as mock_run,
        ):
            tmp_marker = tmp_path / "compressed_tmp.jpg"
            mock_file = MagicMock()
            mock_file.name = str(tmp_marker)
            mock_ntf.return_value = mock_file
            mock_run.return_value = MagicMock()
            # ffmpeg は何も書かない（tmp_marker は作られない）

            result = core._compress_thumbnail(thumb)

        assert result == thumb
        assert not tmp_marker.exists()

    def test_temp_file_removed_when_all_qualities_stay_oversize(self, tmp_path):
        """圧縮を全品質試しても max_bytes を超え続ける場合、temp ファイルを
        リークせず元パスを返す。"""
        core = _make_core()

        thumb = tmp_path / "thumb.jpg"
        thumb.write_bytes(b"x" * (3 * 1024 * 1024))  # 3MB > 2MB

        tmp_marker = tmp_path / "compressed_tmp.jpg"

        def _fake_run(cmd, capture_output=True):
            # ffmpeg 呼び出しをシミュレートし、常に max_bytes 超のファイルを書く
            Path(cmd[-1]).write_bytes(b"y" * (2 * 1024 * 1024 + 1))
            return MagicMock()

        with (
            patch("tempfile.NamedTemporaryFile") as mock_ntf,
            patch("subprocess.run", side_effect=_fake_run),
        ):
            mock_file = MagicMock()
            mock_file.name = str(tmp_marker)
            mock_ntf.return_value = mock_file

            result = core._compress_thumbnail(thumb)

        assert result == thumb
        assert not tmp_marker.exists()

    def test_returns_original_path_unchanged_when_under_max_bytes(self, tmp_path):
        """max_bytes 以下のファイルは圧縮せずそのまま返す（挙動互換）。"""
        core = _make_core()

        thumb = tmp_path / "thumb.jpg"
        thumb.write_bytes(b"x" * 1000)

        result = core._compress_thumbnail(thumb)

        assert result == thumb
