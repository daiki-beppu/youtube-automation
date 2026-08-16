"""CLI stdio bootstrap tests for Windows cp932 environments."""

from __future__ import annotations

import ast
import importlib
import io
import os
import sys
import tomllib
from pathlib import Path

import pytest

EXPECTED_ENTRYPOINT_MODULES = {
    "yt-ad-coverage": "youtube_automation.commands.analytics.ad_coverage",
    "yt-analytics": "youtube_automation.commands.analytics.analytics_system",
    "yt-apply-rain-layers": "youtube_automation.commands.media.apply_rain_layers",
    "yt-audio-visualizer-fill": "youtube_automation.commands.media.audio_visualizer_fill",
    "yt-automation-update": "youtube_automation.commands.system.automation_update",
    "yt-benchmark-collect": "youtube_automation.commands.analytics.benchmark_collector",
    "yt-benchmark-comments": "youtube_automation.commands.analytics.fetch_benchmark_comments",
    "yt-bulk-update-desc": "youtube_automation.commands.metadata.bulk_update_descriptions",
    "yt-bulk-update-synthetic-media": "youtube_automation.commands.metadata.bulk_update_synthetic_media",
    "yt-captions-upload": "youtube_automation.commands.youtube.captions_upload",
    "yt-channel": "youtube_automation.commands.channel.channel",
    "yt-channel-import": "youtube_automation.commands.channel.channel_import",
    "yt-channel-init": "youtube_automation.commands.channel.channel_init",
    "yt-channel-seed": "youtube_automation.commands.channel.channel_seed",
    "yt-channel-settings": "youtube_automation.commands.channel.channel_settings",
    "yt-channel-status": "youtube_automation.commands.channel.channel_status",
    "yt-workspace-status": "youtube_automation.commands.channel.workspace_status",
    "yt-workspace-guard": "youtube_automation.commands.channel.workspace_guard",
    "yt-workflow-state": "youtube_automation.commands.collections.workflow_state_cli",
    "yt-workflow-status": "youtube_automation.commands.collections.workflow_status",
    "yt-channel-trend": "youtube_automation.commands.analytics.channel_trend",
    "yt-collection-preflight": "youtube_automation.commands.collections.collection_preflight",
    "yt-collection-serve": "youtube_automation.commands.collections.collection_serve",
    "yt-comments-reply": "youtube_automation.commands.youtube.comment_reply",
    "yt-cost-report": "youtube_automation.commands.analytics.cost_report",
    "yt-discover-competitors": "youtube_automation.commands.analytics.discover_competitors",
    "yt-dashboard": "youtube_automation.commands.analytics.dashboard",
    "yt-distrokid-prepare": "youtube_automation.commands.distrokid.distrokid_prepare",
    "yt-document-migrate": "youtube_automation.commands.documents.migrate",
    "yt-document-review": "youtube_automation.commands.documents.review",
    "yt-collection-plan-select": "youtube_automation.commands.documents.collection_plan_select",
    "yt-music-prompt-select": "youtube_automation.commands.documents.music_prompt_select",
    "yt-master-audio-review": "youtube_automation.commands.media.master_audio_review",
    "yt-master-video-review": "youtube_automation.commands.media.master_video_review",
    "yt-document-render": "youtube_automation.commands.documents.render",
    "yt-doctor": "youtube_automation.commands.system.doctor",
    "yt-fetch-stream-key": "youtube_automation.commands.youtube.fetch_stream_key",
    "yt-finalize-master": "youtube_automation.commands.media.finalize_master",
    "yt-generate-image": "youtube_automation.commands.media.generate_image",
    "yt-generate-loop-video": "youtube_automation.commands.media.generate_loop_video",
    "yt-generate-lyria-master": "youtube_automation.commands.media.generate_lyria_master",
    "yt-generate-minimax-master": "youtube_automation.commands.media.generate_minimax_master",
    "yt-generate-master": "youtube_automation.commands.media.generate_master",
    "yt-generate-videos-batch": "youtube_automation.commands.media.generate_videos_batch",
    "yt-generate-suno": "youtube_automation.commands.suno.generate_suno_prompts",
    "yt-hybrid-runner": "youtube_automation.commands.system.hybrid_runner",
    "yt-human-tasks": "youtube_automation.commands.system.human_tasks",
    "yt-post-publish-state": "youtube_automation.commands.system.post_publish_state",
    "yt-media-acceptance": "youtube_automation.commands.media.media_acceptance",
    "yt-init-collection": "youtube_automation.commands.collections.init_collection",
    "yt-kpi-dashboard": "youtube_automation.commands.analytics.kpi_dashboard",
    "yt-launch-curve": "youtube_automation.commands.analytics.launch_curve",
    "yt-live-chat-reply": "youtube_automation.commands.youtube.live_chat_reply",
    "yt-metadata-audit": "youtube_automation.commands.metadata.metadata_audit",
    "yt-oauth": "youtube_automation.commands.system.oauth",
    "yt-pinned-comment": "youtube_automation.commands.youtube.pinned_comment",
    "yt-playlist-manager": "youtube_automation.commands.youtube.playlist_manager",
    "yt-playlist-status": "youtube_automation.commands.youtube.playlist_status",
    "yt-postmortem-pending": "youtube_automation.commands.analytics.postmortem_pending",
    "yt-populate-scene-phrases": "youtube_automation.commands.media.populate_scene_phrases",
    "yt-preflight": "youtube_automation.commands.system.preflight",
    "yt-progress-hook": "youtube_automation.commands.system.progress_hook",
    "yt-raw-master-check": "youtube_automation.commands.media.check_raw_master",
    "yt-retention-timeline": "youtube_automation.commands.analytics.retention_timeline",
    "yt-stock-archive": "youtube_automation.commands.media.stock_archive",
    "yt-stock-list": "youtube_automation.commands.media.stock_list",
    "yt-stock-preview": "youtube_automation.commands.media.stock_preview",
    "yt-stock-prune": "youtube_automation.commands.media.stock_prune",
    "yt-suno-audio-cleanup": "youtube_automation.commands.suno.suno_audio_cleanup",
    "yt-suno-unattended-request": "youtube_automation.commands.suno.suno_unattended_request",
    "yt-suno-select-tracks": "youtube_automation.commands.suno.suno_select_tracks",
    "yt-suno-verify": "youtube_automation.commands.suno.suno_verify",
    "yt-suno-verify-playlist": "youtube_automation.commands.suno.suno_verify_playlist",
    "yt-stream-archive-check": "youtube_automation.commands.youtube.streaming_archive_check",
    "yt-stream-bandwidth": "youtube_automation.commands.youtube.stream_bandwidth",
    "yt-stream-broadcast-recover": "youtube_automation.commands.youtube.stream_broadcast_recover",
    "yt-theme-compare": "youtube_automation.commands.analytics.theme_compare",
    "yt-ttp-health": "youtube_automation.commands.analytics.ttp_health",
    "yt-thumbnail-auto-select": "youtube_automation.commands.thumbnail.auto_select_thumbnail",
    "yt-thumbnail-check": "youtube_automation.commands.thumbnail.thumbnail_check",
    "yt-thumbnail-compare": "youtube_automation.commands.thumbnail.compare_thumbnails",
    "yt-thumbnail-correlate": "youtube_automation.commands.thumbnail.thumbnail_correlate",
    "yt-thumbnail-review": "youtube_automation.commands.thumbnail.thumbnail_review",
    "yt-thumbnail-text": "youtube_automation.commands.thumbnail.thumbnail_text",
    "yt-title-duplicate-check": "youtube_automation.commands.metadata.title_duplicate_check",
    "yt-traffic-trend": "youtube_automation.commands.analytics.traffic_trend",
    "yt-video-analyze": "youtube_automation.commands.analytics.video_analyze",
    "yt-vpd-rank": "youtube_automation.commands.analytics.vpd_rank",
    "yt-win-pattern": "youtube_automation.commands.analytics.win_pattern",
    "yt-experiment": "youtube_automation.commands.analytics.experiment",
    "yt-vote-log": "youtube_automation.commands.collections.vote_log",
    "yt-wf-batch": "youtube_automation.commands.uploads.wf_batch",
    "yt-upload-auto": "youtube_automation.commands.uploads.youtube_auto_uploader",
    "yt-upload-collection": "youtube_automation.commands.uploads.collection_uploader",
    "yt-upload-shorts": "youtube_automation.commands.uploads.short_uploader",
    "yt-generate-shorts-loop": "youtube_automation.commands.media.generate_short_loop",
    "yt-shorts-bulk-update-loc": "youtube_automation.commands.metadata.bulk_update_short_localizations",
    "yt-skills": "youtube_automation.commands.system.skills_sync",
    "yt-setup-dirs": "youtube_automation.commands.system.setup_dirs",
}


