"""`config/channel/*.json` を glob ロードし、バリデーション後に `ChannelConfig` を組み立てる."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from youtube_automation.utils.audio_visualizer_fill import normalize_ffmpeg_color, parse_color
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
from youtube_automation.utils.config.community_draft import CommunityDraft, CommunityDraftPost
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
from youtube_automation.utils.config.workflow import (
    SCHEDULED_AUTOMATION_CADENCE_DAYS,
    SCHEDULED_AUTOMATION_NOTIFICATIONS,
    ApprovalGates,
    PostPublish,
    PostPublishApprovalGates,
    ScheduledAutomation,
    WfNext,
    Workflow,
)
from youtube_automation.utils.config.youtube import (
    AudioVisualizerFill,
    AudioVisualizerGlow,
    AudioVisualizerRounding,
    ContentModel,
    OverlayAudioVisualizer,
    OverlayAudioVisualizerRing,
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
_explicit_channel: str | None = None

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


def workspace_channels(workspace_root: Path) -> dict[str, Path]:
    """workspace 直下の有効な channel slug とディレクトリを返す."""
    channels_root = workspace_root / "channels"
    if not channels_root.is_dir():
        return {}
    return {
        path.name: path
        for path in sorted(channels_root.iterdir(), key=lambda candidate: candidate.name)
        if path.is_dir() and (path / "config" / "channel").is_dir()
    }


def find_workspace_root(start: Path | None = None) -> Path | None:
    """start から祖先を遡り、最初の multi-channel workspace を返す."""
    current = (start or Path.cwd()).expanduser().resolve()
    for parent in [current, *current.parents]:
        if workspace_channels(parent):
            return parent
    return None


def select_channel(slug: str | None) -> None:
    """CLI の明示的な ``--channel`` 選択を初回 config 解決へ渡す."""
    global _explicit_channel, _instance, _channel_dir
    if _instance is not None or _channel_dir is not None:
        raise ConfigError("チャンネル設定の解決後に --channel を変更することはできません")
    if slug is not None and not slug.strip():
        raise ConfigError("--channel には空でない channel slug を指定してください")
    _explicit_channel = slug


def _find_channel_ancestor(start: Path) -> Path | None:
    current = start.expanduser().resolve()
    for parent in [current, *current.parents]:
        if (parent / "config" / "channel").is_dir():
            return parent
    return None


def _resolve_slug(slug: str, workspace_root: Path | None, *, source: str) -> Path:
    if workspace_root is None:
        raise ConfigError(f"{source}={slug!r} を解決できる workspace が見つかりません")
    candidates = workspace_channels(workspace_root)
    if slug not in candidates:
        available = ", ".join(candidates) or "(なし)"
        raise ConfigError(
            f"{source}={slug!r} に対応するチャンネルが見つかりません: {workspace_root / 'channels'}. 候補: {available}"
        )
    return candidates[slug]


def _resolve_channel_dir() -> Path:
    """設定ルートを ``--channel`` → env → cwd の優先順で安全に解決する."""
    cwd = Path.cwd()
    cwd_channel = _find_channel_ancestor(cwd)
    env_dir_raw = os.environ.get("CHANNEL_DIR")
    env_dir = Path(env_dir_raw).expanduser() if env_dir_raw else None
    workspace_root = find_workspace_root(cwd)
    if workspace_root is None and env_dir is not None:
        workspace_root = find_workspace_root(env_dir)

    env_slug = os.environ.get("CHANNEL")
    validate_env_channel = _explicit_channel is None or env_dir is not None
    env_channel = (
        _resolve_slug(env_slug, workspace_root, source="CHANNEL") if env_slug and validate_env_channel else None
    )
    if env_channel is not None and env_dir is not None and env_channel.resolve() != env_dir.resolve():
        raise ConfigError(
            "CHANNEL と CHANNEL_DIR が異なるチャンネルを指しています: "
            f"CHANNEL={env_slug!r} -> {env_channel.resolve()}, CHANNEL_DIR={env_dir_raw!r} -> {env_dir.resolve()}"
        )

    if _explicit_channel is not None:
        explicit_channel = _resolve_slug(_explicit_channel, workspace_root, source="--channel")
        if cwd_channel is not None and cwd_channel.resolve() != explicit_channel.resolve():
            logger.warning(
                "--channel=%s (%s) を採用します。cwd は別チャンネル %s を指しています",
                _explicit_channel,
                explicit_channel,
                cwd_channel,
            )
        return explicit_channel
    if env_channel is not None:
        return env_channel
    if env_dir is not None:
        return env_dir
    if cwd_channel is not None:
        return cwd_channel
    if workspace_root is not None:
        available = ", ".join(workspace_channels(workspace_root))
        raise ConfigError(
            f"workspace ルートでは --channel <slug> または CHANNEL=<slug> を指定してください. 候補: {available}"
        )
    raise ConfigError("CHANNEL_DIR 環境変数を設定するか、config/channel/ を持つディレクトリ配下で実行してください")


def channel_dir() -> Path:
    """`config/channel/` を含むプロジェクトルートを返す（シングルトン解決）."""
    global _channel_dir
    if _channel_dir is None:
        _channel_dir = _resolve_channel_dir()
    return _channel_dir


def reset(*, preserve_channel_selection: bool = False) -> None:
    """シングルトン state をリセットし、必要なら CLI の明示選択を保持する."""
    global _explicit_channel, _instance, _channel_dir
    _instance = None
    _channel_dir = None
    if not preserve_channel_selection:
        _explicit_channel = None


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
            "/channel-new の既存チャンネル取り込みモードで "
            "config/channel/*.json を再生成してください"
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
    community_draft = _build_community_draft(merged)
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
        community_draft=community_draft,
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
    av_style = str(av_raw.get("style", "bar"))
    valid_av_styles = ("bar", "mirror-mountain", "ring", "ring-line", "heart")
    if av_style not in valid_av_styles:
        raise ConfigError(
            f"overlays.audio_visualizer.style='{av_style}' は不正です（有効値: {', '.join(valid_av_styles)}）"
        )
    try:
        av_bars = int(av_raw.get("bars", 16))
    except (TypeError, ValueError) as exc:
        raise ConfigError("overlays.audio_visualizer.bars は整数でなければなりません") from exc
    if av_bars <= 0:
        raise ConfigError("overlays.audio_visualizer.bars は 1 以上でなければなりません")
    av_ring_raw = av_raw.get("ring") or {}
    if not isinstance(av_ring_raw, dict):
        raise ConfigError(
            f"overlays.audio_visualizer.ring は object でなければなりません（got {type(av_ring_raw).__name__}）"
        )
    av_arc_raw = av_ring_raw.get("arc_deg", [0, 360])
    if not isinstance(av_arc_raw, (list, tuple)) or len(av_arc_raw) != 2:
        raise ConfigError("overlays.audio_visualizer.ring.arc_deg は [start, end] の 2 要素配列でなければなりません")
    try:
        av_ring = OverlayAudioVisualizerRing(
            inner_r=int(av_ring_raw.get("inner_r", 120)),
            length=int(av_ring_raw.get("length", 160)),
            arc_deg=(float(av_arc_raw[0]), float(av_arc_raw[1])),
        )
    except (TypeError, ValueError) as exc:
        raise ConfigError("overlays.audio_visualizer.ring の値は数値でなければなりません") from exc
    if av_ring.inner_r < 0 or av_ring.length <= 0:
        raise ConfigError("overlays.audio_visualizer.ring の inner_r は 0 以上、length は 1 以上でなければなりません")
    if not 0 <= av_ring.arc_deg[0] < av_ring.arc_deg[1] <= 360:
        raise ConfigError("overlays.audio_visualizer.ring.arc_deg は 0 <= start < end <= 360 でなければなりません")

    fill_raw = av_raw.get("fill")
    if fill_raw is not None and not isinstance(fill_raw, dict):
        raise ConfigError("overlays.audio_visualizer.fill は object でなければなりません")
    fill = None
    if fill_raw is not None:
        fill_type = str(fill_raw.get("type", "solid"))
        if fill_type not in {"solid", "gradient", "rainbow", "conical"}:
            raise ConfigError(
                "overlays.audio_visualizer.fill.type は solid / gradient / rainbow / conical のいずれかです"
            )
        fill_color = str(fill_raw.get("color", av_raw.get("colors", "white")))
        fill_top = str(fill_raw.get("top", "0xA9CBF0"))
        fill_bottom = str(fill_raw.get("bottom", fill_raw.get("bot", "0x3A5696")))
        try:
            if fill_type == "solid":
                normalize_ffmpeg_color(fill_color)
            elif fill_type == "gradient":
                parse_color(fill_top)
                parse_color(fill_bottom)
        except ValueError as exc:
            raise ConfigError(f"overlays.audio_visualizer.fill の色指定が不正です: {exc}") from exc
        fill = AudioVisualizerFill(
            type=fill_type,
            color=fill_color,
            top=fill_top,
            bottom=fill_bottom,
        )

    rounding_raw = av_raw.get("rounding")
    if rounding_raw is not None and not isinstance(rounding_raw, dict):
        raise ConfigError("overlays.audio_visualizer.rounding は object でなければなりません")
    rounding = (
        AudioVisualizerRounding(
            blur=float(rounding_raw.get("blur", 2.3)),
            contrast=float(rounding_raw.get("contrast", 3.2)),
        )
        if rounding_raw is not None
        else None
    )
    if rounding is not None and (rounding.blur < 0 or rounding.contrast <= 0):
        raise ConfigError("overlays.audio_visualizer.rounding の blur は 0 以上、contrast は 0 より大きい値です")

    glow_raw = av_raw.get("glow")
    if glow_raw is not None and not isinstance(glow_raw, dict):
        raise ConfigError("overlays.audio_visualizer.glow は object でなければなりません")
    glow = (
        AudioVisualizerGlow(
            enabled=bool(glow_raw.get("enabled", True)),
            sigma=float(glow_raw.get("sigma", av_raw.get("glow_sigma", 12.0))),
            opacity=float(glow_raw.get("opacity", av_raw.get("glow_opacity", 0.45))),
        )
        if glow_raw is not None
        else None
    )
    if glow is not None and (glow.sigma < 0 or not 0 <= glow.opacity <= 1):
        raise ConfigError("overlays.audio_visualizer.glow の sigma は 0 以上、opacity は 0〜1 の値です")
    audio_visualizer = OverlayAudioVisualizer(
        enabled=bool(av_raw.get("enabled", False)),
        style=av_style,
        bars=av_bars,
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
        ring=av_ring,
        fill=fill,
        mirror_center=bool(av_raw.get("mirror_center", False)),
        symmetric_vertical=bool(av_raw.get("symmetric_vertical", False)),
        rounding=rounding,
        glow=glow,
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

    skip_audio = _resolve_skip_approval(wf_next_raw, gates_raw, "skip_audio_approval", "audio")
    skip_upload = _resolve_skip_approval(wf_next_raw, gates_raw, "skip_upload_approval", "upload")

    post_publish_configured = "post-publish" in wf
    post_publish_raw = wf.get("post-publish", {})
    if not isinstance(post_publish_raw, dict):
        raise ConfigError(
            f"workflow.post-publish は object でなければなりません（got {type(post_publish_raw).__name__}）"
        )
    unexpected = set(post_publish_raw) - {"approval_gates"}
    if unexpected:
        names = ", ".join(sorted(unexpected))
        raise ConfigError(f"workflow.post-publish に未知のキーがあります: {names}")
    post_publish_gates_raw = post_publish_raw.get("approval_gates", {})
    if not isinstance(post_publish_gates_raw, dict):
        raise ConfigError(
            "workflow.post-publish.approval_gates は object でなければなりません"
            f"（got {type(post_publish_gates_raw).__name__}）"
        )
    post_publish_steps = {"community-post", "pinned-comment", "metadata-audit"}
    unknown_steps = set(post_publish_gates_raw) - post_publish_steps
    if unknown_steps:
        names = ", ".join(sorted(unknown_steps))
        raise ConfigError(f"workflow.post-publish.approval_gates に未知の step があります: {names}")

    return Workflow(
        wf_next=WfNext(
            approval_gates=ApprovalGates(audio=not skip_audio, upload=not skip_upload),
            skip_audio_approval=skip_audio,
            skip_upload_approval=skip_upload,
            skip_manual_mastering=_workflow_bool(
                wf_next_raw,
                "skip_manual_mastering",
                "workflow.wf_next.skip_manual_mastering",
            ),
        ),
        post_publish=PostPublish(
            configured=post_publish_configured,
            approval_gates=PostPublishApprovalGates(
                community_post=_workflow_bool(
                    post_publish_gates_raw,
                    "community-post",
                    "workflow.post-publish.approval_gates.community-post",
                ),
                pinned_comment=_workflow_bool(
                    post_publish_gates_raw,
                    "pinned-comment",
                    "workflow.post-publish.approval_gates.pinned-comment",
                ),
                metadata_audit=_workflow_bool(
                    post_publish_gates_raw,
                    "metadata-audit",
                    "workflow.post-publish.approval_gates.metadata-audit",
                ),
            ),
        ),
        scheduled_automation=_build_scheduled_automation(wf),
    )


def _build_scheduled_automation(wf: dict) -> ScheduledAutomation:
    """`workflow.scheduled_automation`（optional）を組み立てる（#1892）.

    未設定なら全 default（`enabled = False`）で、既存チャンネルの挙動を変えない。
    指定された値は falsy を default に潰さず strict に検証する（#1449 と同方針）。
    """
    if "scheduled_automation" not in wf:
        return ScheduledAutomation()
    raw = wf["scheduled_automation"]
    if not isinstance(raw, dict):
        raise ConfigError(f"workflow.scheduled_automation は object でなければなりません（got {type(raw).__name__}）")

    prefix = "workflow.scheduled_automation"
    defaults = ScheduledAutomation()
    return ScheduledAutomation(
        enabled=_scheduled_bool(raw, "enabled", prefix, defaults.enabled),
        timezone=_scheduled_str(raw, "timezone", prefix, defaults.timezone),
        run_time=_scheduled_run_time(raw, prefix, defaults.run_time),
        cadence=_scheduled_cadence(raw, prefix, defaults.cadence),
        target_workflow=_scheduled_str(raw, "target_workflow", prefix, defaults.target_workflow),
        max_retries=_scheduled_int(raw, "max_retries", prefix, defaults.max_retries),
        retry_delay_seconds=_scheduled_int(raw, "retry_delay_seconds", prefix, defaults.retry_delay_seconds),
        prevent_concurrent_runs=_scheduled_bool(
            raw, "prevent_concurrent_runs", prefix, defaults.prevent_concurrent_runs
        ),
        notification=_scheduled_notification(raw, prefix, defaults.notification),
        allow_external_publish=_scheduled_bool(raw, "allow_external_publish", prefix, defaults.allow_external_publish),
    )


def _scheduled_bool(raw: dict, key: str, prefix: str, default: bool) -> bool:
    if key not in raw:
        return default
    value = raw[key]
    if not isinstance(value, bool):
        raise ConfigError(f"{prefix}.{key} は boolean でなければなりません（got {type(value).__name__}）")
    return value


def _scheduled_int(raw: dict, key: str, prefix: str, default: int) -> int:
    if key not in raw:
        return default
    value = raw[key]
    # bool は int の subclass のため明示的に弾く
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{prefix}.{key} は integer でなければなりません（got {type(value).__name__}）")
    if value < 0:
        raise ConfigError(f"{prefix}.{key} は 0 以上でなければなりません（got {value}）")
    return value


def _scheduled_str(raw: dict, key: str, prefix: str, default: str) -> str:
    if key not in raw:
        return default
    value = raw[key]
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{prefix}.{key} は空でない string でなければなりません（got {value!r}）")
    return value


def _scheduled_run_time(raw: dict, prefix: str, default: str) -> str:
    value = _scheduled_str(raw, "run_time", prefix, default)
    parts = value.split(":")
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        hour, minute = int(parts[0]), int(parts[1])
        if len(parts[0]) == 2 and len(parts[1]) == 2 and hour <= 23 and minute <= 59:
            return value
    raise ConfigError(f"{prefix}.run_time は HH:MM（24 時間表記）でなければなりません（got {value!r}）")


def _scheduled_cadence(raw: dict, prefix: str, default: tuple[str, ...]) -> tuple[str, ...]:
    if "cadence" not in raw:
        return default
    value = raw["cadence"]
    if not isinstance(value, list) or not value:
        raise ConfigError(f"{prefix}.cadence は空でない曜日の array でなければなりません（got {value!r}）")
    seen: list[str] = []
    for day in value:
        if not isinstance(day, str) or day not in SCHEDULED_AUTOMATION_CADENCE_DAYS:
            raise ConfigError(
                f"{prefix}.cadence の要素は {list(SCHEDULED_AUTOMATION_CADENCE_DAYS)} の"
                f"いずれかでなければなりません（got {day!r}）"
            )
        if day in seen:
            raise ConfigError(f"{prefix}.cadence に重複した曜日があります（{day!r}）")
        seen.append(day)
    return tuple(seen)


def _scheduled_notification(raw: dict, prefix: str, default: str) -> str:
    value = _scheduled_str(raw, "notification", prefix, default)
    if value not in SCHEDULED_AUTOMATION_NOTIFICATIONS:
        raise ConfigError(
            f"{prefix}.notification は {list(SCHEDULED_AUTOMATION_NOTIFICATIONS)} の"
            f"いずれかでなければなりません（got {value!r}）"
        )
    return value


def _resolve_skip_approval(wf_next_raw: dict, gates_raw: dict, new_key: str, legacy_key: str) -> bool:
    """`skip_*_approval`（正キー、true=承認省略）と旧 `approval_gates.*`（true=承認する）を解決する.

    同一ゲートに新旧キーを同時指定した場合は、silent な優先解決で片方を潰さず
    `ConfigError` にする（#1744。falsy を default に潰さない #1449 と同じ strict 方針）。
    どちらも未指定なら従来既定（承認ゲートなし = skip True）。
    """
    new_specified = new_key in wf_next_raw
    legacy_specified = legacy_key in gates_raw
    if new_specified and legacy_specified:
        raise ConfigError(
            f"workflow.wf_next.{new_key} と workflow.wf_next.approval_gates.{legacy_key} は"
            "同時指定できません（新キー skip_* 側へ移行してください）"
        )
    if new_specified:
        return _workflow_bool(wf_next_raw, new_key, f"workflow.wf_next.{new_key}")
    if legacy_specified:
        return not _workflow_bool(gates_raw, legacy_key, f"workflow.wf_next.approval_gates.{legacy_key}")
    return True


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


def _build_community_draft(merged: dict) -> CommunityDraft:
    raw = merged.get("community_draft")
    if raw is None:
        return CommunityDraft()
    if not isinstance(raw, dict):
        raise ConfigError("community_draft セクションは object でなければなりません")

    variables_raw = raw.get("variables", {})
    if not isinstance(variables_raw, dict) or any(
        not isinstance(key, str) or not isinstance(value, str) for key, value in variables_raw.items()
    ):
        raise ConfigError("community_draft.variables は string 値の object でなければなりません")

    posts_raw = raw.get("posts")
    if not isinstance(posts_raw, list) or not posts_raw:
        raise ConfigError("community_draft.posts は空でない array でなければなりません")

    required_fields = {"label", "template", "schedule_offset_days", "schedule_time", "image"}
    posts: list[CommunityDraftPost] = []
    for index, post_raw in enumerate(posts_raw):
        prefix = f"community_draft.posts[{index}]"
        if not isinstance(post_raw, dict):
            raise ConfigError(f"{prefix} は object でなければなりません")
        missing = required_fields - post_raw.keys()
        unexpected = post_raw.keys() - required_fields
        if missing:
            raise ConfigError(f"{prefix} に必須キーがありません: {', '.join(sorted(missing))}")
        if unexpected:
            raise ConfigError(f"{prefix} に未知のキーがあります: {', '.join(sorted(unexpected))}")
        if not all(isinstance(post_raw[key], str) for key in ("label", "template", "schedule_time", "image")):
            raise ConfigError(f"{prefix} の label/template/schedule_time/image は string でなければなりません")
        posts.append(
            CommunityDraftPost(
                label=post_raw["label"],
                template=post_raw["template"],
                schedule_offset_days=post_raw["schedule_offset_days"],
                schedule_time=post_raw["schedule_time"],
                image=post_raw["image"],
            )
        )

    return CommunityDraft(variables=dict(variables_raw), posts=tuple(posts))


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
