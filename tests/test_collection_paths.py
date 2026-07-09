"""
CollectionPaths のユニットテスト

テスト対象: utils/collection_paths.py
ファイルシステム操作を tmp_path フィクスチャで検証する。
"""

import sys
from pathlib import Path
from typing import ClassVar

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from youtube_automation.utils.collection_paths import (
    REQUIRED_SUBDIRS,
    CollectionPaths,
    resolve_collection_dir,
)
from youtube_automation.utils.exceptions import ValidationError

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

    def test_shorts_dir(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        assert paths.shorts_dir == tmp_path / "01-master" / "shorts"

    def test_short_loop_path(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        assert paths.short_loop == tmp_path / "10-assets" / "short-loop.mp4"


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
# find_thumbnail: thumbnail.jpg > thumbnail.png
# main.jpg / main.png は textless 動画背景なので upload thumbnail には使わない
# ---------------------------------------------------------------------------


class TestFindThumbnail:
    def test_prefers_thumbnail_jpg(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.assets_dir.mkdir()
        (paths.assets_dir / "thumbnail.jpg").touch()
        (paths.assets_dir / "thumbnail.png").touch()
        (paths.assets_dir / "main.png").touch()
        (paths.assets_dir / "main.jpg").touch()
        assert paths.find_thumbnail().name == "thumbnail.jpg"

    def test_prefers_thumbnail_png_over_main(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.assets_dir.mkdir()
        (paths.assets_dir / "thumbnail.png").touch()
        (paths.assets_dir / "main.png").touch()
        (paths.assets_dir / "main.jpg").touch()
        assert paths.find_thumbnail().name == "thumbnail.png"

    def test_ignores_main_images(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.assets_dir.mkdir()
        (paths.assets_dir / "main.png").touch()
        (paths.assets_dir / "main.jpg").touch()
        assert paths.find_thumbnail() is None

    def test_returns_none_when_no_image(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.assets_dir.mkdir()
        assert paths.find_thumbnail() is None

    def test_returns_none_when_dir_missing(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        assert paths.find_thumbnail() is None


# ---------------------------------------------------------------------------
# 回帰: upload thumbnail resolver は main.* に fallback しない
# （Issue #1310 — main.* は textless 動画背景で、thumbnail.* 欠落を隠さない）
# ---------------------------------------------------------------------------


class TestFindThumbnailUploadContract:
    _UPLOAD_THUMBNAIL_ORDER: ClassVar[list[str]] = ["thumbnail.jpg", "thumbnail.png"]

    @staticmethod
    def _pick_first_existing(assets_dir, order):
        for tn in order:
            candidate = assets_dir / tn
            if candidate.exists():
                return candidate
        return None

    @pytest.mark.parametrize(
        ("present", "expected"),
        [
            ([], None),
            (["thumbnail.jpg"], "thumbnail.jpg"),
            (["thumbnail.png"], "thumbnail.png"),
            (["main.jpg"], None),
            (["main.png"], None),
            (["thumbnail.jpg", "thumbnail.png"], "thumbnail.jpg"),
            (["thumbnail.png", "main.jpg"], "thumbnail.png"),
            (["thumbnail.png", "main.png"], "thumbnail.png"),
            (["main.jpg", "main.png"], None),
            (["thumbnail.jpg", "thumbnail.png", "main.jpg", "main.png"], "thumbnail.jpg"),
        ],
    )
    def test_upload_thumbnail_order_for_all_combinations(self, tmp_path, present, expected):
        paths = CollectionPaths(tmp_path)
        paths.assets_dir.mkdir()
        for name in present:
            (paths.assets_dir / name).touch()

        expected_path = self._pick_first_existing(paths.assets_dir, self._UPLOAD_THUMBNAIL_ORDER)
        result = paths.find_thumbnail()

        assert result == expected_path
        assert (result.name if result else None) == expected


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
# Shorts paths
# ---------------------------------------------------------------------------


class TestShortsPaths:
    def test_find_short_video_prefers_numbered_match(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.shorts_dir.mkdir(parents=True)
        (paths.shorts_dir / "short-01-beta.mp4").touch()
        (paths.shorts_dir / "short-01-alpha.mp4").touch()
        (paths.master_dir / "short.mp4").touch()

        result = paths.find_short_video(1)

        assert result == paths.shorts_dir / "short-01-alpha.mp4"

    def test_find_short_video_falls_back_to_short_mp4(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.master_dir.mkdir()
        fallback = paths.master_dir / "short.mp4"
        fallback.touch()

        assert paths.find_short_video(1) == fallback

    def test_find_short_video_returns_none_when_missing(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.master_dir.mkdir()

        assert paths.find_short_video(1) is None

    def test_short_video_search_paths_with_short_num(self, tmp_path):
        paths = CollectionPaths(tmp_path)

        assert paths.short_video_search_paths(2) == [
            str(tmp_path / "01-master" / "shorts" / "short-02-*.mp4"),
            str(tmp_path / "01-master" / "short.mp4"),
        ]

    def test_short_video_search_paths_without_short_num(self, tmp_path):
        paths = CollectionPaths(tmp_path)

        assert paths.short_video_search_paths() == [
            str(tmp_path / "01-master" / "short.mp4"),
        ]

    def test_short_video_search_paths_for_multiple_numbers(self, tmp_path):
        paths = CollectionPaths(tmp_path)

        assert paths.short_video_search_paths(1)[0] == str(tmp_path / "01-master" / "shorts" / "short-01-*.mp4")
        assert paths.short_video_search_paths(12)[0] == str(tmp_path / "01-master" / "shorts" / "short-12-*.mp4")

    def test_find_short_thumbnail_prefers_jpg(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.assets_dir.mkdir()
        (paths.assets_dir / "short-thumbnail.png").touch()
        jpg = paths.assets_dir / "short-thumbnail.jpg"
        jpg.touch()

        assert paths.find_short_thumbnail() == jpg

    def test_find_short_loop_input_image_prefers_png(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.assets_dir.mkdir()
        (paths.assets_dir / "short.jpg").touch()
        png = paths.assets_dir / "short.png"
        png.touch()

        assert paths.find_short_loop_input_image() == png

    def test_find_short_loop_input_image_finds_jpg_when_png_missing(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.assets_dir.mkdir()
        jpg = paths.assets_dir / "short.jpg"
        jpg.touch()

        assert paths.find_short_loop_input_image() == jpg

    def test_find_short_loop_input_image_returns_none_when_missing(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.assets_dir.mkdir()

        assert paths.find_short_loop_input_image() is None


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


# ---------------------------------------------------------------------------
# resolve_collection_dir (DRY 統合: generate_master / finalize_master 共通)
# ---------------------------------------------------------------------------


class TestResolveCollectionDir:
    """`generate_master.py` / `finalize_master.py` から共通利用される CLI 引数解決。

    `01-master/` / `02-Individual-music/` の契約文字列がこの関数のエラーメッセージと
    `CollectionPaths.master_dir` / `music_dir` プロパティの 1 系統だけに集約され、
    各 script 側でローカル複製しないことの再発防止テスト。
    """

    def test_explicit_arg_returns_resolved_path(self, tmp_path):
        target = tmp_path / "some-collection"
        target.mkdir()
        result = resolve_collection_dir(str(target))
        assert result == target.resolve()

    def test_explicit_arg_does_not_require_subdirs(self, tmp_path):
        # 明示引数のときは存在検証しない (既存挙動の踏襲)。
        target = tmp_path / "no-subdirs"
        target.mkdir()
        result = resolve_collection_dir(str(target))
        assert result == target.resolve()

    def test_cwd_fallback_when_arg_none_and_subdirs_exist(self, tmp_path, monkeypatch):
        (tmp_path / "01-master").mkdir()
        (tmp_path / "02-Individual-music").mkdir()
        monkeypatch.chdir(tmp_path)
        assert resolve_collection_dir(None) == Path.cwd()

    def test_raises_validation_error_when_cwd_missing_master_dir(self, tmp_path, monkeypatch):
        (tmp_path / "02-Individual-music").mkdir()
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValidationError):
            resolve_collection_dir(None)

    def test_raises_validation_error_when_cwd_missing_music_dir(self, tmp_path, monkeypatch):
        (tmp_path / "01-master").mkdir()
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValidationError):
            resolve_collection_dir(None)

    def test_raises_validation_error_when_cwd_has_neither(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValidationError):
            resolve_collection_dir(None)


# ---------------------------------------------------------------------------
# リテラルパス散在の回帰テスト（issue #357）
# ---------------------------------------------------------------------------


class TestLiteralCollectionSubpathRegression:
    """CollectionPaths 採用済みモジュールでコレクションサブパスのリテラル Path
    演算がないことの回帰テスト。

    将来の変更で CollectionPaths を迂回したリテラル Path 演算が混入しないよう、
    issue #357 の移行対象 4 ファイルを機械的に検査する安全網。
    """

    _MIGRATED_FILES: ClassVar[list[str]] = [
        "src/youtube_automation/agents/short_uploader.py",
        "src/youtube_automation/agents/collection_uploader.py",
        "src/youtube_automation/agents/youtube_auto_uploader.py",
        # Issue #465: collection_uploader.py の責務分割で派生した mixin モジュール群。
        # 元ファイル同等の literal Path 回避制約を継続させる。
        "src/youtube_automation/agents/_tracking_io.py",
        "src/youtube_automation/agents/_published_dates.py",
        "src/youtube_automation/agents/_playlist_assignment.py",
        "src/youtube_automation/agents/_complete_collection_executor.py",
        "src/youtube_automation/scripts/generate_short_loop.py",
        "src/youtube_automation/scripts/bulk_update_short_localizations.py",
        "src/youtube_automation/utils/suno_track_selection.py",
    ]

    # CollectionPaths が唯一の参照元であるべきコレクションサブパス文字列
    _COLLECTION_SUBPATH_LITERALS: ClassVar[list[str]] = [
        "01-master",
        "10-assets",
        "20-documentation",
        "workflow-state.json",
        "upload_tracking.json",
    ]

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def _violates(self, line: str) -> bool:
        """コメント行を除く行で、リテラル Path 演算を検出する。

        / "literal" および .glob("literal/...") パターンを対象にする。
        コメント行（# で始まる）は除外。
        """
        import re

        stripped = line.strip()
        if stripped.startswith("#"):
            return False
        escaped = "|".join(re.escape(lit) for lit in self._COLLECTION_SUBPATH_LITERALS)
        # / "literal" パターン（Path 演算子による直接構築）
        if re.search(rf'/ "(?:{escaped})"', line):
            return True
        # .glob("literal/... パターン（glob による直接参照）
        if re.search(rf'\.glob\("(?:{escaped})/', line):
            return True
        return False

    def test_no_literal_path_construction_in_migrated_files(self):
        """migrated files にコレクションサブパスのリテラル Path 演算がないこと。"""
        repo_root = self._repo_root()
        violations: list[str] = []

        for rel_path in self._MIGRATED_FILES:
            file_path = repo_root / rel_path
            assert file_path.exists(), f"移行済みファイルが見つかりません: {rel_path}"
            lines = file_path.read_text(encoding="utf-8").splitlines()
            for lineno, line in enumerate(lines, 1):
                if self._violates(line):
                    violations.append(f"{rel_path}:{lineno}: {line.strip()}")

        assert not violations, (
            "以下のファイルにコレクションサブパスのリテラル Path 演算があります。"
            "CollectionPaths を使用してください:\n" + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# 必須骨格の検証・補完（issue #1494）
# ---------------------------------------------------------------------------


class TestRequiredSkeleton:
    def test_required_subdirs_contract(self):
        """必須骨格の定義が標準レイアウト 4 ディレクトリと一致すること。"""
        assert REQUIRED_SUBDIRS == (
            "01-master",
            "02-Individual-music",
            "10-assets",
            "20-documentation",
        )

    def test_missing_required_dirs_all_missing(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        assert paths.missing_required_dirs() == list(REQUIRED_SUBDIRS)

    def test_missing_required_dirs_partial(self, tmp_path):
        """issue #1494 の実事例: 01-master だけが欠落しているケース。"""
        for sub in REQUIRED_SUBDIRS:
            if sub != "01-master":
                (tmp_path / sub).mkdir()
        paths = CollectionPaths(tmp_path)
        assert paths.missing_required_dirs() == ["01-master"]

    def test_missing_required_dirs_treats_file_as_missing(self, tmp_path):
        """同名ファイルが存在してもディレクトリではないので欠落扱い。"""
        (tmp_path / "01-master").touch()
        paths = CollectionPaths(tmp_path)
        assert "01-master" in paths.missing_required_dirs()
        assert paths.invalid_required_dirs() == ["01-master"]

    def test_ensure_required_dirs_creates_missing(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        created = paths.ensure_required_dirs()
        assert created == list(REQUIRED_SUBDIRS)
        for sub in REQUIRED_SUBDIRS:
            assert (tmp_path / sub).is_dir()

    def test_ensure_required_dirs_idempotent(self, tmp_path):
        paths = CollectionPaths(tmp_path)
        paths.ensure_required_dirs()
        assert paths.ensure_required_dirs() == []

    def test_ensure_required_dirs_preserves_existing_content(self, tmp_path):
        """既存ファイルに触れない（非破壊）こと。"""
        music = tmp_path / "02-Individual-music"
        music.mkdir()
        track = music / "track-01.mp3"
        track.write_bytes(b"audio")
        paths = CollectionPaths(tmp_path)
        created = paths.ensure_required_dirs()
        assert "02-Individual-music" not in created
        assert track.read_bytes() == b"audio"

    def test_ensure_required_dirs_rejects_same_name_file_without_destroying(self, tmp_path):
        collision = tmp_path / "01-master"
        collision.write_text("keep me", encoding="utf-8")
        paths = CollectionPaths(tmp_path)

        with pytest.raises(ValidationError, match="同名のファイル"):
            paths.ensure_required_dirs()

        assert collision.is_file()
        assert collision.read_text(encoding="utf-8") == "keep me"
