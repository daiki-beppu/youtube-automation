"""descriptions.md（/video-description 生成物）の読み込み・抽出ロジック。

``YouTubeAutoUploader`` から分離した mixin。挙動は分割前と同一。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from pathlib import Path

from youtube_automation.utils.collection_paths import CollectionPaths
from youtube_automation.utils.youtube_tag import parse_youtube_tags

logger = logging.getLogger(__name__)

_DESCRIPTIONS_MD_EXPECTED_HEADINGS = (
    "タイトル案",
    "Complete Collection 概要欄",
    "タグ（YouTube タグ欄）",
)

_DESCRIPTIONS_MD_RECREATE_GUIDE = (
    "→ 手書きファイルを直接直すのではなく、正規フローで作り直してください:\n"
    "  1. /video-description を再実行する\n"
    "  2. 生成された 20-documentation/descriptions.md を確認する\n"
    "  3. 必要なら生成後の本文だけを調整してから再アップロードする\n"
    "  必須セクション: `## タイトル案` / `## Complete Collection 概要欄` / `## タグ（YouTube タグ欄）`"
)


def _extract_level2_headings(text: str) -> list[str]:
    """descriptions.md 内の `##` 見出しを出現順で返す."""
    return [match.group(1).strip() for match in re.finditer(r"^##\s+(.+?)\s*$", text, re.MULTILINE)]


def _format_heading_list(headings: Sequence[str]) -> str:
    if not headings:
        return "  - (なし)"
    return "\n".join(f"  - ## {heading}" for heading in headings)


def _build_descriptions_md_parse_diagnostics(text: str, missing_headings: Sequence[str]) -> str:
    """descriptions.md の見出し不一致を人間が直せる形で説明する."""
    found_headings = _extract_level2_headings(text)
    missing = list(dict.fromkeys(missing_headings))
    return "\n".join(
        [
            "期待する見出し（完全一致）:",
            _format_heading_list(_DESCRIPTIONS_MD_EXPECTED_HEADINGS),
            "不足/不一致の見出し:",
            _format_heading_list(missing),
            "検出した ## 見出し:",
            _format_heading_list(found_headings),
            "修正例:",
            "  ## タイトル案",
            "  ```",
            "  公開タイトル",
            "  ```",
            "  ## Complete Collection 概要欄",
            "  ```",
            "  概要欄本文",
            "  ```",
            "  ## タグ（YouTube タグ欄）",
            "  ```",
            "  tag one, tag two",
            "  ```",
            _DESCRIPTIONS_MD_RECREATE_GUIDE,
        ]
    )


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
        if not desc_path.exists():
            # 過去事例: description.txt 等の別名でもファイルが存在し、
            # その場合 fallback 経路で「Track 01」のような汎用名が
            # アップロードされてしまった。意図しないフォールバックを早期発見する。
            stray = list(paths.docs_dir.glob("description*"))
            if stray:
                raise RuntimeError(
                    f"descriptions.md が無いのに別名ファイルが存在します: "
                    f"{[p.name for p in stray]}\n"
                    f"→ ファイル名は `descriptions.md` 固定です。\n"
                    f"{_DESCRIPTIONS_MD_RECREATE_GUIDE}"
                )
            return None

        text = desc_path.read_text(encoding="utf-8")

        title = self._extract_md_section(text, "タイトル案")
        description = self._extract_md_section(text, "Complete Collection 概要欄")
        tags_raw = self._extract_md_section(text, "タグ（YouTube タグ欄）")

        if not (title and description):
            parsed_sections = {
                "タイトル案": title,
                "Complete Collection 概要欄": description,
                "タグ（YouTube タグ欄）": tags_raw,
            }
            missing_headings = [
                heading for heading in _DESCRIPTIONS_MD_EXPECTED_HEADINGS if parsed_sections.get(heading) is None
            ]
            logger.warning(
                "⚠️  descriptions.md のパースに失敗 — 正規フォーマットとして読み込めません\n%s",
                _build_descriptions_md_parse_diagnostics(text, missing_headings),
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
        pattern = rf"## {re.escape(heading)}\s*\n+```\n(.*?)```"
        m = re.search(pattern, text, re.DOTALL)
        return m.group(1).strip() if m else None
