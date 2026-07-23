"""アップロード前メタデータ品質チェック（fail-loud preflight）。

``YouTubeAutoUploader`` から分離した mixin。挙動は分割前と同一。
``self._extract_md_section`` は ``DescriptionsMdMixin`` が提供する。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from youtube_automation.agents._complete_collection_strategy import resolve_master_video
from youtube_automation.configuration import load_config
from youtube_automation.domains.metadata import BAHMetadataGenerator
from youtube_automation.domains.metadata.descriptions import (
    build_descriptions_md_parse_diagnostics,
    extract_descriptions_md_section,
)
from youtube_automation.utils.collection_paths import CollectionPaths
from youtube_automation.utils.preflight_checks import (
    check_chapter_count,
    check_chapter_variation_suffix,
    check_duration,
    check_low_cpm_localization_languages,
    check_tags_count,
    check_tags_yt_chars,
    check_title_codepoint_limit,
    check_title_template_compliance,
    extract_descriptions_md_tags,
    requires_scene_phrases,
)
from youtube_automation.utils.probe import probe_duration

logger = logging.getLogger(__name__)


class PreflightMixin:
    """アップロード前メタデータ検証を提供する mixin。"""

    def _collect_live_titles(self, exclude_dir: Path | None = None) -> list[str]:
        """既存 live コレクションの公開タイトル（`## タイトル案`）を収集する (#602).

        収集元は `collections/live/*/20-documentation/descriptions.md`。RHS 重複検出の
        比較対象に使う。live ディレクトリ不在・descriptions.md 不在・セクション欠落は
        スキップする。`exclude_dir` で指定したコレクション自身は除外する。
        """
        titles: list[str] = []
        live_root = self.collections_root / "live"
        if not live_root.exists():
            return titles
        exclude_resolved = exclude_dir.resolve() if exclude_dir else None
        for col in sorted(live_root.iterdir()):
            if not col.is_dir() or col.name.startswith("."):
                continue
            if exclude_resolved and col.resolve() == exclude_resolved:
                continue
            desc_path = CollectionPaths(col).descriptions_md_path
            if not desc_path.exists():
                continue
            title = self._extract_md_section(desc_path.read_text(encoding="utf-8"), "タイトル案")
            if title:
                titles.append(title.strip())
        return titles

    def _preflight_check(self, collection_dir: Path) -> None:
        """アップロード前メタデータ品質チェック (fail-loud)。

        過去事例の再発防止:
        1. descriptions.md が存在すること（Track 01 仮名フォールバックを防ぐ）
        2. workflow-state.json が存在し、有効な JSON であること。多言語チャンネルでは
           workflow-state.json.scene_phrases に supported_languages が揃っていること。
           単一言語チャンネルでは populate が no-op のため scene_phrases は要求しない
           （多言語タイトルが EN ベタコピーになる事故を防ぐ）
        3. タイムスタンプ件数が `audio.chapter_max` 以内かつ chapter 名に
           パターン展開接尾辞（v1〜v6 / ロマン数字 I〜VIII）を含まないこと
           （個別トラック = 1 chapter の per-track 命名はデフォルトで許容）
        4. タイトルが 100 codepoint 以内（YouTube 制限）
        5. タグ件数が `tags.min_count` を満たすこと（戦略書違反防止）
        6. タグの quotation 込み文字数が YouTube の 500 制限内
        7. supported_languages に低 CPM 警告対象言語が含まれる場合は warning を出すこと
        """
        paths = CollectionPaths(collection_dir)
        desc_path = paths.descriptions_md_path
        if not desc_path.exists():
            raise RuntimeError(f"❌ {desc_path} が存在しません。/video-description を実行してください。")

        text = desc_path.read_text(encoding="utf-8")
        title_raw = extract_descriptions_md_section(text, "タイトル案")
        description_raw = extract_descriptions_md_section(text, "Complete Collection 概要欄")

        if title_raw is None or description_raw is None:
            raise RuntimeError(
                f"❌ {desc_path}: descriptions.md のパースに失敗\n{build_descriptions_md_parse_diagnostics(text)}"
            )

        title = title_raw.strip()
        description = description_raw.strip()
        if not title or not description:
            raise RuntimeError(f"❌ {desc_path}: タイトル案 / Complete Collection 概要欄 が空")

        if msg := check_title_codepoint_limit(title):
            raise RuntimeError(f"❌ {msg}")

        config = load_config()

        # workflow-state.json 自体は全チャンネルで必須。scene_phrases 完全性だけを
        # 単一言語チャンネルでは不要扱いにする（populate 側と同じ判定を共有 #1470）。
        ws_path = paths.workflow_state_path
        if not ws_path.exists():
            raise RuntimeError(
                f"❌ {ws_path} が存在しません。/wf-new または /video-description の前提を確認してください。"
            )
        state = json.loads(ws_path.read_text(encoding="utf-8"))
        title_template_check = state.get("title_template_check")

        # タイトル鋳型準拠チェック（巻数表記・RHS 重複・鋳型逸脱を機械検出）。
        # 鋳型語彙・パターンは config 駆動、` | ` 鋳型を使うチャンネルでのみ適用。
        title_cfg = config.content.title
        template_check_cfg = {**dict(title_cfg.template_check), "template": title_cfg.template}
        if isinstance(title_template_check, dict) and title_template_check.get("allow_volume_patterns") is True:
            template_check_cfg["volume_patterns"] = ()
        existing_titles = self._collect_live_titles(exclude_dir=collection_dir)
        msg = check_title_template_compliance(title, existing_titles, template_check_cfg)
        if msg:
            raise RuntimeError(
                f"❌ タイトル鋳型違反: {msg}\n"
                f"  title={title!r}\n"
                f"  → コレクション名の流用ではなく鋳型に沿った公開タイトルを /video-description で再生成してください。"
            )

        msg = check_low_cpm_localization_languages(config.localizations.supported_languages)
        if msg:
            logger.warning(f"⚠️  {msg}。意図的な例外でなければ config/localizations.json を見直してください。")

        ts_lines = [line for line in description.split("\n") if re.match(r"^\d{1,2}:\d{2}", line.strip())]
        msg = check_chapter_count(len(ts_lines), config.audio.chapter_max)
        if msg:
            raise RuntimeError(f"❌ {msg}。config.audio.chapter_max を見直してください。")
        msg = check_chapter_variation_suffix(ts_lines)
        if msg:
            raise RuntimeError(f"❌ {msg}: 1 パターン = 1 chapter で再生成してください。")

        scene_phrases = state.get("scene_phrases") or {}

        if requires_scene_phrases(config.localizations.supported_languages):
            required_langs = list(dict.fromkeys(config.localizations.supported_languages))
            missing = [lang for lang in required_langs if not scene_phrases.get(lang)]
            if missing:
                raise RuntimeError(
                    f"❌ workflow-state.json.scene_phrases に翻訳が不足: {missing}\n"
                    f"→ /video-description で多言語翻訳を含めて再生成してください。\n"
                    f"→ 既存例: collections/live/20260322-rjn-city-collection/workflow-state.json"
                )

        # 実 upload と同じ generator で全 locale の title を構築し、API 呼び出し前の
        # --plan preflight でも YouTube の 100 codepoint 制限を検証する。
        generator = BAHMetadataGenerator(str(collection_dir))
        # 同じ invocation で読み込んだ config を使い、plan と upload の設定 snapshot を揃える。
        # 最小 stub を使う既存 unit test では localization data が無いため生成を省略する。
        generator.config = config
        localization_data = getattr(config.localizations, "data", {})
        languages = localization_data.get("languages", {}) if isinstance(localization_data, dict) else {}
        supported = localization_data.get("supported_languages", []) if isinstance(localization_data, dict) else []
        templates_complete = bool(supported) and all(
            languages.get(lang, {}).get("title_template") for lang in supported
        )
        try:
            localizations = (
                generator.generate_localizations(
                    title,
                    description,
                    scene_phrases,
                    scene_emoji=generator._load_scene_emoji(),
                )
                if templates_complete
                else {}
            )
        except ValueError as exc:
            raise RuntimeError(f"❌ ローカライズタイトル検証に失敗:\n{exc}") from exc
        over_limit = [
            f"{locale}={len(value.get('title', ''))}c: {value.get('title', '')!r}"
            for locale, value in localizations.items()
            if check_title_codepoint_limit(value.get("title", ""))
        ]
        if over_limit:
            raise RuntimeError("❌ ローカライズタイトルが 100 codepoint を超過:\n  - " + "\n  - ".join(over_limit))

        # タグ件数 / quotation 文字数チェック
        # descriptions.md の「タグ（YouTube タグ欄）」が _upload_complete_collection で
        # for_collection() を上書きするため、本番と同じソースを検証する。
        prebuilt_tags = extract_descriptions_md_tags(desc_path)
        tags = prebuilt_tags if prebuilt_tags is not None else config.content.tags.for_collection(collection_dir.name)
        issues: list[str] = []
        for msg in (
            check_tags_count(tags, config.content.tags.min_count),
            check_tags_yt_chars(tags),
        ):
            if msg:
                issues.append(msg)

        target_min = getattr(config.audio, "target_duration_min", None)
        target_max = getattr(config.audio, "target_duration_max", None)
        if target_min is not None or target_max is not None:
            master_video = resolve_master_video(collection_dir)
            duration_sec = probe_duration(master_video)
            if duration_sec is None:
                issues.append(f"duration probe failed for {master_video.name}")
            else:
                duration_issue = check_duration(
                    duration_sec,
                    target_min * 60 if target_min is not None else None,
                    target_max * 60 if target_max is not None else None,
                )
                if duration_issue and not getattr(self, "allow_duration_outside_target", False):
                    issues.append(
                        f"{duration_issue}; config/channel/audio.json の target を満たす動画を再生成するか、"
                        "operator 判断で --allow-duration-outside-target を明示してください"
                    )

        if issues:
            raise RuntimeError("❌ preflight failed:\n  - " + "\n  - ".join(issues))

        logger.info(f"✅ preflight OK — title={len(title)}c, chapters={len(ts_lines)}, langs={len(scene_phrases)}")
