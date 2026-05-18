"""`config/channel/*.json` を glob ロードし、バリデーション後に `ChannelConfig` を組み立てる."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from youtube_automation.utils.config.analytics import Analytics, Benchmark
from youtube_automation.utils.config.audio import Audio
from youtube_automation.utils.config.comments import CommentRule, Comments
from youtube_automation.utils.config.config import ChannelConfig
from youtube_automation.utils.config.content import Content, Descriptions, Genre, Tags, Title
from youtube_automation.utils.config.localizations import Localizations
from youtube_automation.utils.config.meta import Branding, ChannelMeta
from youtube_automation.utils.config.playlists import Playlists
from youtube_automation.utils.config.workflow import DEFAULT_SHORT_PUBLISH_TIME, PostUpload, Workflow
from youtube_automation.utils.config.youtube import ContentModel, YoutubeApi, YoutubeSection
from youtube_automation.utils.exceptions import ConfigError

logger = logging.getLogger(__name__)

_instance: ChannelConfig | None = None
_channel_dir: Path | None = None

# 必須キー（ドット区切り）。分割前の channel_config.py::_REQUIRED_KEYS を新構造へ分配。
_REQUIRED_KEYS_BY_SECTION: dict[str, list[str]] = {
    "meta.json": [
        "channel.name",
        "channel.short",
        "channel.youtube_handle",
        "channel.url",
    ],
    "content.json": [
        "genre.primary",
        "genre.style",
        "genre.context",
        "tags.base",
        "tags.themes",
        "descriptions.opening",
        "descriptions.perfect_for",
        "descriptions.hashtags",
        "title.template",
    ],
    "youtube.json": [
        "youtube.category_id",
        "youtube.privacy_status",
        "youtube.language",
    ],
}


def _resolve_channel_dir() -> Path:
    """チャンネルディレクトリを解決する.

    優先順: `CHANNEL_DIR` 環境変数 → CWD 祖先探索で `config/channel/` を持つディレクトリ.
    """
    env = os.environ.get("CHANNEL_DIR")
    if env:
        return Path(env)
    for parent in [Path.cwd()] + list(Path.cwd().parents):
        if (parent / "config" / "channel").is_dir():
            return parent
    raise ConfigError("CHANNEL_DIR 環境変数を設定するか、config/channel/ を持つディレクトリ配下で実行してください")


def channel_dir() -> Path:
    """チャンネルディレクトリを返す（シングルトン解決）."""
    global _channel_dir
    if _channel_dir is None:
        _channel_dir = _resolve_channel_dir()
    return _channel_dir


def reset() -> None:
    """シングルトン state をリセット（テスト用）."""
    global _instance, _channel_dir
    _instance = None
    _channel_dir = None


def load_config() -> ChannelConfig:
    """`config/channel/*.json` を glob ロードし `ChannelConfig` を返す（シングルトン）."""
    global _instance, _channel_dir
    if _instance is not None:
        return _instance

    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv())

    _channel_dir = _resolve_channel_dir()
    _instance = _build(_channel_dir)
    return _instance


def _build(channel_dir_path: Path) -> ChannelConfig:
    channel_subdir = channel_dir_path / "config" / "channel"
    legacy_path = channel_dir_path / "config" / "channel_config.json"

    if legacy_path.exists():
        raise ConfigError(
            f"旧 channel_config.json が残っています: {legacy_path}\n"
            "yt-config-migrate で新構造 (config/channel/*.json) へ変換してください"
        )

    if not channel_subdir.is_dir():
        raise ConfigError(f"config/channel/ ディレクトリが見つかりません: {channel_subdir}")

    files = sorted(channel_subdir.glob("*.json"))
    if not files:
        raise ConfigError(f"config/channel/ に JSON ファイルが 1 つもありません: {channel_subdir}")

    merged = _load_and_merge(files)
    _validate_required(merged)
    return _assemble(merged, channel_dir_path)


def _load_and_merge(files: list[Path]) -> dict:
    """各ファイルを parse し、トップレベルキー重複を検出しつつ 1 つの dict にマージ."""
    merged: dict[str, object] = {}
    key_origin: dict[str, str] = {}
    for path in files:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ConfigError(f"JSON パース失敗: {path}: {e}")
        if not isinstance(data, dict):
            raise ConfigError(f"{path} のトップレベルは object でなければなりません")
        for key, value in data.items():
            if key in merged:
                raise ConfigError(f"トップレベルキー '{key}' が {key_origin[key]} と {path.name} の両方に存在します")
            merged[key] = value
            key_origin[key] = path.name
    return merged


def _validate_required(merged: dict) -> None:
    """必須キーをドット区切りパスで検証."""
    missing: list[str] = []
    for keys in _REQUIRED_KEYS_BY_SECTION.values():
        for key_path in keys:
            current: object = merged
            for part in key_path.split("."):
                if not isinstance(current, dict) or part not in current:
                    missing.append(key_path)
                    break
                current = current[part]
    if missing:
        raise ConfigError(f"config/channel/ に必須キーがありません: {', '.join(missing)}")


def _assemble(merged: dict, channel_dir_path: Path) -> ChannelConfig:
    meta = _build_meta(merged)
    content = _build_content(merged, meta)
    youtube = _build_youtube(merged)
    analytics = _build_analytics(merged)
    playlists = _build_playlists(merged)
    workflow = _build_workflow(merged)
    audio = _build_audio(merged)
    localizations = _load_localizations(channel_dir_path, youtube.api.language)
    comments = _build_comments(merged)

    _validate_cross_file(youtube, content, localizations)

    return ChannelConfig(
        meta=meta,
        content=content,
        youtube=youtube,
        analytics=analytics,
        playlists=playlists,
        workflow=workflow,
        audio=audio,
        localizations=localizations,
        comments=comments,
    )


def _build_meta(merged: dict) -> ChannelMeta:
    ch = merged["channel"]
    branding = Branding.from_dict(merged.get("youtube_channel"))
    return ChannelMeta(
        channel_name=ch["name"],
        channel_short=ch["short"],
        youtube_handle=ch["youtube_handle"],
        channel_url=ch["url"],
        core_message=ch.get("core_message", ""),
        cta_subscribe=ch.get("cta_subscribe", ""),
        tagline=ch.get("tagline", ""),
        branding=branding,
    )


def _build_content(merged: dict, meta: ChannelMeta) -> Content:
    gn = merged["genre"]
    genre = Genre(primary=gn["primary"], style=gn["style"], context=gn["context"])

    tg = merged["tags"]
    tags = Tags(
        base=list(tg["base"]),
        themes={k: list(v) for k, v in tg["themes"].items()},
        channel_specific=list(tg.get("channel_specific", [])),
        channel_name=meta.channel_name,
        min_count=tg.get("min_count"),
    )

    dp = merged["descriptions"]
    descriptions = Descriptions(
        opening=dp["opening"],
        sub_opening=dp.get("sub_opening", ""),
        perfect_for=list(dp["perfect_for"]),
        hashtags=list(dp["hashtags"]),
        metadata=dict(dp.get("metadata", {})),
        genre=genre,
    )

    tl = merged["title"]
    # 旧実装が default_activities （タイポ）も許容していたので踏襲
    default_activity = tl.get("default_activity", tl.get("default_activities", "Study"))
    title = Title(
        template=tl["template"],
        default_activity=default_activity,
        theme_scenes=dict(tl.get("theme_scenes", {})),
        theme_activities=dict(tl.get("theme_activities", {})),
    )

    return Content(genre=genre, tags=tags, descriptions=descriptions, title=title)


def _build_youtube(merged: dict) -> YoutubeSection:
    yt = merged["youtube"]
    api = YoutubeApi(
        category_id=yt["category_id"],
        privacy_status=yt["privacy_status"],
        language=yt["language"],
    )

    cm_data = merged.get("content_model") or {}
    content_model = ContentModel(
        type=cm_data.get("type", "release"),
        languages=list(cm_data.get("languages", [api.language])),
    )

    music_engine = merged.get("music_engine", "suno")
    if music_engine not in ("suno", "lyria"):
        logger.warning("music_engine='%s' は未知の値です（既知: 'suno' / 'lyria'）", music_engine)

    return YoutubeSection(api=api, music_engine=music_engine, content_model=content_model)


def _build_analytics(merged: dict) -> Analytics:
    an = merged.get("analytics") or {}
    bm = merged.get("benchmark") or {}
    return Analytics(
        collection_filter_keywords=list(an.get("collection_filter_keywords", [])),
        benchmark=Benchmark(channels=list(bm.get("channels", []))),
    )


def _build_playlists(merged: dict) -> Playlists:
    return Playlists(items=dict(merged.get("playlists") or {}))


def _build_workflow(merged: dict) -> Workflow:
    # v5 で `workflow.post_upload.short_publish_time` を Shorts スケジュール用に再導入。
    # 旧 top-level `post_upload` / `short` キーが downstream に残っていても
    # silently ignore する（後方互換）。`_REQUIRED_KEYS_BY_SECTION` に
    # workflow.json キーを登録していないため、ファイル不在 / セクション欠如時は
    # default `"08:00"` で動く。
    workflow_section = merged.get("workflow") or {}
    pu_section = workflow_section.get("post_upload") or {}
    post_upload = PostUpload(
        short_publish_time=pu_section.get("short_publish_time", DEFAULT_SHORT_PUBLISH_TIME),
    )
    return Workflow(post_upload=post_upload)


def _build_audio(merged: dict) -> Audio:
    ad = merged.get("audio") or {}
    return Audio(
        target_duration_min=ad.get("target_duration_min"),
        target_duration_max=ad.get("target_duration_max"),
    )


def _build_comments(merged: dict) -> Comments:
    cm = merged.get("comments") or {}
    rules_raw = cm.get("rules") or []
    rules: list[CommentRule] = []
    for i, raw in enumerate(rules_raw):
        if not isinstance(raw, dict):
            raise ConfigError(f"comments.rules[{i}] は object でなければなりません")
        name = raw.get("name")
        if not name:
            raise ConfigError(f"comments.rules[{i}].name が必須です")
        rules.append(
            CommentRule(
                name=name,
                keywords=list(raw.get("keywords", [])),
                pattern=raw.get("pattern"),
                template_key=raw.get("template_key", "default"),
                language=raw.get("language"),
                priority=int(raw.get("priority", 0)),
            )
        )
    templates_raw = cm.get("templates") or {}
    if not isinstance(templates_raw, dict):
        raise ConfigError("comments.templates は {言語: {key: text}} の object でなければなりません")
    templates: dict[str, dict[str, str]] = {}
    for lang, bucket in templates_raw.items():
        if not isinstance(bucket, dict):
            raise ConfigError(f"comments.templates.{lang} は object でなければなりません")
        templates[str(lang)] = {str(k): str(v) for k, v in bucket.items()}

    return Comments(
        enabled=bool(cm.get("enabled", False)),
        rules=rules,
        templates=templates,
        ng_words=list(cm.get("ng_words", [])),
        max_replies_per_run=int(cm.get("max_replies_per_run", 20)),
        delay_between_replies_sec=float(cm.get("delay_between_replies_sec", 2.0)),
        history_file=str(cm.get("history_file", "comment_reply_history.json")),
        skip_held_for_review=bool(cm.get("skip_held_for_review", True)),
    )


def _load_localizations(channel_dir_path: Path, fallback_language: str) -> Localizations:
    loc_path = channel_dir_path / "config" / "localizations.json"
    if not loc_path.exists():
        return Localizations(
            data={},
            exists=False,
            supported_languages=[fallback_language],
            default_language="",
        )
    try:
        with open(loc_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(f"localizations.json の JSON パース失敗: {loc_path}: {e}")
    if not isinstance(data, dict):
        raise ConfigError(f"localizations.json のトップレベルは object でなければなりません: {loc_path}")
    return Localizations(
        data=data,
        exists=True,
        supported_languages=list(data.get("supported_languages", [])),
        default_language=data.get("default_language", ""),
    )


def _validate_cross_file(
    youtube: YoutubeSection,
    content: Content,
    localizations: Localizations,
) -> None:
    """ファイル跨ぎ整合性チェック（違反はすべて ConfigError）."""
    # 1. content_model.languages ⊆ localizations.supported_languages（localizations 存在時）
    if localizations.exists:
        unknown_langs = [
            lang for lang in youtube.content_model.languages if lang not in localizations.supported_languages
        ]
        if unknown_langs:
            raise ConfigError(
                f"content_model.languages に localizations.supported_languages へ未登録の"
                f"言語があります: {unknown_langs}"
            )

    # 2. title.theme_scenes のキー ⊆ tags.themes のキー
    unknown_scenes = set(content.title.theme_scenes.keys()) - set(content.tags.themes.keys())
    if unknown_scenes:
        raise ConfigError(
            f"title.theme_scenes に tags.themes で定義されていないテーマキーがあります: {sorted(unknown_scenes)}"
        )