def _cp932_stream() -> tuple[io.BytesIO, io.TextIOWrapper]:
    buffer = io.BytesIO()
    return buffer, io.TextIOWrapper(buffer, encoding="cp932", errors="strict")


def _drop_youtube_automation_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    for module_name in list(sys.modules):
        if module_name == "youtube_automation" or module_name.startswith("youtube_automation."):
            monkeypatch.delitem(sys.modules, module_name, raising=False)


def test_package_import_does_not_configure_stdio(monkeypatch):
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    _drop_youtube_automation_modules(monkeypatch)

    _, stdout = _cp932_stream()
    _, stderr = _cp932_stream()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    importlib.import_module("youtube_automation")

    assert "PYTHONUTF8" not in os.environ
    assert "PYTHONIOENCODING" not in os.environ
    assert sys.stdout.encoding.lower() == "cp932"
    assert sys.stderr.encoding.lower() == "cp932"


def test_cli_entrypoint_configures_utf8_before_importing_target(monkeypatch):
    from youtube_automation import entrypoints

    stdout_buffer, stdout = _cp932_stream()
    stderr_buffer, stderr = _cp932_stream()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    def fake_import_module(module_name: str) -> object:
        assert module_name == "dummy_cli_module"
        assert sys.stdout.encoding.lower().replace("_", "-") == "utf-8"
        assert sys.stderr.encoding.lower().replace("_", "-") == "utf-8"
        print("import 時出力 — 完了", file=sys.stdout)
        print("import 時エラー — 続行", file=sys.stderr)
        sys.stdout.flush()
        sys.stderr.flush()

        class TargetModule:
            @staticmethod
            def main() -> int:
                return 7

        return TargetModule()

    monkeypatch.setattr(entrypoints, "import_module", fake_import_module)

    assert entrypoints._run("dummy_cli_module") == 7

    assert stdout_buffer.getvalue().decode("utf-8") == "import 時出力 — 完了\n"
    assert stderr_buffer.getvalue().decode("utf-8") == "import 時エラー — 続行\n"


