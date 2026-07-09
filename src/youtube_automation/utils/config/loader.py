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
    VALID_FALLBACK_VALUES,
    VALID_PROVIDERS,
    Comments,
    GeneratorConfig,
)
from youtube_automation.utils.config.config import ChannelConfig
from youtube_automation.utils.config.content import Content, Descriptions, Genre, Tags, Title
from youtube_automation.utils.config.distrokid import (
    REQUIRED_PROFILE_FIELDS,
    AiDisclosure,
    Distrokid,
    DistrokidProfile,
    DistrokidProfileCredits,
    SongwriterName,
)
from youtube_automation.utils.config.localizations import Localizations
from youtube_automation.utils.config.meta import Branding, ChannelMeta
from youtube_automation.utils.config.pinned_comment import PinnedComment
from youtube_automation.utils.config.playlists import Playlists
from youtube_automation.utils.config.shorts import Shorts, ShortsCollection, ShortsRelease
from youtube_automation.utils.config.workflow import ApprovalGates, WfNext, Workflow
from youtube_automation.utils.config.youtube import (
    ContentModel,
    OverlayAudioVisualizer,
    OverlayEncoder,
    Overlays,
    OverlaySubscribePopup,
    YoutubeApi,
    YoutubeSection,
)
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
    """`config/channel/` を含むプロジェクトルートを解決する.

    優先順: `CHANNEL_DIR` 環境変数 → CWD 祖先探索で `config/channel/` を持つ祖先ディレクトリ.
    """
    env = os.environ.get("CHANNEL_DIR")
    if env:
        return Path(env)
    for parent in [Path.cwd(), *list(Path.cwd().parents)]:
        if (parent / "config" / "channel").is_dir():
            return parent
    raise ConfigError("CHANNEL_DIR 環境変数を設定するか、config/channel/ を持つディレクトリ配下で実行してください")


def channel_dir() -> Path:
    """`config/channel/` を含むプロジェクトルートを返す（シングルトン解決）."""
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
            raise ConfigError(f"JSON パース失敗: {path}: {e}") from e
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
    distrokid = _build_distrokid(merged)

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
        distrokid=distrokid,
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
        channel_id=ch.get("channel_id", ""),
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
        template_check=dict(tl.get("template_check", {})),
    )

    return Content(genre=genre, tags=tags, descriptions=descriptions, title=title)


def _build_youtube(merged: dict) -> YoutubeSection:
    yt = merged["youtube"]
    api = YoutubeApi(
        category_id=yt["category_id"],
        privacy_status=yt["privacy_status"],
        language=yt["language"],
        contains_synthetic_media=bool(yt.get("contains_synthetic_media", True)),
        self_declared_made_for_kids=bool(yt.get("self_declared_made_for_kids", False)),
        default_publish_time=yt.get("default_publish_time"),
        default_publish_timezone=yt.get("default_publish_timezone", "Asia/Tokyo"),
    )

    cm_data = merged.get("content_model") or {}
    content_model = ContentModel(
        type=cm_data.get("type", "release"),
        languages=list(cm_data.get("languages", [api.language])),
    )

    music_engine = merged.get("music_engine", "suno")
    if music_engine not in ("suno", "lyria"):
        logger.warning("music_engine='%s' は未知の値です（既知: 'suno' / 'lyria'）", music_engine)

    overlays = _build_overlays(merged.get("overlays"))

    return YoutubeSection(
        api=api,
        music_engine=music_engine,
        content_model=content_model,
        overlays=overlays,
    )


