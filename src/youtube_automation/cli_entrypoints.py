"""Console script entry point wrappers for ``yt-*`` commands."""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from typing import cast

from youtube_automation.cli_stdio import configure_utf8_stdio


def _run(module_path: str, function_name: str = "main") -> object:
    """Configure CLI stdio before importing and running the real command."""

    configure_utf8_stdio()
    target = getattr(import_module(module_path), function_name)
    if not callable(target):
        raise TypeError(f"{module_path}:{function_name} is not callable")
    return cast(Callable[[], object], target)()


def _make_entrypoint(module_path: str, function_name: str = "main") -> Callable[[], object]:
    def entrypoint() -> object:
        return _run(module_path, function_name)

    return entrypoint


yt_analytics = _make_entrypoint("youtube_automation.scripts.analytics_system")
yt_apply_rain_layers = _make_entrypoint("youtube_automation.scripts.apply_rain_layers")
yt_automation_update = _make_entrypoint("youtube_automation.cli.automation_update")
yt_benchmark_collect = _make_entrypoint("youtube_automation.scripts.benchmark_collector")
yt_benchmark_comments = _make_entrypoint("youtube_automation.scripts.fetch_benchmark_comments")
yt_bulk_update_desc = _make_entrypoint("youtube_automation.scripts.bulk_update_descriptions_from_md")
yt_bulk_update_synthetic_media = _make_entrypoint("youtube_automation.scripts.bulk_update_synthetic_media")
yt_channel_init = _make_entrypoint("youtube_automation.cli.channel_init")
yt_channel_seed = _make_entrypoint("youtube_automation.scripts.channel_seed")
yt_channel_settings = _make_entrypoint("youtube_automation.scripts.channel_settings_cli")
yt_channel_status = _make_entrypoint("youtube_automation.scripts.get_channel_status")
yt_channel_trend = _make_entrypoint("youtube_automation.scripts.channel_trend")
yt_collection_preflight = _make_entrypoint("youtube_automation.scripts.collection_preflight")
yt_collection_serve = _make_entrypoint("youtube_automation.scripts.collection_serve")
yt_comments_reply = _make_entrypoint("youtube_automation.scripts.comment_reply")
yt_cost_report = _make_entrypoint("youtube_automation.cli.cost_report")
yt_discover_competitors = _make_entrypoint("youtube_automation.scripts.discover_competitors")
yt_distrokid_migrate = _make_entrypoint("youtube_automation.cli.distrokid_migrate")
yt_distrokid_prepare = _make_entrypoint("youtube_automation.scripts.distrokid_prepare")
yt_doctor = _make_entrypoint("youtube_automation.cli.doctor")
yt_fetch_stream_key = _make_entrypoint("youtube_automation.scripts.fetch_stream_key")
yt_finalize_master = _make_entrypoint("youtube_automation.scripts.finalize_master")
yt_generate_image = _make_entrypoint("youtube_automation.scripts.generate_image")
yt_generate_loop_video = _make_entrypoint("youtube_automation.scripts.generate_loop_video")
yt_generate_lyria_master = _make_entrypoint("youtube_automation.scripts.generate_lyria_master")
yt_generate_master = _make_entrypoint("youtube_automation.scripts.generate_master")
yt_generate_suno = _make_entrypoint("youtube_automation.scripts.generate_suno_prompts")
yt_init_collection = _make_entrypoint("youtube_automation.scripts.init_collection")
yt_launch_curve = _make_entrypoint("youtube_automation.scripts.launch_curve")
yt_metadata_audit = _make_entrypoint("youtube_automation.scripts.metadata_audit")
yt_pinned_comment = _make_entrypoint("youtube_automation.scripts.pinned_comment")
yt_playlist_manager = _make_entrypoint("youtube_automation.scripts.playlist_manager")
yt_playlist_status = _make_entrypoint("youtube_automation.scripts.playlist_status")
yt_populate_scene_phrases = _make_entrypoint("youtube_automation.scripts.populate_scene_phrases")
yt_stock_archive = _make_entrypoint("youtube_automation.scripts.stock_archive")
yt_stock_list = _make_entrypoint("youtube_automation.scripts.stock_list")
yt_stock_preview = _make_entrypoint("youtube_automation.scripts.stock_preview")
yt_stock_prune = _make_entrypoint("youtube_automation.scripts.stock_prune")
yt_suno_audio_cleanup = _make_entrypoint("youtube_automation.scripts.suno_audio_cleanup")
yt_suno_select_tracks = _make_entrypoint("youtube_automation.scripts.suno_select_tracks")
yt_suno_verify = _make_entrypoint("youtube_automation.scripts.suno_verify")
yt_suno_verify_playlist = _make_entrypoint("youtube_automation.scripts.suno_verify_playlist")
yt_stream_archive_check = _make_entrypoint("youtube_automation.scripts.streaming_archive_check")
yt_stream_bandwidth = _make_entrypoint("youtube_automation.cli.stream_bandwidth")
yt_theme_compare = _make_entrypoint("youtube_automation.scripts.theme_compare")
yt_thumbnail_auto_select = _make_entrypoint("youtube_automation.scripts.auto_select_thumbnail")
yt_thumbnail_check = _make_entrypoint("youtube_automation.scripts.thumbnail_check")
yt_thumbnail_compare = _make_entrypoint("youtube_automation.scripts.compare_thumbnails")
yt_thumbnail_correlate = _make_entrypoint("youtube_automation.scripts.thumbnail_correlate")
yt_thumbnail_text = _make_entrypoint("youtube_automation.scripts.thumbnail_text")
yt_title_duplicate_check = _make_entrypoint("youtube_automation.scripts.title_duplicate_check")
yt_video_analyze = _make_entrypoint("youtube_automation.scripts.video_analyze")
yt_vote_log = _make_entrypoint("youtube_automation.scripts.vote_log")
yt_upload_auto = _make_entrypoint("youtube_automation.agents.youtube_auto_uploader")
yt_upload_collection = _make_entrypoint("youtube_automation.agents.collection_uploader")
yt_upload_shorts = _make_entrypoint("youtube_automation.agents.short_uploader")
yt_generate_shorts_loop = _make_entrypoint("youtube_automation.scripts.generate_short_loop")
yt_shorts_bulk_update_loc = _make_entrypoint("youtube_automation.scripts.bulk_update_short_localizations")
yt_skills = _make_entrypoint("youtube_automation.cli.skills_sync")
yt_setup_dirs = _make_entrypoint("youtube_automation.cli.setup_dirs")
