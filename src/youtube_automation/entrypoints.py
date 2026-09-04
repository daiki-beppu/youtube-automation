"""Console script entry point wrappers for ``yt-*`` commands."""

from __future__ import annotations

import sys
from collections.abc import Callable
from importlib import import_module
from typing import cast

from youtube_automation.cli_stdio import configure_utf8_stdio

_CHANNEL_OPTION_CONFLICTS = {
    "youtube_automation.commands.channel.channel",
    "youtube_automation.commands.channel.channel_export",
    "youtube_automation.commands.channel.channel_import",
    "youtube_automation.commands.channel.workspace_status",
    "youtube_automation.commands.analytics.benchmark_collector",
    "youtube_automation.commands.analytics.fetch_benchmark_comments",
    "youtube_automation.commands.analytics.video_analyze",
    "youtube_automation.commands.system.codex_canary_notify",
    "youtube_automation.commands.system.channels",
    "youtube_automation.commands.thumbnail.compare_thumbnails",
}


def _consume_channel_option(argv: list[str]) -> str | None:
    """共通 ``--channel`` を argv から除去し、指定 slug を返す."""
    slug: str | None = None
    index = 1
    while index < len(argv):
        argument = argv[index]
        if argument == "--":
            break
        if argument == "--channel":
            if index + 1 >= len(argv) or argv[index + 1].startswith("-"):
                from youtube_automation.core.errors import ConfigError

                raise ConfigError("--channel には channel slug が必要です")
            value = argv[index + 1]
            del argv[index : index + 2]
        elif argument.startswith("--channel="):
            value = argument.partition("=")[2]
            del argv[index]
        else:
            index += 1
            continue
        if not value:
            from youtube_automation.core.errors import ConfigError

            raise ConfigError("--channel には空でない channel slug を指定してください")
        if slug is not None:
            from youtube_automation.core.errors import ConfigError

            raise ConfigError("--channel は複数回指定できません")
        slug = value
    return slug


def _run(module_path: str, function_name: str = "main") -> object:
    """Configure CLI stdio before importing and running the real command."""

    configure_utf8_stdio()
    if module_path not in _CHANNEL_OPTION_CONFLICTS:
        channel = _consume_channel_option(sys.argv)
        if channel is not None:
            from youtube_automation.configuration import select_channel

            select_channel(channel)
    target = getattr(import_module(module_path), function_name)
    if not callable(target):
        raise TypeError(f"{module_path}:{function_name} is not callable")
    return cast(Callable[[], object], target)()


def _make_entrypoint(module_path: str, function_name: str = "main") -> Callable[[], object]:
    def entrypoint() -> object:
        return _run(module_path, function_name)

    return entrypoint