def _build_overlays(raw: object) -> Overlays:
    """`overlays` セクション（optional, #511）の dataclass 組み立て.

    未設定（`None` / 空 dict）のときは `Overlays(enabled=False)` を返し、
    `generate_videos.sh` 既存 stream copy 経路を完全に維持する。
    """
    if raw is None:
        return Overlays()
    if not isinstance(raw, dict):
        raise ConfigError(f"overlays セクションは object でなければなりません（got {type(raw).__name__}）")

    av_raw = raw.get("audio_visualizer") or {}
    if not isinstance(av_raw, dict):
        raise ConfigError(f"overlays.audio_visualizer は object でなければなりません（got {type(av_raw).__name__}）")
    audio_visualizer = OverlayAudioVisualizer(
        enabled=bool(av_raw.get("enabled", False)),
        mode=str(av_raw.get("mode", "bar")),
        size=str(av_raw.get("size", "1280x180")),
        rate=str(av_raw.get("rate", "24")),
        fscale=str(av_raw.get("fscale", "log")),
        win_size=int(av_raw.get("win_size", 2048)),
        win_func=str(av_raw.get("win_func", "hann")),
        colors=str(av_raw.get("colors", "white")),
        position=str(av_raw.get("position", "(W-w)/2:H-h-40")),
        opacity=float(av_raw.get("opacity", 0.85)),
        glow_enabled=bool(av_raw.get("glow_enabled", True)),
        glow_sigma=float(av_raw.get("glow_sigma", 12.0)),
        glow_opacity=float(av_raw.get("glow_opacity", 0.45)),
    )

    sp_raw = raw.get("subscribe_popup") or {}
    if not isinstance(sp_raw, dict):
        raise ConfigError(f"overlays.subscribe_popup は object でなければなりません（got {type(sp_raw).__name__}）")
    subscribe_popup = OverlaySubscribePopup(
        enabled=bool(sp_raw.get("enabled", False)),
        image=str(sp_raw.get("image", "subscribe-popup.png")),
        start_sec=float(sp_raw.get("start_sec", 5.0)),
        duration_sec=float(sp_raw.get("duration_sec", 8.0)),
        fade_sec=float(sp_raw.get("fade_sec", 0.6)),
        position=str(sp_raw.get("position", "W-w-40:40")),
        opacity=float(sp_raw.get("opacity", 1.0)),
    )

    enc_raw = raw.get("encoder") or {}
    if not isinstance(enc_raw, dict):
        raise ConfigError(f"overlays.encoder は object でなければなりません（got {type(enc_raw).__name__}）")
    encoder = OverlayEncoder(
        codec=str(enc_raw.get("codec", "libx264")),
        preset=str(enc_raw.get("preset", "medium")),
        crf=int(enc_raw.get("crf", 20)),
        pix_fmt=str(enc_raw.get("pix_fmt", "yuv420p")),
        maxrate=str(enc_raw.get("maxrate", "4M")),
        bufsize=str(enc_raw.get("bufsize", "8M")),
        profile=str(enc_raw.get("profile", "high")),
        framerate=int(enc_raw.get("framerate", 24)),
    )

    return Overlays(
        enabled=bool(raw.get("enabled", False)),
        audio_visualizer=audio_visualizer,
        subscribe_popup=subscribe_popup,
        encoder=encoder,
    )


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
            # list / int / null など想定外型は Fail Fast で弾く。
            # silent pass-through すると Playlists.items: dict[str, dict] 型注釈と
            # 実態が乖離し、consumer 側に防御分岐が必要になる（#419）。
            raise ConfigError(
                f"playlists.{key} は string または object でなければなりません（got {type(value).__name__}）"
            )
    return Playlists(items=items)


