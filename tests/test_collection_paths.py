"""
CollectionPaths のユニットテスト

テスト対象: utils/collection_paths.py
ファイルシステム操作を tmp_path フィクスチャで検証する。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.collection_paths import CollectionPaths

# ---------------------------------------------------------------------------
# コンストラクタ
# ---------------------------------------------------------------------------

class TestConstructor:
    def test_from_string(self, tmp_path):
        paths = CollectionPaths(str(tmp_path))
        assert paths.root == tmp_path

    def test_from_path(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        assert paths.root == tmp_path

    def test_resolves_to_absolute(self, tmp_path):
        relative = tmp_path / "sub" / ".." / "sub"
        relative.mkdir(parents=True, exist_ok=True)
        paths = CollectionPaths(str(relative))
        assert paths.root.is_absolute()
        assert ".." not in str(paths.root)


# ---------------------------------------------------------------------------
# ディレクトリプロパティ
# ---------------------------------------------------------------------------

class TestDirectoryProperties:
    def test_master_dir(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        assert paths.master_dir == tmp_path / "01-master"

    def test_music_dir(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        assert paths.music_dir == tmp_path / "02-Individual-music"

    def test_movie_dir(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        assert paths.movie_dir == tmp_path / "03-Individual-movie"

    def test_assets_dir(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        assert paths.assets_dir == tmp_path / "10-assets"

    def test_docs_dir(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        assert paths.docs_dir == tmp_path / "20-documentation"


# ---------------------------------------------------------------------------
# ファイルパスプロパティ
# ---------------------------------------------------------------------------

class TestFilePathProperties:
    def test_workflow_state_path(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        assert paths.workflow_state_path == tmp_path / "workflow-state.json"

    def test_tracking_path(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        assert paths.tracking_path == tmp_path / "20-documentation" / "upload_tracking.json"

    def test_descriptions_md_path(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        assert paths.descriptions_md_path == tmp_path / "20-documentation" / "descriptions.md"

    def test_thumbnail_prompts_path(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        assert paths.thumbnail_prompts_path == tmp_path / "20-documentation" / "thumbnail-prompts.md"

    def test_composition_path(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        assert paths.composition_path == tmp_path / "20-documentation" / "composition.json"


# ---------------------------------------------------------------------------
# find_master_video
# ---------------------------------------------------------------------------

class TestFindMasterVideo:
    def test_returns_mp4_when_exists(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.master_dir.mkdir()
        video = paths.master_dir / "master.mp4"
        video.touch()
        assert paths.find_master_video() == video

    def test_returns_none_when_no_mp4(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.master_dir.mkdir()
        assert paths.find_master_video() is None

    def test_returns_first_sorted(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.master_dir.mkdir()
        (paths.master_dir / "b.mp4").touch()
        (paths.master_dir / "a.mp4").touch()
        assert paths.find_master_video().name == "a.mp4"

    def test_ignores_non_mp4(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.master_dir.mkdir()
        (paths.master_dir / "master.mp3").touch()
        assert paths.find_master_video() is None


# ---------------------------------------------------------------------------
# find_master_audio
# ---------------------------------------------------------------------------

class TestFindMasterAudio:
    def test_returns_mp3_when_exists(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.master_dir.mkdir()
        audio = paths.master_dir / "master.mp3"
        audio.touch()
        assert paths.find_master_audio() == audio

    def test_returns_none_when_no_mp3(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.master_dir.mkdir()
        assert paths.find_master_audio() is None

    def test_returns_first_sorted(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.master_dir.mkdir()
        (paths.master_dir / "z.mp3").touch()
        (paths.master_dir / "a.mp3").touch()
        assert paths.find_master_audio().name == "a.mp3"


# ---------------------------------------------------------------------------
# find_thumbnail: thumbnail.jpg > main.png > main.jpg
# ---------------------------------------------------------------------------

class TestFindThumbnail:
    def test_prefers_thumbnail_jpg(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.assets_dir.mkdir()
        (paths.assets_dir / "thumbnail.jpg").touch()
        (paths.assets_dir / "main.png").touch()
        (paths.assets_dir / "main.jpg").touch()
        assert paths.find_thumbnail().name == "thumbnail.jpg"

    def test_falls_back_to_main_png(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.assets_dir.mkdir()
        (paths.assets_dir / "main.png").touch()
        (paths.assets_dir / "main.jpg").touch()
        assert paths.find_thumbnail().name == "main.png"

    def test_falls_back_to_main_jpg(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.assets_dir.mkdir()
        (paths.assets_dir / "main.jpg").touch()
        assert paths.find_thumbnail().name == "main.jpg"

    def test_returns_none_when_no_image(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.assets_dir.mkdir()
        assert paths.find_thumbnail() is None

    def test_returns_none_when_dir_missing(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        assert paths.find_thumbnail() is None


# ---------------------------------------------------------------------------
# find_main_image: main.png > main.jpg
# ---------------------------------------------------------------------------

class TestFindMainImage:
    def test_prefers_main_png(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.assets_dir.mkdir()
        (paths.assets_dir / "main.png").touch()
        (paths.assets_dir / "main.jpg").touch()
        assert paths.find_main_image().name == "main.png"

    def test_falls_back_to_main_jpg(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.assets_dir.mkdir()
        (paths.assets_dir / "main.jpg").touch()
        assert paths.find_main_image().name == "main.jpg"

    def test_returns_none_when_empty(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.assets_dir.mkdir()
        assert paths.find_main_image() is None

    def test_ignores_thumbnail_jpg(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.assets_dir.mkdir()
        (paths.assets_dir / "thumbnail.jpg").touch()
        assert paths.find_main_image() is None


# ---------------------------------------------------------------------------
# find_loop_video
# ---------------------------------------------------------------------------

class TestFindLoopVideo:
    def test_returns_loop_mp4_when_exists(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.assets_dir.mkdir()
        loop = paths.assets_dir / "loop.mp4"
        loop.touch()
        assert paths.find_loop_video() == loop

    def test_returns_none_when_missing(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.assets_dir.mkdir()
        assert paths.find_loop_video() is None


# ---------------------------------------------------------------------------
# individual_music_files
# ---------------------------------------------------------------------------

class TestIndividualMusicFiles:
    def test_returns_sorted_mp3_list(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.music_dir.mkdir(parents=True)
        (paths.music_dir / "03-track.mp3").touch()
        (paths.music_dir / "01-track.mp3").touch()
        (paths.music_dir / "02-track.mp3").touch()
        result = paths.individual_music_files()
        assert len(result) == 3
        assert result[0].name == "01-track.mp3"
        assert result[1].name == "02-track.mp3"
        assert result[2].name == "03-track.mp3"

    def test_returns_empty_when_no_files(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.music_dir.mkdir(parents=True)
        assert paths.individual_music_files() == []

    def test_ignores_non_mp3(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.music_dir.mkdir(parents=True)
        (paths.music_dir / "track.wav").touch()
        (paths.music_dir / "track.mp3").touch()
        result = paths.individual_music_files()
        assert len(result) == 1


# ---------------------------------------------------------------------------
# individual_movie_files
# ---------------------------------------------------------------------------

class TestIndividualMovieFiles:
    def test_returns_sorted_mp4_list(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.movie_dir.mkdir(parents=True)
        (paths.movie_dir / "03-video.mp4").touch()
        (paths.movie_dir / "01-video.mp4").touch()
        result = paths.individual_movie_files()
        assert len(result) == 2
        assert result[0].name == "01-video.mp4"
        assert result[1].name == "03-video.mp4"

    def test_returns_empty_when_no_files(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.movie_dir.mkdir(parents=True)
        assert paths.individual_movie_files() == []


# ---------------------------------------------------------------------------
# collection_name
# ---------------------------------------------------------------------------

class TestCollectionName:
    def test_with_date_and_channel_prefix(self, tmp_path):
        col = tmp_path / "20260310-clm-titanias-midsummer-bower"
        col.mkdir()
        paths = CollectionPaths(col)
        assert paths.collection_name == "titanias-midsummer-bower"

    def test_with_date_prefix_only(self, tmp_path):
        col = tmp_path / "20260310-some-collection"
        col.mkdir()
        paths = CollectionPaths(col)
        assert paths.collection_name == "collection"

    def test_without_prefix(self, tmp_path):
        col = tmp_path / "my-collection"
        col.mkdir()
        paths = CollectionPaths(col)
        assert paths.collection_name == "my-collection"

    def test_simple_name(self, tmp_path):
        col = tmp_path / "forest"
        col.mkdir()
        paths = CollectionPaths(col)
        assert paths.collection_name == "forest"

    def test_numeric_first_part_two_segments(self, tmp_path):
        col = tmp_path / "123-name"
        col.mkdir()
        paths = CollectionPaths(col)
        # Only 2 parts, so len(parts) < 3 → returns full name
        assert paths.collection_name == "123-name"
