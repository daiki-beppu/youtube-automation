"""yt-channel-init が生成するファイル契約を集約する."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

CONFIG_DIR = Path("config")
CONFIG_SUBDIR = CONFIG_DIR / "channel"
SKILLS_SUBDIR = CONFIG_DIR / "skills"
GITKEEP_NAME = ".gitkeep"
PLACEHOLDER_DEFAULT = "TBD"
BENCHMARK_CHANNEL_SEPARATOR = "|"
DEFAULT_LOCALIZATION_LANGUAGES: tuple[str, ...] = ("ja", "en", "de")

SETUP_DIRECTORIES: tuple[str, ...] = (
    "auth",
    "collections",
    "data",
    "docs/channel/personas",
    "docs/benchmarks",
    "research",
)

DIRECTORIES: tuple[str, ...] = SETUP_DIRECTORIES


@dataclass(frozen=True)
class ChannelInitContext:
    """argparse から正規化したスキャフォールド入力."""

    short: str
    name: str
    genre: str
    style: str
    context: str
    core_message: str
    target_duration_min: float | None
    target_duration_max: float | None
    music_engine: str
    benchmark_channels: tuple[dict[str, str], ...]
    channel_keywords: tuple[str, ...]
    branding_description: str
    country: str
    default_language: str
    supported_languages: tuple[str, ...]


def serialize_json(data: dict) -> str:
    """`indent=2`, `ensure_ascii=False`, 末尾改行付きで JSON 化する."""
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _render_meta(ctx: ChannelInitContext) -> dict:
    return {
        "channel": {
            "name": ctx.name,
            "short": ctx.short,
            "youtube_handle": "",
            "url": "",
            "channel_id": "",
            "core_message": ctx.core_message,
            "cta_subscribe": f"Subscribe for new {ctx.genre} music!",
            "tagline": ctx.core_message,
        },
        "youtube_channel": {
            "description": ctx.branding_description,
            "keywords": list(ctx.channel_keywords),
            "country": ctx.country,
            "default_language": ctx.default_language,
            "unsubscribed_trailer": "",
            "made_for_kids": False,
        },
    }


def _render_content(ctx: ChannelInitContext) -> dict:
    return {
        "genre": {"primary": ctx.genre, "style": ctx.style, "context": ctx.context},
        "tags": {"base": [], "themes": {}},
        "descriptions": {
            "opening": f"{ctx.style} {ctx.genre} music inspired by {ctx.context}.",
            "sub_opening": f"Perfect for studying, relaxing, or immersing yourself in {ctx.context}.",
            "perfect_for": ["Study & Focus Sessions", "Background Music", "Creative Work", "Relaxation"],
            "hashtags": [],
        },
        "title": {
            "template": "{style} {theme} Music - {activity} BGM [{duration_display}]",
            "default_activity": "Study",
            "theme_scenes": {},
            "theme_activities": {},
        },
    }


def _render_youtube(ctx: ChannelInitContext) -> dict:
    return {
        "youtube": {
            "category_id": "10",
            "privacy_status": "public",
            "language": "en",
        },
        "content_model": {
            "type": "collection",
            "languages": list(ctx.supported_languages),
        },
        "music_engine": ctx.music_engine,
    }


def _render_analytics(ctx: ChannelInitContext) -> dict:
    return {
        "analytics": {"collection_filter_keywords": ["Complete Collection", ctx.short]},
        "benchmark": {
            "channels": list(ctx.benchmark_channels),
            "scan_recent": 50,
            "min_views": 10000,
            "freshness_days": 3,
            "gemini_thumbnail_analysis": False,
        },
    }


def _render_empty(_ctx: ChannelInitContext) -> dict:
    return {}


def _render_audio(ctx: ChannelInitContext) -> dict:
    return {
        "audio": {
            "target_duration_min": ctx.target_duration_min,
            "target_duration_max": ctx.target_duration_max,
            "chapter_max": 100,
        }
    }


CHANNEL_CONFIG_TEMPLATES: dict[str, Callable[[ChannelInitContext], dict]] = {
    "meta.json": _render_meta,
    "content.json": _render_content,
    "youtube.json": _render_youtube,
    "analytics.json": _render_analytics,
    "playlists.json": _render_empty,
    "workflow.json": _render_empty,
    "audio.json": _render_audio,
}


def _render_localizations(ctx: ChannelInitContext) -> dict:
    entries = {lang: {"title": ctx.name, "description": ctx.branding_description} for lang in ctx.supported_languages}
    language_templates = {lang: _render_language_template(lang, ctx) for lang in ctx.supported_languages}
    return {
        "supported_languages": list(ctx.supported_languages),
        "default_language": ctx.default_language,
        **entries,
        "languages": language_templates,
    }


def _template_literal(value: str) -> str:
    return value.replace("{", "{{").replace("}", "}}")


def _render_language_template(lang: str, ctx: ChannelInitContext) -> dict[str, str]:
    genre_label = _template_literal(ctx.genre)
    title_template = f"{{scene_phrase}} | {genre_label} BGM ({{activities}})"
    openings: dict[str, str] = {
        "ja": f"{ctx.style}の{ctx.genre}音楽。",
        "de": f"{ctx.style} {ctx.genre} Musik.",
    }
    return {
        "title_template": title_template,
        "description_opening": openings.get(lang, f"{ctx.style} {ctx.genre} music."),
    }


def _render_schedule(_ctx: ChannelInitContext) -> dict:
    return {
        "schedule": {
            "timezone": "Asia/Tokyo",
            "auto_schedule_enabled": True,
            "publish_time": "20:00",
            "cadence": ["tue", "thu", "sat"],
        },
        "upload_settings": {
            "privacy_status": "private",
            "category_id": "10",
            "auto_create_playlist": True,
            "max_retries": 3,
            "retry_delay_seconds": 300,
        },
        "collections_management": {
            "auto_move_to_live": True,
            "backup_before_move": False,
            "watch_ready_directory": True,
        },
        "notification_settings": {
            "discord_webhook_url": "",
            "email_notifications": False,
            "terminal_notifications": True,
        },
        "api_limits": {
            "upload_quota_per_day": 6,
            "uploads_per_batch": 5,
            "concurrent_uploads": 1,
            "delay_between_uploads": 5,
        },
    }


ROOT_JSON_TEMPLATES: dict[Path, Callable[[ChannelInitContext], dict]] = {
    CONFIG_DIR / "localizations.json": _render_localizations,
    CONFIG_DIR / "schedule_config.json": _render_schedule,
}


def _yaml_scalar(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _render_env(_ctx: ChannelInitContext) -> str:
    return "CHANNEL_DIR=.\nGOOGLE_CLOUD_PROJECT=\nVERTEX_LOCATION=us-central1\n"


def _render_gitignore(_ctx: ChannelInitContext) -> str:
    return "\n".join(
        [
            "# Local environment",
            ".env",
            ".direnv/",
            ".venv/",
            "",
            "# Python",
            "__pycache__/",
            "*.pyc",
            "",
            "# OAuth credentials",
            "auth/client_secrets.json",
            "auth/token*.json",
            "",
        ]
    )


def _render_auth_template(_ctx: ChannelInitContext) -> str:
    return serialize_json(
        {
            "installed": {
                "client_id": "",
                "project_id": "",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_secret": "",
                "redirect_uris": ["http://localhost"],
            }
        }
    )


def _render_suno_skill(ctx: ChannelInitContext) -> str:
    return (
        f"workspace_name: {_yaml_scalar(ctx.name)}\n"
        f"genre_line: {_yaml_scalar(f'{ctx.style} {ctx.genre} music for {ctx.context}')}\n"
        'exclude_styles: ""\n'
    )


def _render_thumbnail_skill(ctx: ChannelInitContext) -> str:
    return (
        "image_generation:\n"
        "  gemini:\n"
        '    brand_background: "TBD"\n'
        "    reference_images:\n"
        "      default: []\n"
        "      path_base: channel_dir\n"
        f"      notes: {_yaml_scalar(f'TTP benchmarks: {len(ctx.benchmark_channels)} channel(s)')}\n"
        '    diff_prompt_template: "Apply this channel visual direction to the collection theme."\n'
        "    composition_rules:\n"
        '      environment: "TBD"\n'
        '      character_size: "TBD"\n'
        '      character_pose: "TBD"\n'
        '      allowed_actions: "TBD"\n'
        '      ng_actions: "TBD"\n'
        '      background: "TBD"\n'
        '      text_lines: "タイトルは 2 行以内"\n'
        f"      channel_branding: {_yaml_scalar(ctx.name)}\n"
    )


ROOT_TEXT_TEMPLATES: dict[Path, Callable[[ChannelInitContext], str]] = {
    Path(".env"): _render_env,
    Path(".gitignore"): _render_gitignore,
    Path("auth") / "client_secrets.template.json": _render_auth_template,
    SKILLS_SUBDIR / "suno.yaml": _render_suno_skill,
    SKILLS_SUBDIR / "thumbnail.yaml": _render_thumbnail_skill,
}