def test_cli_entrypoint_consumes_channel_before_importing_target(monkeypatch):
    from youtube_automation import entrypoints
    from youtube_automation.configuration import loader

    monkeypatch.setattr(sys, "argv", ["yt-dummy", "--channel", "alpha", "--dry-run"])

    def fake_import_module(_module_name: str) -> object:
        assert loader._explicit_channel == "alpha"
        assert sys.argv == ["yt-dummy", "--dry-run"]

        class TargetModule:
            @staticmethod
            def main() -> int:
                return 0

        return TargetModule()

    monkeypatch.setattr(entrypoints, "import_module", fake_import_module)

    assert entrypoints._run("dummy_cli_module") == 0


def test_cli_entrypoint_preserves_legacy_benchmark_channel_option(monkeypatch):
    from youtube_automation import entrypoints

    monkeypatch.setattr(sys, "argv", ["yt-benchmark-collect", "--channel", "competitor"])

    class TargetModule:
        @staticmethod
        def main() -> int:
            assert sys.argv == ["yt-benchmark-collect", "--channel", "competitor"]
            return 0

    monkeypatch.setattr(entrypoints, "import_module", lambda _module_name: TargetModule())

    assert entrypoints._run("youtube_automation.commands.analytics.benchmark_collector") == 0


def test_configure_utf8_stdio_reconfigures_cp932_stdin_stdout_and_stderr(monkeypatch):
    from youtube_automation.cli_stdio import configure_utf8_stdio

    _, stdin = _cp932_stream()
    stdout_buffer, stdout = _cp932_stream()
    stderr_buffer, stderr = _cp932_stream()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    configure_utf8_stdio()
    print("日本語パス C:\\音楽\\作業 — 完了", file=sys.stdout)
    print("エラー詳細 — 続行", file=sys.stderr)
    sys.stdout.flush()
    sys.stderr.flush()

    assert sys.stdin.encoding.lower().replace("_", "-") == "utf-8"
    assert sys.stdin.errors == "surrogateescape"
    assert sys.stdout.encoding.lower().replace("_", "-") == "utf-8"
    assert sys.stderr.encoding.lower().replace("_", "-") == "utf-8"
    assert stdout_buffer.getvalue().decode("utf-8") == "日本語パス C:\\音楽\\作業 — 完了\n"
    assert stderr_buffer.getvalue().decode("utf-8") == "エラー詳細 — 続行\n"


def test_configure_utf8_stdio_sets_child_python_defaults(monkeypatch):
    from youtube_automation.cli_stdio import configure_utf8_stdio

    monkeypatch.delenv("PYTHONUTF8", raising=False)
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)

    configure_utf8_stdio()

    assert os.environ["PYTHONUTF8"] == "1"
    assert os.environ["PYTHONIOENCODING"] == "utf-8"