def _build_workflow(merged: dict) -> Workflow:
    # 旧 top-level `post_upload` / `short` キーが残っていても silently ignore する
    # （`_REQUIRED_KEYS_BY_SECTION` に workflow.json キーを登録していないため）。
    # Shorts スケジュール公開時刻は `shorts.publish_time` に移動。
    if "workflow" in merged:
        wf = merged["workflow"]
    else:
        wf = {}
    if not isinstance(wf, dict):
        raise ConfigError(f"workflow セクションは object でなければなりません（got {type(wf).__name__}）")

    if "wf_next" in wf:
        wf_next_raw = wf["wf_next"]
    else:
        wf_next_raw = {}
    if not isinstance(wf_next_raw, dict):
        raise ConfigError(f"workflow.wf_next は object でなければなりません（got {type(wf_next_raw).__name__}）")

    if "approval_gates" in wf_next_raw:
        gates_raw = wf_next_raw["approval_gates"]
    else:
        gates_raw = {}
    if not isinstance(gates_raw, dict):
        raise ConfigError(
            f"workflow.wf_next.approval_gates は object でなければなりません（got {type(gates_raw).__name__}）"
        )

    return Workflow(
        wf_next=WfNext(
            approval_gates=ApprovalGates(
                audio=_workflow_bool(gates_raw, "audio", "workflow.wf_next.approval_gates.audio"),
                upload=_workflow_bool(gates_raw, "upload", "workflow.wf_next.approval_gates.upload"),
            ),
            skip_manual_mastering=_workflow_bool(
                wf_next_raw,
                "skip_manual_mastering",
                "workflow.wf_next.skip_manual_mastering",
            ),
        ),
    )


