"""新規 command CLI に共通 harness 境界を強制する契約テスト。"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.helpers.paths import REPO_ROOT

COMMANDS_ROOT = REPO_ROOT / "src/youtube_automation/commands"
HARNESS_MODULE = "youtube_automation.commands._shared.cli_harness"
LEGACY_CLI_LIMIT = 70

# #3925 導入時点の未移行 CLI。既存互換のため凍結し、移行した module は削除する。
LEGACY_CLI_ALLOWLIST: frozenset[str] = frozenset(
    {
        "youtube_automation.commands.analytics.analytics_system",
        "youtube_automation.commands.analytics.benchmark_collector",
        "youtube_automation.commands.analytics.cost_report",
        "youtube_automation.commands.analytics.dashboard",
        "youtube_automation.commands.analytics.discover_competitors",
        "youtube_automation.commands.analytics.experiment",
        "youtube_automation.commands.analytics.fetch_benchmark_comments",
        "youtube_automation.commands.analytics.retention_timeline",
        "youtube_automation.commands.analytics.video_analyze",
        "youtube_automation.commands.analytics.vpd_rank",
        "youtube_automation.commands.analytics.win_pattern",
        "youtube_automation.commands.channel.channel_init",
        "youtube_automation.commands.channel.channel_seed",
        "youtube_automation.commands.channel.channel_settings",
        "youtube_automation.commands.channel.channel_status",
        "youtube_automation.commands.collections.collection_preflight",
        "youtube_automation.commands.collections.collection_serve",
        "youtube_automation.commands.collections.init_collection",
        "youtube_automation.commands.collections.vote_log",
        "youtube_automation.commands.distrokid.distrokid_prepare",
        "youtube_automation.commands.media.apply_rain_layers",
        "youtube_automation.commands.media.audio_visualizer_fill",
        "youtube_automation.commands.media.check_raw_master",
        "youtube_automation.commands.media.finalize_master",
        "youtube_automation.commands.media.generate_image",
        "youtube_automation.commands.media.generate_loop_video",
        "youtube_automation.commands.media.generate_lyria_master",
        "youtube_automation.commands.media.generate_master",
        "youtube_automation.commands.media.generate_short_loop",
        "youtube_automation.commands.media.generate_videos_batch",
        "youtube_automation.commands.media.populate_scene_phrases",
        "youtube_automation.commands.media.stock_archive",
        "youtube_automation.commands.media.stock_list",
        "youtube_automation.commands.media.stock_preview",
        "youtube_automation.commands.media.stock_prune",
        "youtube_automation.commands.metadata.bulk_update_descriptions",
        "youtube_automation.commands.metadata.bulk_update_short_localizations",
        "youtube_automation.commands.metadata.bulk_update_synthetic_media",
        "youtube_automation.commands.metadata.title_duplicate_check",
        "youtube_automation.commands.suno.generate_suno_prompts",
        "youtube_automation.commands.suno.suno_audio_cleanup",
        "youtube_automation.commands.suno.suno_select_tracks",
        "youtube_automation.commands.suno.suno_unattended_request",
        "youtube_automation.commands.suno.suno_verify",
        "youtube_automation.commands.suno.suno_verify_playlist",
        "youtube_automation.commands.system.automation_update",
        "youtube_automation.commands.system.doctor",
        "youtube_automation.commands.system.oauth",
        "youtube_automation.commands.system.preflight",
        "youtube_automation.commands.system.setup_dirs",
        "youtube_automation.commands.thumbnail.auto_select_thumbnail",
        "youtube_automation.commands.thumbnail.compare_thumbnails",
        "youtube_automation.commands.thumbnail.thumbnail_check",
        "youtube_automation.commands.thumbnail.thumbnail_correlate",
        "youtube_automation.commands.thumbnail.thumbnail_text",
        "youtube_automation.commands.uploads.wf_batch",
        "youtube_automation.commands.youtube.captions_upload",
        "youtube_automation.commands.youtube.comment_reply",
        "youtube_automation.commands.youtube.fetch_stream_key",
        "youtube_automation.commands.youtube.live_chat_reply",
        "youtube_automation.commands.youtube.pinned_comment",
        "youtube_automation.commands.youtube.playlist_manager",
        "youtube_automation.commands.youtube.playlist_status",
        "youtube_automation.commands.youtube.stream_bandwidth",
        "youtube_automation.commands.youtube.stream_broadcast_recover",
        "youtube_automation.commands.youtube.streaming_archive_check",
    }
)


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(REPO_ROOT / "src").with_suffix("").parts)


def _main_definition(tree: ast.Module) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    return next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main"
        ),
        None,
    )


def _has_harness_import(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == HARNESS_MODULE
        and any(alias.name == "run_cli" for alias in node.names)
        for node in tree.body
    )


def _calls_harness(main: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "run_cli"
        for node in ast.walk(main)
    )


def _main_signature_is_canonical(main: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    positional = [*main.args.posonlyargs, *main.args.args]
    return (
        len(positional) == 1
        and positional[0].arg == "argv"
        and positional[0].annotation is not None
        and ast.unparse(positional[0].annotation) == "list[str] | None"
        and len(main.args.defaults) == 1
        and isinstance(main.args.defaults[0], ast.Constant)
        and main.args.defaults[0].value is None
        and main.args.vararg is None
        and main.args.kwarg is None
        and not main.args.kwonlyargs
    )


def _cli_violations(path: Path) -> tuple[str, ...] | None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    main = _main_definition(tree)
    if main is None:
        return None

    violations: list[str] = []
    if not _has_harness_import(tree):
        violations.append("共通harnessのimportなし")
    if not _calls_harness(main):
        violations.append("mainがrun_cliを呼んでいない")
    if not _main_signature_is_canonical(main):
        violations.append("main(argv: list[str] | None = None)でない")
    if main.returns is None or ast.unparse(main.returns) != "int":
        violations.append("mainの戻り値注釈がintでない")
    return tuple(violations)


def _command_cli_violations() -> dict[str, tuple[str, ...]]:
    violations: dict[str, tuple[str, ...]] = {}
    for path in sorted(COMMANDS_ROOT.rglob("*.py")):
        # package entry point は command module と別契約。CLI 本体だけを追跡する。
        if path.name == "__init__.py":
            continue
        module_violations = _cli_violations(path)
        if module_violations:
            violations[_module_name(path)] = module_violations
    return violations


def test_new_command_clis_use_shared_harness_and_canonical_main() -> None:
    """allowlist 外の新規 CLI と、移行済みなのに残る例外を同時に検出する。"""
    assert len(LEGACY_CLI_ALLOWLIST) <= LEGACY_CLI_LIMIT, (
        f"legacy CLI allowlistを増やさないこと: {len(LEGACY_CLI_ALLOWLIST)} > {LEGACY_CLI_LIMIT}"
    )
    violations = _command_cli_violations()
    unexpected = {module: kinds for module, kinds in violations.items() if module not in LEGACY_CLI_ALLOWLIST}
    stale = sorted(LEGACY_CLI_ALLOWLIST - violations.keys())

    diagnostics = [
        *(f"{module}: {', '.join(kinds)}" for module, kinds in sorted(unexpected.items())),
        *(f"{module}: allowlistに残っているが全契約へ移行済み" for module in stale),
    ]
    assert not diagnostics, "CLI harness契約違反:\n  " + "\n  ".join(diagnostics)
