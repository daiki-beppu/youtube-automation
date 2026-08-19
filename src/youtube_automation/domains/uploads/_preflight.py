"""アップロード前メタデータ品質チェック（fail-loud preflight）。"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from youtube_automation.configuration import load_config
from youtube_automation.core.adapters.media import CollectionPaths, probe_duration
from youtube_automation.core.errors import ValidationError, WorkflowStateError
from youtube_automation.domains.collections.workflow_state import read as read_workflow_state
from youtube_automation.domains.documents.video_description import read_video_description_metadata
from youtube_automation.domains.metadata import BAHMetadataGenerator
from youtube_automation.domains.uploads._complete_collection_strategy import resolve_master_video
from youtube_automation.domains.uploads.playlist_resolution import (
    check_playlist_assignment,
    resolve_playlist_keys,
)
from youtube_automation.domains.uploads.preflight import (
    check_chapter_count,
    check_chapter_variation_suffix,
    check_duration,
    check_low_cpm_localization_languages,
    check_tags_count,
    check_tags_yt_chars,
    check_title_codepoint_limit,
    check_title_template_compliance,
    requires_scene_phrases,
)
from youtube_automation.infrastructure.filesystem import (
    list_directory,
    path_exists,
    path_is_directory,
)

logger = logging.getLogger(__name__)


class PreflightChecker:
    """明示された collection root と依存でメタデータを検証する。"""

    def __init__(
        self,
        collections_root: Path,
        *,
        config_loader=None,
        duration_probe=None,
        metadata_generator_factory=None,
        master_video_resolver=None,
        allow_duration_outside_target: bool = False,
    ) -> None:
        self.collections_root = collections_root
        self.config_loader = config_loader if config_loader is not None else load_config
        self.duration_probe = duration_probe if duration_probe is not None else probe_duration
        self.metadata_generator_factory = (
            metadata_generator_factory if metadata_generator_factory is not None else BAHMetadataGenerator
        )
        self.master_video_resolver = (
            master_video_resolver if master_video_resolver is not None else resolve_master_video
        )
        self.allow_duration_outside_target = allow_duration_outside_target

    def _collect_live_titles(self, exclude_dir: Path | None = None) -> list[str]:
        """既存 live コレクションの公開タイトル（`## タイトル案`）を収集する (#602).

        収集元は `collections/live/*/20-documentation/descriptions.md`。RHS 重複検出の
        比較対象に使う。live ディレクトリ不在・descriptions.md 不在・セクション欠落は
        スキップする。`exclude_dir` で指定したコレクション自身は除外する。
        """
        titles: list[str] = []
        live_root = self.collections_root / "live"
        if not path_exists(live_root):
            return titles
        exclude_resolved = exclude_dir.resolve() if exclude_dir else None
        for col in sorted(list_directory(live_root)):
            if not path_is_directory(col) or col.name.startswith("."):
                continue
            if exclude_resolved and col.resolve() == exclude_resolved:
                continue
            desc_path = CollectionPaths(col).descriptions_json_path
            if not path_exists(desc_path):
                continue
            metadata = read_video_description_metadata(desc_path)
            title = metadata["title"]
            if isinstance(title, str):
                titles.append(title)
        return titles

    @staticmethod
    def _check_playlist_assignment(state, config) -> None:
        """分類プレイリストへ 1 つも割り当たらない状態を fail-loud で弾く (#4346).

        `auto_add_themes` の theme slug 部分一致は、新テーマを作るたびに
        キーワード未登録で漏れ、黙って `auto_add` プレイリストだけに入る。
        アップロード後の割り当ては非致命的（動画は既に公開済み）なので、
        気付ける唯一の場所がアップロード前のここになる。
        """
        playlists_config = config.playlists.items
        if not playlists_config:
            return
        theme = state.theme or ""
        planning = state.planning
        explicit = planning.playlists if planning is not None else None
        activity = None
        if explicit is None:
            activity = planning.activities if planning is not None else None
            if activity is None:
                activity = config.content.title.activity_for_theme(theme)
        resolved = resolve_playlist_keys(
            playlists_config,
            theme,
            activity=activity or "",
            explicit=explicit,
        )
        issue = check_playlist_assignment(playlists_config, resolved, theme=theme, explicit=explicit)
        if issue:
            raise ValidationError(f"❌ プレイリスト未割り当て: {issue}")

    def check(self, collection_dir: Path) -> None:
        """アップロード前メタデータ品質チェック (fail-loud)。

        過去事例の再発防止:
        1. 検証済み descriptions.json + HTML pair が存在すること（Track 01 仮名フォールバックを防ぐ）
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
        desc_path = paths.descriptions_json_path
        if not path_exists(desc_path):
            raise ValidationError(f"❌ {desc_path} が存在しません。/video --describe を実行してください。")
        prebuilt = read_video_description_metadata(desc_path)
        title = str(prebuilt["title"])
        description = str(prebuilt["description"])

        if msg := check_title_codepoint_limit(title):
            raise ValidationError(f"❌ {msg}")

        config = self.config_loader()

        # workflow-state.json 自体は全チャンネルで必須。scene_phrases 完全性だけを
        # 単一言語チャンネルでは不要扱いにする（populate 側と同じ判定を共有 #1470）。
        ws_path = paths.workflow_state_path
        if not path_exists(ws_path):
            raise ValidationError(
                f"❌ {ws_path} が存在しません。/wf-new または /video --describe の前提を確認してください。"
            )
        try:
            state = read_workflow_state(ws_path)
        except WorkflowStateError as exc:
            if isinstance(exc.__cause__, json.JSONDecodeError):
                raise exc.__cause__ from exc
            raise

        # タイトル鋳型準拠チェック（巻数表記・RHS 重複・鋳型逸脱を機械検出）。
        # 鋳型語彙・パターンは config 駆動、` | ` 鋳型を使うチャンネルでのみ適用。
        title_cfg = config.content.title
        template_check_cfg = {**dict(title_cfg.template_check), "template": title_cfg.template}
        if state.allow_volume_patterns:
            template_check_cfg["volume_patterns"] = ()
        existing_titles = self._collect_live_titles(exclude_dir=collection_dir)
        msg = check_title_template_compliance(title, existing_titles, template_check_cfg)
        if msg:
            raise ValidationError(
                f"❌ タイトル鋳型違反: {msg}\n"
                f"  title={title!r}\n"
                f"  → コレクション名の流用ではなく鋳型に沿った公開タイトルを /video --describe で再生成してください。"
            )

        msg = check_low_cpm_localization_languages(config.localizations.supported_languages)
        if msg:
            logger.warning(f"⚠️  {msg}。意図的な例外でなければ config/localizations.json を見直してください。")

        ts_lines = [line for line in description.split("\n") if re.match(r"^\d{1,2}:\d{2}", line.strip())]
        msg = check_chapter_count(len(ts_lines), config.audio.chapter_max)
        if msg:
            raise ValidationError(f"❌ {msg}。config.audio.chapter_max を見直してください。")
        msg = check_chapter_variation_suffix(ts_lines)
        if msg:
            raise ValidationError(f"❌ {msg}: 1 パターン = 1 chapter で再生成してください。")

        # プレイリスト割り当て（#4346）。アップロード完了後に気付いても手戻りが
        # 大きいので、数 GB を送る前のこの位置で fail-loud する。
        self._check_playlist_assignment(state, config)

        scene_phrases = state.scene_phrases or {}

        if requires_scene_phrases(config.localizations.supported_languages):
            required_langs = list(dict.fromkeys(config.localizations.supported_languages))
            missing = [lang for lang in required_langs if not scene_phrases.get(lang)]
            if missing:
                raise ValidationError(
                    f"❌ workflow-state.json.scene_phrases に翻訳が不足: {missing}\n"
                    f"→ /video --describe で多言語翻訳を含めて再生成してください。\n"
                    f"→ 既存例: collections/live/20260322-rjn-city-collection/workflow-state.json"
                )

        # JSON 正本の全 locale title を API 呼び出し前に再検証する。
        master_video = self.master_video_resolver(collection_dir)
        duration_sec = self.duration_probe(master_video)
        if duration_sec is None:
            raise ValidationError(
                f"❌ 実マスター尺を取得できません: {master_video.name}。"
                "ffprobe で読み取れる完成済みマスター動画を指定してください"
            )
        localizations = prebuilt["localizations"]
        if not isinstance(localizations, dict):
            raise ValidationError("❌ descriptions.json::localizations は object が必要です")
        over_limit = [
            f"{locale}={len(value.get('title', ''))}c: {value.get('title', '')!r}"
            for locale, value in localizations.items()
            if check_title_codepoint_limit(value.get("title", ""))
        ]
        if over_limit:
            raise ValidationError("❌ ローカライズタイトルが 100 codepoint を超過:\n  - " + "\n  - ".join(over_limit))

        # タグ件数 / quotation 文字数チェック
        # 本番と同じ validated JSON の tags を検証する。
        tags_value = prebuilt["tags"]
        if not isinstance(tags_value, list) or not all(isinstance(tag, str) for tag in tags_value):
            raise ValidationError("❌ descriptions.json::tags は string array が必要です")
        tags = tags_value
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
            duration_issue = check_duration(
                duration_sec,
                target_min * 60 if target_min is not None else None,
                target_max * 60 if target_max is not None else None,
            )
            if duration_issue and not self.allow_duration_outside_target:
                issues.append(
                    f"{duration_issue}; config/channel/audio.json の target を満たす動画を再生成するか、"
                    "operator 判断で --allow-duration-outside-target を明示してください"
                )

        if issues:
            raise ValidationError("❌ preflight failed:\n  - " + "\n  - ".join(issues))

        logger.info(f"✅ preflight OK — title={len(title)}c, chapters={len(ts_lines)}, langs={len(scene_phrases)}")