def _workflow_bool(raw: dict, key: str, path: str) -> bool:
    value = raw.get(key, False)
    if not isinstance(value, bool):
        raise ConfigError(f"{path} は boolean でなければなりません（got {type(value).__name__}）")
    return value


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
    cm = merged.get("comments", {})
    if not isinstance(cm, dict):
        raise ConfigError("comments セクションは object でなければなりません")
    if "templates" in cm:
        raise ConfigError("comments.templates は廃止されました。LLM provider で返信を生成してください")
    rules_raw = cm.get("rules", [])
    if rules_raw is None:
        rules_raw = []
    if not isinstance(rules_raw, list):
        raise ConfigError("comments.rules は list でなければなりません")

    gen_raw = cm.get("generator")
    generator = GeneratorConfig()
    if gen_raw is not None:
        if not isinstance(gen_raw, dict):
            raise ConfigError("comments.generator は object でなければなりません")
        generator = _build_generator_config(gen_raw)

    language = cm.get("language")
    if language is not None and not isinstance(language, str):
        raise ConfigError("comments.language は文字列でなければなりません")

    return Comments(
        enabled=bool(cm.get("enabled", False)),
        rules=[],
        language=language,
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


def _build_distrokid(merged: dict) -> Distrokid:
    """`distrokid` セクション（optional・opt-in）.

    未配置のチャンネルは `Distrokid(enabled=False)` でロードされ、`/distrokid/*`
    エンドポイントは 404 になる。`enabled=True` のときのみ profile の必須フィールド
    （`REQUIRED_PROFILE_FIELDS`）を条件付き検証する（条件付き必須のため
    `_REQUIRED_KEYS_BY_SECTION` の無条件検証では宣言できず、ここで Fail Fast する）。
    """
    raw = merged.get("distrokid")
    if raw is None:
        return Distrokid()
    if not isinstance(raw, dict):
        raise ConfigError(f"distrokid セクションは object でなければなりません（got {type(raw).__name__}）")

    enabled = bool(raw.get("enabled", False))
    profile_raw = raw.get("profile") or {}
    if not isinstance(profile_raw, dict):
        raise ConfigError(f"distrokid.profile は object でなければなりません（got {type(profile_raw).__name__}）")

    if enabled:
        missing = [f for f in REQUIRED_PROFILE_FIELDS if not profile_raw.get(f)]
        if missing:
            raise ConfigError(
                f"distrokid.enabled=true のとき distrokid.profile に必須フィールドがありません: {', '.join(missing)}"
            )

    if not enabled:
        profile_raw = _disabled_distrokid_profile_raw(profile_raw)

    profile = _build_distrokid_profile(profile_raw)
    return Distrokid(enabled=enabled, profile=profile)


def _disabled_distrokid_profile_raw(profile_raw: dict) -> dict:
    sanitized: dict = {}
    if "artist" in profile_raw:
        sanitized["artist"] = _optional_string(profile_raw, "artist", "distrokid.profile.artist")
    for key in ("language", "main_genre"):
        value = profile_raw.get(key)
        if isinstance(value, str):
            sanitized[key] = value
    sub_genre = profile_raw.get("sub_genre")
    if isinstance(sub_genre, str) or sub_genre is None:
        sanitized["sub_genre"] = sub_genre
    for key in ("songwriter", "ai_disclosure", "credits"):
        value = profile_raw.get(key)
        if isinstance(value, dict) or value is None:
            sanitized[key] = value
    return sanitized


def _build_distrokid_profile(profile_raw: dict) -> DistrokidProfile:
    sub_genre = profile_raw.get("sub_genre")
    return DistrokidProfile(
        artist=_optional_string(profile_raw, "artist", "distrokid.profile.artist"),
        language=str(profile_raw.get("language", "")),
        main_genre=str(profile_raw.get("main_genre", "")),
        sub_genre=str(sub_genre) if sub_genre is not None else None,
        songwriter=_build_songwriter(profile_raw.get("songwriter")),
        ai_disclosure=_build_ai_disclosure(profile_raw.get("ai_disclosure")),
        credits=_build_credits(profile_raw.get("credits")),
    )


def _optional_string(raw: dict, key: str, label: str) -> str:
    value = raw.get(key, "")
    if value is None or not isinstance(value, str):
        raise ConfigError(f"{label} は string でなければなりません（got {type(value).__name__}）")
    return value


def _build_credits(raw: object) -> DistrokidProfileCredits:
    if raw is None:
        return DistrokidProfileCredits()
    if not isinstance(raw, dict):
        raise ConfigError(f"distrokid.profile.credits は object でなければなりません（got {type(raw).__name__}）")
    return DistrokidProfileCredits(
        performer_role=str(raw.get("performer_role", "Synthesizer")),
        producer_role=str(raw.get("producer_role", "Producer")),
    )


def _build_songwriter(raw: object) -> SongwriterName | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError(f"distrokid.profile.songwriter は object でなければなりません（got {type(raw).__name__}）")
    middle = raw.get("middle")
    return SongwriterName(
        first=str(raw.get("first", "")),
        last=str(raw.get("last", "")),
        middle=str(middle) if middle is not None else None,
    )


_VALID_RECORDING_SCOPES = ("full", "partial")
_VALID_PARTIAL_AUDIO_TYPES = (None, "vocals", "instruments")


def _build_ai_disclosure(raw: object) -> AiDisclosure:
    if raw is None:
        return AiDisclosure()
    if not isinstance(raw, dict):
        raise ConfigError(f"distrokid.profile.ai_disclosure は object でなければなりません（got {type(raw).__name__}）")
    recording_scope = raw.get("recording_scope", "full")
    if recording_scope not in _VALID_RECORDING_SCOPES:
        raise ConfigError(
            "distrokid.profile.ai_disclosure.recording_scope は "
            f"'full' / 'partial' のいずれか（got {recording_scope!r}）"
        )
    partial = raw.get("partial_audio_type")
    if partial not in _VALID_PARTIAL_AUDIO_TYPES:
        raise ConfigError(
            "distrokid.profile.ai_disclosure.partial_audio_type は "
            f"'vocals' / 'instruments' / null のいずれか（got {partial!r}）"
        )
    # partial_audio_type は partial 録音の種別なので、recording_scope='partial' 以外で
    # 指定されたら設定ミス（modal にも該当 radio が出ない）として fail-loud。
    if partial is not None and recording_scope != "partial":
        raise ConfigError(
            "distrokid.profile.ai_disclosure.partial_audio_type は recording_scope='partial' のときのみ指定できます"
        )
    return AiDisclosure(
        enabled=bool(raw.get("enabled", True)),
        lyrics=bool(raw.get("lyrics", True)),
        music=bool(raw.get("music", True)),
        recording_scope=recording_scope,
        partial_audio_type=partial,
        artist_persona=bool(raw.get("artist_persona", True)),
        apply_to_all=bool(raw.get("apply_to_all", True)),
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
        raise ConfigError(f"localizations.json の JSON パース失敗: {loc_path}: {e}") from e
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