def test_configure_utf8_stdio_preserves_existing_child_python_defaults(monkeypatch):
    from youtube_automation.cli_stdio import configure_utf8_stdio

    monkeypatch.setenv("PYTHONUTF8", "0")
    monkeypatch.setenv("PYTHONIOENCODING", "cp932")

    configure_utf8_stdio()

    assert os.environ["PYTHONUTF8"] == "0"
    assert os.environ["PYTHONIOENCODING"] == "cp932"


def test_configure_utf8_stdio_fails_fast_when_stdout_stays_non_utf8(monkeypatch):
    from youtube_automation.cli_stdio import configure_utf8_stdio

    class FailingStdout:
        encoding = "cp932"

        def reconfigure(self, *, encoding: str, errors: str) -> None:
            raise OSError("unsupported")

    monkeypatch.setattr(sys, "stdout", FailingStdout())

    with pytest.raises(RuntimeError, match="stdout"):
        configure_utf8_stdio()


def test_configure_utf8_stdio_fails_fast_when_stdin_stays_non_utf8(monkeypatch):
    from youtube_automation.cli_stdio import configure_utf8_stdio

    class FailingStdin:
        encoding = "cp932"

        def reconfigure(self, *, encoding: str, errors: str) -> None:
            raise OSError("unsupported")

    monkeypatch.setattr(sys, "stdin", FailingStdin())

    with pytest.raises(RuntimeError, match="stdin"):
        configure_utf8_stdio()


def test_configure_utf8_stdio_fails_fast_when_required_reconfigure_is_noop(monkeypatch):
    from youtube_automation.cli_stdio import configure_utf8_stdio

    class NoopStdout:
        encoding = "cp932"

        def reconfigure(self, *, encoding: str, errors: str) -> None:
            return None

    monkeypatch.setattr(sys, "stdout", NoopStdout())

    with pytest.raises(RuntimeError, match="stdout"):
        configure_utf8_stdio()


def test_configure_utf8_stdio_accepts_utf8_alias_without_reconfigure(monkeypatch):
    from youtube_automation.cli_stdio import configure_utf8_stdio

    class AliasStream:
        encoding = "UTF8"

    monkeypatch.setattr(sys, "stdin", AliasStream())
    monkeypatch.setattr(sys, "stdout", AliasStream())
    monkeypatch.setattr(sys, "stderr", AliasStream())

    configure_utf8_stdio()


def test_project_scripts_route_through_cli_entrypoint_wrappers():
    from youtube_automation import entrypoints

    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    scripts = pyproject["project"]["scripts"]

    assert scripts
    assert set(scripts) == set(EXPECTED_ENTRYPOINT_MODULES)
    for script_name, target in scripts.items():
        module_name, _, function_name = target.partition(":")
        assert script_name.startswith("yt-")
        assert module_name == "youtube_automation.entrypoints"
        assert function_name
        assert hasattr(entrypoints, function_name)


def test_entrypoint_wrappers_only_target_command_modules():
    """#2308: 全 wrapper の dispatch 先が `commands/<domain>` である。

    `EXPECTED_ENTRYPOINT_MODULES` を突き合わせるだけでは、期待表ごと実装層へ書き換えられた
    ときに素通りする。実 source の `_make_entrypoint(...)` リテラルを直接読み、
    `utils` / `infrastructure` / `domains` への直接 dispatch が 1 件も無いことを固定する。
    """
    source = Path("src/youtube_automation/entrypoints.py").read_text(encoding="utf-8")
    targets = [
        node.args[0].value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_make_entrypoint"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    ]

    assert len(targets) == len(EXPECTED_ENTRYPOINT_MODULES)
    assert [target for target in targets if not target.startswith("youtube_automation.commands.")] == []


def test_retired_config_migration_cli_is_not_registered():
    from youtube_automation import entrypoints

    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    retired_script = "yt-config" + "-migrate"
    retired_wrapper = "yt_config" + "_migrate"

    assert retired_script not in pyproject["project"]["scripts"]
    assert not hasattr(entrypoints, retired_wrapper)


@pytest.mark.parametrize(
    ("script_name", "expected_module_path"),
    sorted(EXPECTED_ENTRYPOINT_MODULES.items()),
)
def test_cli_entrypoint_wrapper_dispatches_to_command_module(monkeypatch, script_name, expected_module_path):
    from youtube_automation import entrypoints

    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    _, _, function_name = pyproject["project"]["scripts"][script_name].partition(":")
    calls: list[tuple[str, str]] = []

    def fake_run(module_path: str, function_name: str = "main") -> int:
        calls.append((module_path, function_name))
        return 42

    monkeypatch.setattr(entrypoints, "_run", fake_run)

    assert getattr(entrypoints, function_name)() == 42
    assert calls == [(expected_module_path, "main")]
