"""`config/channel/*.json` を glob ロードし、バリデーション後に `ChannelConfig` を組み立てる."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from youtube_automation.utils.config.analytics import Analytics, Benchmark
from youtube_automation.utils.config.audio import Audio
from youtube_automation.utils.config.comments import (
    FALLBACK_SKIP,
    MAX_LENGTH_DEFAULT,
    PROVIDER_CODEX,
    PROVIDER_GEMINI,
    REQUESTS_PER_MINUTE_DEFAULT,
    SCOPE_ANY,
    VALID_FALLBACK_VALUES,
    VALID_PROVIDERS,
    VALID_SCOPES,
    CommentRule,
    Comments,
    GeneratorConfig,
)
from youtube_automation.utils.config.config import ChannelConfig
from youtube_automation.utils.config.content import Content, Descriptions, Genre, Tags, Title
from youtube_automation.utils.config.localizations import Localizations
from youtube_automation.utils.config.meta import Branding, ChannelMeta
from youtube_automation.utils.config.pinned_comment import PinnedComment
from youtube_automation.utils.config.playlists import Playlists
from youtube_automation.utils.config.shorts import Shorts, ShortsCollection, ShortsRelease
from youtube_automation.utils.config.workflow import Workflow
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
    shorts = _build_shorts(merged)
    audio = _build_audio(merged)
    localizations = _load_localizations(channel_dir_path, youtube.api.language)
    comments = _build_comments(merged)
    pinned_comment = _build_pinned_comment(merged)

    _validate_cross_file(youtube, content, localizations)

    return ChannelConfig(
        meta=meta,
        content=content,
        youtube=youtube,
        analytics=analytics,
        playlists=playlists,
        workflow=workflow,
        shorts=shorts,
        audio=audio,
        localizations=localizations,
        comments=comments,
        pinned_comment=pinned_comment,
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
    raw = merged.get("playlists")
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError(f"playlists セクションは object でなければなりません（got {type(raw).__name__}）")
    items: dict[str, dict] = {}
    for key, value in raw.items():
        if isinstance(value, str):
            items[key] = {"playlist_id": value, "auto_add": True, "title": None}
        elif isinstance(value, dict):
            items[key] = dict(value)
        else:
            raise ConfigError(f"playlists.{key} は string または object でなければなりません")
    return Playlists(items=items)


def _build_workflow(merged: dict) -> Workflow:
    # v5 では空 dataclass。旧 top-level `post_upload` / `short` キーが残っていても
    # silently ignore する（`_REQUIRED_KEYS_BY_SECTION` に workflow.json キーを
    # 登録していないため）。Shorts スケジュール公開時刻は `shorts.publish_time` に移動。
    return Workflow()


def _build_shorts(merged: dict) -> Shorts:
    """`shorts` セクション（optional）.

    未配置のチャンネルは `Shorts.enabled = False`（オプトイン）でロードされる。
    `ShortUploader.__init__` が起動時に `UploadError` を投げる。
    """
    sh = merged.get("shorts") or {}
    col = sh.get("collection") or {}
    rel = sh.get("release") or {}
    return Shorts(
        enabled=bool(sh.get("enabled", False)),
        publish_time=str(sh.get("publish_time", "08:00")),
        min_hours_between_shorts_per_collection=int(sh.get("min_hours_between_shorts_per_collection", 24)),
        mode=str(sh.get("mode", "auto")),
        collection=ShortsCollection(
            default_count=int(col.get("default_count", 3)),
            chapter_offset_sec=int(col.get("chapter_offset_sec", 30)),
        ),
        release=ShortsRelease(
            languages=tuple(rel.get("languages", ["jp", "en"])),
            start_sec=int(rel.get("start_sec", 30)),
            duration_sec=int(rel.get("duration_sec", 40)),
        ),
    )


def _build_audio(merged: dict) -> Audio:
    ad = merged.get("audio") or {}
    return Audio(
        target_duration_min=ad.get("target_duration_min"),
        target_duration_max=ad.get("target_duration_max"),
        chapter_max=int(ad.get("chapter_max", 100)),
    )


def _build_generator_config(raw: dict) -> GeneratorConfig:
    if "type" in raw:
        raise ConfigError("comments.generator.type は廃止されました。comments.generator.provider を使用してください")
    provider = raw.get("provider", PROVIDER_CODEX)
    if provider not in VALID_PROVIDERS:
        raise ConfigError(
            f"comments.generator.provider は {VALID_PROVIDERS} のいずれかでなければなりません: {provider!r}"
        )
    if provider == PROVIDER_GEMINI and not raw.get("model"):
        raise ConfigError("comments.generator.provider='gemini' の場合 model は必須です")

    fallback = raw.get("fallback_on_error", FALLBACK_SKIP)
    if fallback not in VALID_FALLBACK_VALUES:
        raise ConfigError(
            f"comments.generator.fallback_on_error は {VALID_FALLBACK_VALUES} "
            f"のいずれかでなければなりません: {fallback!r}"
        )

    return GeneratorConfig(
        provider=provider,
        model=raw.get("model"),
        channel_persona=str(raw.get("channel_persona", "")),
        max_length=int(raw.get("max_length", MAX_LENGTH_DEFAULT)),
        fallback_on_error=fallback,
        requests_per_minute=int(raw.get("requests_per_minute", REQUESTS_PER_MINUTE_DEFAULT)),
    )


def _build_comments(merged: dict) -> Comments:
    cm = merged.get("comments") or {}
    if "templates" in cm:
        raise ConfigError("comments.templates は廃止されました。LLM provider で返信を生成してください")
    rules_raw = cm.get("rules") or []
    rules: list[CommentRule] = []
    for i, raw in enumerate(rules_raw):
        if not isinstance(raw, dict):
            raise ConfigError(f"comments.rules[{i}] は object でなければなりません")
        name = raw.get("name")
        if not name:
            raise ConfigError(f"comments.rules[{i}].name が必須です")
        if "template_key" in raw:
            raise ConfigError(f"comments.rules[{i}].template_key は廃止されました")
        if "generator" in raw:
            raise ConfigError(f"comments.rules[{i}].generator は廃止されました。provider を使用してください")
        rule_provider = raw.get("provider")
        if rule_provider is not None and rule_provider not in VALID_PROVIDERS:
            raise ConfigError(
                f"comments.rules[{i}].provider は {VALID_PROVIDERS} のいずれかでなければなりません: {rule_provider!r}"
            )
        rule_scope = raw.get("scope", SCOPE_ANY)
        if rule_scope not in VALID_SCOPES:
            raise ConfigError(
                f"comments.rules[{i}].scope は {VALID_SCOPES} のいずれかでなければなりません: {rule_scope!r}"
            )
        rules.append(
            CommentRule(
                name=name,
                keywords=list(raw.get("keywords", [])),
                pattern=raw.get("pattern"),
                language=raw.get("language"),
                priority=int(raw.get("priority", 0)),
                provider=rule_provider,
                scope=rule_scope,
            )
        )

    gen_raw = cm.get("generator")
    generator = GeneratorConfig()
    if gen_raw is not None:
        if not isinstance(gen_raw, dict):
            raise ConfigError("comments.generator は object でなければなりません")
        generator = _build_generator_config(gen_raw)

    return Comments(
        enabled=bool(cm.get("enabled", False)),
        rules=rules,
        ng_words=list(cm.get("ng_words", [])),
        max_replies_per_run=int(cm.get("max_replies_per_run", 20)),
        delay_between_replies_sec=float(cm.get("delay_between_replies_sec", 2.0)),
        history_file=str(cm.get("history_file", "comment_reply_history.json")),
        skip_held_for_review=bool(cm.get("skip_held_for_review", True)),
        generator=generator,
    )


def _build_pinned_comment(merged: dict) -> PinnedComment:
    pc = merged.get("pinned_comment") or {}
    if not isinstance(pc, dict):
        raise ConfigError("pinned_comment セクションは object でなければなりません")
    templates_raw = pc.get("templates") or {}
    if not isinstance(templates_raw, dict):
        raise ConfigError("pinned_comment.templates は {言語: テンプレート文字列} の object でなければなりません")
    templates = {str(lang): str(text) for lang, text in templates_raw.items()}
    return PinnedComment(
        enabled=bool(pc.get("enabled", False)),
        history_file=str(pc.get("history_file", "pinned_comment_history.json")),
        delay_between_posts_sec=float(pc.get("delay_between_posts_sec", 2.5)),
        default_language=str(pc.get("default_language", "en")),
        templates=templates,
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
