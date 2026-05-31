"""コレクションディレクトリ構造のパス解決ユーティリティ。

Usage:
    from youtube_automation.utils.collection_paths import CollectionPaths

    paths = CollectionPaths("/path/to/collection")
    master = paths.find_master_video()
    thumb = paths.find_thumbnail()
"""

from pathlib import Path

from youtube_automation.utils.exceptions import ValidationError

_SHORT_THUMBNAIL_EXTENSIONS = ("jpg", "png")
_SHORT_LOOP_INPUT_NAMES = ("short.png", "short.jpg")

# サムネイル候補ファイルの優先順。アップロード経路
# （agents/youtube_auto_uploader.py::_upload_complete_collection）と統一し、
# 呼び出し経路によらず同一コレクションで同じ画像が選ばれることを保証する。
_THUMBNAIL_CANDIDATES = ("thumbnail.jpg", "thumbnail.png", "main.jpg", "main.png")


class CollectionPaths:
    """標準コレクションディレクトリ構造のパスリゾルバ。

    ディレクトリ構造:
        XXX-collection-name/
        ├── 01-master/           # マスター音声・動画
        ├── 02-Individual-music/ # 個別音声ファイル
        ├── 03-Individual-movie/ # 個別動画ファイル
        ├── 10-assets/           # 静止画・ループ動画素材
        ├── 20-documentation/    # 作業文書・プロンプト
        └── workflow-state.json  # 進捗トラッキング
    """

    def __init__(self, collection_dir: str | Path):
        self.root = Path(collection_dir).resolve()

    @property
    def master_dir(self) -> Path:
        return self.root / "01-master"

    @property
    def music_dir(self) -> Path:
        return self.root / "02-Individual-music"

    @property
    def movie_dir(self) -> Path:
        return self.root / "03-Individual-movie"

    @property
    def assets_dir(self) -> Path:
        return self.root / "10-assets"

    @property
    def docs_dir(self) -> Path:
        return self.root / "20-documentation"

    @property
    def workflow_state_path(self) -> Path:
        return self.root / "workflow-state.json"

    @property
    def tracking_path(self) -> Path:
        return self.docs_dir / "upload_tracking.json"

    @property
    def descriptions_md_path(self) -> Path:
        return self.docs_dir / "descriptions.md"

    @property
    def thumbnail_prompts_path(self) -> Path:
        return self.docs_dir / "thumbnail-prompts.md"

    @property
    def shorts_dir(self) -> Path:
        """番号付き Shorts 動画を格納する実ディレクトリを返す。"""
        return self.master_dir / "shorts"

    def _short_video(self) -> Path:
        """単一 Shorts 動画の実ファイルパスを返す。"""
        return self.master_dir / "short.mp4"

    def _short_video_glob(self, short_num: int) -> str:
        """番号付き Shorts 動画を探すファイル名 glob パターンを返す。"""
        return f"short-{short_num:02d}-*.mp4"

    @property
    def short_loop(self) -> Path:
        """Shorts ループ動画の出力実ファイルパスを返す。"""
        return self.assets_dir / "short-loop.mp4"

    def _short_thumbnail(self, ext: str) -> Path:
        """指定拡張子の Shorts サムネイル実ファイルパスを返す。"""
        if ext not in _SHORT_THUMBNAIL_EXTENSIONS:
            raise ValidationError(
                f"Shorts サムネイル拡張子は {_SHORT_THUMBNAIL_EXTENSIONS} のいずれかが必要です: {ext}"
            )
        return self.assets_dir / f"short-thumbnail.{ext}"

    def find_master_video(self) -> Path | None:
        """01-master/ からマスター動画（.mp4）を探す。"""
        for p in sorted(self.master_dir.glob("*.mp4")):
            return p
        return None

    def find_master_audio(self) -> Path | None:
        """01-master/ からマスター音声（.mp3）を探す。"""
        for p in sorted(self.master_dir.glob("*.mp3")):
            return p
        return None

    def find_thumbnail(self) -> Path | None:
        """10-assets/ からサムネイル画像を探す。

        候補順は ``thumbnail.jpg > thumbnail.png > main.jpg > main.png``
        （``_THUMBNAIL_CANDIDATES``）。アップロード経路
        （``_upload_complete_collection``）と統一しており、呼び出し経路によらず
        同一コレクションで同じ画像が選ばれる。
        """
        for name in _THUMBNAIL_CANDIDATES:
            path = self.assets_dir / name
            if path.exists():
                return path
        return None

    def find_main_image(self) -> Path | None:
        """10-assets/ からメイン画像を探す（main.png > main.jpg）。"""
        for name in ["main.png", "main.jpg"]:
            path = self.assets_dir / name
            if path.exists():
                return path
        return None

    def find_loop_video(self) -> Path | None:
        """10-assets/ からループ動画を探す。"""
        path = self.assets_dir / "loop.mp4"
        return path if path.exists() else None

    def find_short_video(self, short_num: int | None = None) -> Path | None:
        """番号付き Shorts 動画を優先し、無ければ単一 Shorts 動画を探す。"""
        if short_num is not None and self.shorts_dir.exists():
            matches = sorted(self.shorts_dir.glob(self._short_video_glob(short_num)))
            if matches:
                return matches[0]

        fallback = self._short_video()
        return fallback if fallback.exists() else None

    def short_video_search_paths(self, short_num: int | None = None) -> list[str]:
        """Shorts 動画探索時に確認する実パスまたは glob パターンを文字列で返す。"""
        if short_num is None:
            return [str(self._short_video())]
        return [str(self.shorts_dir / self._short_video_glob(short_num)), str(self._short_video())]

    def find_short_thumbnail(self) -> Path | None:
        """Shorts サムネイルの実ファイルを jpg、png の順に探す。"""
        for ext in _SHORT_THUMBNAIL_EXTENSIONS:
            path = self._short_thumbnail(ext)
            if path.exists():
                return path
        return None

    def short_loop_input_image_search_paths(self) -> list[Path]:
        """Shorts ループ動画入力画像の探索候補実パスを返す。"""
        return [self.assets_dir / name for name in _SHORT_LOOP_INPUT_NAMES]

    def find_short_loop_input_image(self) -> Path | None:
        """Shorts ループ動画入力画像の実ファイルを png、jpg の順に探す。"""
        for path in self.short_loop_input_image_search_paths():
            if path.exists():
                return path
        return None

    def individual_music_files(self) -> list[Path]:
        """02-Individual-music/ の音声ファイル一覧（ソート済み）。"""
        return sorted(self.music_dir.glob("*.mp3"))

    def individual_movie_files(self) -> list[Path]:
        """03-Individual-movie/ の動画ファイル一覧（ソート済み）。"""
        return sorted(self.movie_dir.glob("*.mp4"))

    @property
    def collection_name(self) -> str:
        """コレクション名（ディレクトリ名から番号プレフィックスを除去）。"""
        name = self.root.name
        # "20260310-clm-some-name" → "some-name" (チャンネルプレフィックス除去)
        parts = name.split("-", 2)
        if len(parts) >= 3 and parts[0].isdigit():
            return parts[2]
        return name


def resolve_collection_dir(arg: str | None) -> Path:
    """CLI 引数から collection ディレクトリを解決する (CWD フォールバック)。

    `arg` 指定時はそのパスを resolve して返す。未指定時は CWD が
    `01-master/` と `02-Individual-music/` を持つコレクションディレクトリで
    あることを `CollectionPaths` 経由で検証して返す。判定に失敗した場合は
    `ValidationError` を raise する (Fail Fast)。
    """
    if arg:
        return Path(arg).resolve()

    cwd = Path.cwd()
    paths = CollectionPaths(cwd)
    if paths.master_dir.is_dir() and paths.music_dir.is_dir():
        return cwd

    raise ValidationError(
        "コレクションディレクトリを解決できません。引数で指定するか、"
        "01-master/ と 02-Individual-music/ を持つディレクトリで実行してください。"
    )
