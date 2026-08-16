"""動画説明 JSON+HTML pair の upload 境界。"""

from __future__ import annotations

from pathlib import Path

from youtube_automation.core.adapters.media import CollectionPaths
from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.documents.video_description import read_video_description_metadata
from youtube_automation.infrastructure.filesystem import glob_files, path_exists


def load_description_document(collection_dir: Path) -> dict[str, object] | None:
    """validated JSON 正本だけを読み、旧 Markdown は暗黙 parse しない。"""
    paths = CollectionPaths(collection_dir)
    source = paths.descriptions_json_path
    if not path_exists(source):
        if path_exists(paths.descriptions_md_path):
            raise ValidationError(
                f"{paths.descriptions_md_path}: 旧 descriptions.md は upload 入力にできません。"
                "明示 migration で descriptions.json + descriptions.html pair へ移行してください"
            )
        stray = glob_files(paths.docs_dir, "description*")
        if stray:
            raise ValidationError(
                f"descriptions.json が無いのに別名ファイルが存在します: {[path.name for path in stray]}\n"
                "→ /video --describe で検証済み JSON+HTML pair を生成してください"
            )
        return None
    return read_video_description_metadata(source)