yt_analytics = _make_entrypoint("youtube_automation.commands.analytics.analytics_system")
yt_ad_coverage = _make_entrypoint("youtube_automation.commands.analytics.ad_coverage")
yt_audio_visualizer_fill = _make_entrypoint("youtube_automation.commands.media.audio_visualizer_fill")
yt_audio_studio = _make_entrypoint("youtube_automation.commands.media.audio_studio")
yt_apply_rain_layers = _make_entrypoint("youtube_automation.commands.media.apply_rain_layers")
yt_automation_update = _make_entrypoint("youtube_automation.commands.system.automation_update")
yt_benchmark_collect = _make_entrypoint("youtube_automation.commands.analytics.benchmark_collector")
yt_benchmark_comments = _make_entrypoint("youtube_automation.commands.analytics.fetch_benchmark_comments")
yt_bulk_update_desc = _make_entrypoint("youtube_automation.commands.metadata.bulk_update_descriptions")
yt_bulk_update_synthetic_media = _make_entrypoint("youtube_automation.commands.metadata.bulk_update_synthetic_media")
yt_captions_upload = _make_entrypoint("youtube_automation.commands.youtube.captions_upload")
yt_channel = _make_entrypoint("youtube_automation.commands.channel.channel")
yt_channel_export = _make_entrypoint("youtube_automation.commands.channel.channel_export")
yt_channel_import = _make_entrypoint("youtube_automation.commands.channel.channel_import")
yt_channel_init = _make_entrypoint("youtube_automation.commands.channel.channel_init")
yt_channel_seed = _make_entrypoint("youtube_automation.commands.channel.channel_seed")
yt_channel_settings = _make_entrypoint("youtube_automation.commands.channel.channel_settings")
yt_channel_status = _make_entrypoint("youtube_automation.commands.channel.channel_status")
yt_channels = _make_entrypoint("youtube_automation.commands.system.channels")
yt_session_start = _make_entrypoint("youtube_automation.commands.system.session_start")
yt_changelog_compile = _make_entrypoint("youtube_automation.commands.system.changelog_compile")
yt_workspace_status = _make_entrypoint("youtube_automation.commands.channel.workspace_status")
yt_workspace_guard = _make_entrypoint("youtube_automation.commands.channel.workspace_guard")
yt_workflow_state = _make_entrypoint("youtube_automation.commands.collections.workflow_state_cli")
yt_workflow_status = _make_entrypoint("youtube_automation.commands.collections.workflow_status")
yt_hybrid_runner = _make_entrypoint("youtube_automation.commands.system.hybrid_runner")
yt_human_tasks = _make_entrypoint("youtube_automation.commands.system.human_tasks")
yt_codex_canary_notify = _make_entrypoint("youtube_automation.commands.system.codex_canary_notify")
yt_post_publish_state = _make_entrypoint("youtube_automation.commands.system.post_publish_state")
yt_media_acceptance = _make_entrypoint("youtube_automation.commands.media.media_acceptance")
yt_channel_trend = _make_entrypoint("youtube_automation.commands.analytics.channel_trend")
yt_collection_preflight = _make_entrypoint("youtube_automation.commands.collections.collection_preflight")
yt_collection_serve = _make_entrypoint("youtube_automation.commands.collections.collection_serve")
yt_comments_reply = _make_entrypoint("youtube_automation.commands.youtube.comment_reply")
yt_cost_report = _make_entrypoint("youtube_automation.commands.analytics.cost_report")
yt_discover_competitors = _make_entrypoint("youtube_automation.commands.analytics.discover_competitors")
yt_dashboard = _make_entrypoint("youtube_automation.commands.analytics.dashboard")
yt_distrokid_prepare = _make_entrypoint("youtube_automation.commands.distrokid.distrokid_prepare")
yt_document_migrate = _make_entrypoint("youtube_automation.commands.documents.migrate")
yt_document_review = _make_entrypoint("youtube_automation.commands.documents.review")
yt_collection_plan_select = _make_entrypoint("youtube_automation.commands.documents.collection_plan_select")
yt_music_prompt_select = _make_entrypoint("youtube_automation.commands.documents.music_prompt_select")
yt_master_audio_review = _make_entrypoint("youtube_automation.commands.media.master_audio_review")
yt_master_adjust = _make_entrypoint("youtube_automation.commands.media.master_adjust")
yt_master_video_review = _make_entrypoint("youtube_automation.commands.media.master_video_review")
yt_document_render = _make_entrypoint("youtube_automation.commands.documents.render")
yt_doctor = _make_entrypoint("youtube_automation.commands.system.doctor")
yt_fetch_stream_key = _make_entrypoint("youtube_automation.commands.youtube.fetch_stream_key")
yt_finalize_master = _make_entrypoint("youtube_automation.commands.media.finalize_master")
yt_generate_image = _make_entrypoint("youtube_automation.commands.media.generate_image")
yt_generate_loop_video = _make_entrypoint("youtube_automation.commands.media.generate_loop_video")
yt_generate_lyria_master = _make_entrypoint("youtube_automation.commands.media.generate_lyria_master")
yt_generate_minimax_master = _make_entrypoint("youtube_automation.commands.media.generate_minimax_master")
yt_generate_master = _make_entrypoint("youtube_automation.commands.media.generate_master")
yt_generate_videos_batch = _make_entrypoint("youtube_automation.commands.media.generate_videos_batch")
yt_generate_suno = _make_entrypoint("youtube_automation.commands.suno.generate_suno_prompts")
yt_init_collection = _make_entrypoint("youtube_automation.commands.collections.init_collection")
yt_kpi_dashboard = _make_entrypoint("youtube_automation.commands.analytics.kpi_dashboard")
yt_launch_curve = _make_entrypoint("youtube_automation.commands.analytics.launch_curve")
yt_live_chat_reply = _make_entrypoint("youtube_automation.commands.youtube.live_chat_reply")
yt_metadata_audit = _make_entrypoint("youtube_automation.commands.metadata.metadata_audit")
yt_oauth = _make_entrypoint("youtube_automation.commands.system.oauth")
yt_pinned_comment = _make_entrypoint("youtube_automation.commands.youtube.pinned_comment")
yt_playlist_manager = _make_entrypoint("youtube_automation.commands.youtube.playlist_manager")
yt_playlist_status = _make_entrypoint("youtube_automation.commands.youtube.playlist_status")
yt_postmortem_pending = _make_entrypoint("youtube_automation.commands.analytics.postmortem_pending")
yt_populate_scene_phrases = _make_entrypoint("youtube_automation.commands.media.populate_scene_phrases")
yt_preflight = _make_entrypoint("youtube_automation.commands.system.preflight")
yt_progress_hook = _make_entrypoint("youtube_automation.commands.system.progress_hook")
yt_raw_master_check = _make_entrypoint("youtube_automation.commands.media.check_raw_master")
yt_retention_timeline = _make_entrypoint("youtube_automation.commands.analytics.retention_timeline")
yt_stock_archive = _make_entrypoint("youtube_automation.commands.media.stock_archive")
yt_stock_list = _make_entrypoint("youtube_automation.commands.media.stock_list")
yt_stock_preview = _make_entrypoint("youtube_automation.commands.media.stock_preview")
yt_stock_prune = _make_entrypoint("youtube_automation.commands.media.stock_prune")
yt_suno_audio_cleanup = _make_entrypoint("youtube_automation.commands.suno.suno_audio_cleanup")
yt_suno_unattended_request = _make_entrypoint("youtube_automation.commands.suno.suno_unattended_request")
yt_suno_select_tracks = _make_entrypoint("youtube_automation.commands.suno.suno_select_tracks")
yt_suno_verify = _make_entrypoint("youtube_automation.commands.suno.suno_verify")
yt_suno_verify_playlist = _make_entrypoint("youtube_automation.commands.suno.suno_verify_playlist")
yt_stream_archive_check = _make_entrypoint("youtube_automation.commands.youtube.streaming_archive_check")
yt_stream_bandwidth = _make_entrypoint("youtube_automation.commands.youtube.stream_bandwidth")
yt_stream_broadcast_recover = _make_entrypoint("youtube_automation.commands.youtube.stream_broadcast_recover")
yt_theme_compare = _make_entrypoint("youtube_automation.commands.analytics.theme_compare")
yt_ttp_health = _make_entrypoint("youtube_automation.commands.analytics.ttp_health")
yt_thumbnail_auto_select = _make_entrypoint("youtube_automation.commands.thumbnail.auto_select_thumbnail")
yt_traffic_trend = _make_entrypoint("youtube_automation.commands.analytics.traffic_trend")
yt_thumbnail_check = _make_entrypoint("youtube_automation.commands.thumbnail.thumbnail_check")
yt_thumbnail_compare = _make_entrypoint("youtube_automation.commands.thumbnail.compare_thumbnails")
yt_thumbnail_correlate = _make_entrypoint("youtube_automation.commands.thumbnail.thumbnail_correlate")
yt_thumbnail_review = _make_entrypoint("youtube_automation.commands.thumbnail.thumbnail_review")
yt_thumbnail_text = _make_entrypoint("youtube_automation.commands.thumbnail.thumbnail_text")
yt_title_duplicate_check = _make_entrypoint("youtube_automation.commands.metadata.title_duplicate_check")
yt_video_analyze = _make_entrypoint("youtube_automation.commands.analytics.video_analyze")
yt_vpd_rank = _make_entrypoint("youtube_automation.commands.analytics.vpd_rank")
yt_win_pattern = _make_entrypoint("youtube_automation.commands.analytics.win_pattern")
yt_experiment = _make_entrypoint("youtube_automation.commands.analytics.experiment")
yt_vote_log = _make_entrypoint("youtube_automation.commands.collections.vote_log")
yt_wf_batch = _make_entrypoint("youtube_automation.commands.uploads.wf_batch")
yt_upload_auto = _make_entrypoint("youtube_automation.commands.uploads.youtube_auto_uploader")
yt_upload_collection = _make_entrypoint("youtube_automation.commands.uploads.collection_uploader")
yt_upload_shorts = _make_entrypoint("youtube_automation.commands.uploads.short_uploader")
yt_generate_shorts_loop = _make_entrypoint("youtube_automation.commands.media.generate_short_loop")
yt_shorts_bulk_update_loc = _make_entrypoint("youtube_automation.commands.metadata.bulk_update_short_localizations")
yt_skills = _make_entrypoint("youtube_automation.commands.system.skills_sync")
yt_setup_dirs = _make_entrypoint("youtube_automation.commands.system.setup_dirs")
