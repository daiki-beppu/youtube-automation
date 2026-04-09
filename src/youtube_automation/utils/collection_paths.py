"""コレクションディレクトリ構造のパス解決ユーティリティ。

Usage:
    from youtube_automation.utils.collection_paths import CollectionPaths

    paths = CollectionPaths("/path/to/collection")
    master = paths.find_master_video()
    thumb = paths.find_thumbnail()
"""

from pathlib import Path


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
        return self.root / '01-master'

    @property
    def music_dir(self) -> Path:
        return self.root / '02-Individual-music'

    @property
    def movie_dir(self) -> Path:
        return self.root / '03-Individual-movie'

    @property
    def assets_dir(self) -> Path:
        return self.root / '10-assets'

    @property
    def docs_dir(self) -> Path:
        return self.root / '20-documentation'

    @property
    def workflow_state_path(self) -> Path:
        return self.root / 'workflow-state.json'

    @property
    def tracking_path(self) -> Path:
        return self.root / '20-documentation' / 'upload_tracking.json'

    @property
    def descriptions_md_path(self) -> Path:
        return self.root / '20-documentation' / 'descriptions.md'

    @property
    def thumbnail_prompts_path(self) -> Path:
        return self.root / '20-documentation' / 'thumbnail-prompts.md'

    @property
    def composition_path(self) -> Path:
        return self.root / '20-documentation' / 'composition.json'

    def find_master_video(self) -> Path | None:
        """01-master/ からマスター動画（.mp4）を探す。"""
        for p in sorted(self.master_dir.glob('*.mp4')):
            return p
        return None

    def find_master_audio(self) -> Path | None:
        """01-master/ からマスター音声（.mp3）を探す。"""
        for p in sorted(self.master_dir.glob('*.mp3')):
            return p
        return None

    def find_thumbnail(self) -> Path | None:
        """10-assets/ からサムネイル画像を探す（thumbnail.jpg > main.png）。"""
        for name in ['thumbnail.jpg', 'main.png', 'main.jpg']:
            path = self.assets_dir / name
            if path.exists():
                return path
        return None

    def find_main_image(self) -> Path | None:
        """10-assets/ からメイン画像を探す（main.png > main.jpg）。"""
        for name in ['main.png', 'main.jpg']:
            path = self.assets_dir / name
            if path.exists():
                return path
        return None

    def find_loop_video(self) -> Path | None:
        """10-assets/ からループ動画を探す。"""
        path = self.assets_dir / 'loop.mp4'
        return path if path.exists() else None

    def individual_music_files(self) -> list[Path]:
        """02-Individual-music/ の音声ファイル一覧（ソート済み）。"""
        return sorted(self.music_dir.glob('*.mp3'))

    def individual_movie_files(self) -> list[Path]:
        """03-Individual-movie/ の動画ファイル一覧（ソート済み）。"""
        return sorted(self.movie_dir.glob('*.mp4'))

    @property
    def collection_name(self) -> str:
        """コレクション名（ディレクトリ名から番号プレフィックスを除去）。"""
        name = self.root.name
        # "20260310-clm-some-name" → "some-name" (チャンネルプレフィックス除去)
        parts = name.split('-', 2)
        if len(parts) >= 3 and parts[0].isdigit():
            return parts[2]
        return name
