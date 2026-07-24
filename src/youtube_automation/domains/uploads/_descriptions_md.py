"""descriptions.md（/video-description 生成物）の読み込み・抽出ロジック。

``YouTubeAutoUploader`` から分離した mixin。挙動は分割前と同一。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from youtube_automation.infrastructure.errors import ValidationError
from youtube_automation.infrastructure.filesystem import glob_files, path_exists, read_file_text
from youtube_automation.utils.collection_paths import CollectionPaths
from youtube_automation.utils.descriptions_md import (
    DESCRIPTIONS_MD_RECREATE_GUIDE,
    build_descriptions_md_parse_diagnostics,
    extract_descriptions_md_section,
)
from youtube_automation.utils.youtube_tag import parse_youtube_tags

logger = logging.getLogger(__name__)


class DescriptionsMdMixin:
    """descriptions.md のパース・ローカライゼーション抽出を提供する mixin。"""

    def _load_descriptions_md(self, collection_dir: Path) -> dict | None:
        """descriptions.md から事前生成メタデータを読み込み

        /video-description スキルが生成した descriptions.md が存在する場合、
        title / description / tags を抽出して返す。
        ファイルが存在しない or パース失敗時は None（BAHMetadataGenerator にフォールバック）。
        """
        paths = CollectionPaths(collection_dir)
        desc_path = paths.descriptions_md_path
        if not path_exists(desc_path):
            # 過去事例: description.txt 等の別名でもファイルが存在し、
            # その場合 fallback 経路で「Track 01」のような汎用名が
            # アップロードされてしまった。意図しないフォールバックを早期発見する。
            stray = glob_files(paths.docs_dir, "description*")
            if stray:
                raise ValidationError(
                    f"descriptions.md が無いのに別名ファイルが存在します: "
                    f"{[p.name for p in stray]}\n"
                    f"→ ファイル名は `descriptions.md` 固定です。\n"
                    f"{DESCRIPTIONS_MD_RECREATE_GUIDE}"
                )
            return None

        text = read_file_text(desc_path)

        title = extract_descriptions_md_section(text, "タイトル案")
        description = extract_descriptions_md_section(text, "Complete Collection 概要欄")
        tags_raw = extract_descriptions_md_section(text, "タグ（YouTube タグ欄）")

        if not (title and description):
            logger.warning(
                "⚠️  descriptions.md のパースに失敗 — 正規フォーマットとして読み込めません\n%s",
                build_descriptions_md_parse_diagnostics(text),
            )
            return None

        tags = parse_youtube_tags(tags_raw) if tags_raw else []

        logger.info("📄 descriptions.md からメタデータを読み込み")
        return {"title": title.strip(), "description": description.strip(), "tags": tags}

    @staticmethod
    def _extract_body_for_localizations(description: str) -> str | None:
        """キュレーション済み概要欄からタイムスタンプ部分を抽出

        ローカライゼーション用: トラックリスト（タイムスタンプ行）のみを返す。
        概要欄の他セクションは generate_localizations() がテンプレートから構築する。
        """
        lines = description.split("\n")
        timestamp_lines = [line for line in lines if re.match(r"^\d{1,2}:\d{2}", line.strip())]
        return "\n".join(timestamp_lines) if timestamp_lines else None

    @staticmethod
    def _extract_md_section(text: str, heading: str) -> str | None:
        """Markdown の ## heading 直後のコードフェンス内容を抽出"""
        return extract_descriptions_md_section(text, heading)
