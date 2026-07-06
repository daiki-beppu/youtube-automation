"""CLI stdio bootstrap tests for Windows cp932 environments."""

from __future__ import annotations

import importlib
import io
import os
import sys
import tomllib
from pathlib import Path

import pytest

EXPECTED_ENTRYPOINT_MODULES = {
    "yt-analytics": "youtube_automation.scripts.analytics_system",
    "yt-apply-rain-layers": "youtube_automation.scripts.apply_rain_layers",
    "yt-automation-update": "youtube_automation.cli.automation_update",
    "yt-benchmark-collect": "youtube_automation.scripts.benchmark_collector",
    "yt-benchmark-comments": "youtube_automation.scripts.fetch_benchmark_comments",
    "yt-bulk-update-desc": "youtube_automation.scripts.bulk_update_descriptions_from_md",
    "yt-bulk-update-synthetic-media": "youtube_automation.scripts.bulk_update_synthetic_media",
    "yt-channel-init": "youtube_automation.cli.channel_init",
    "yt-channel-seed": "youtube_automation.scripts.channel_seed",
    "yt-channel-settings": "youtube_automation.scripts.channel_settings_cli",
    "yt-channel-status": "youtube_automation.scripts.get_channel_status",
    "yt-channel-trend": "youtube_automation.scripts.channel_trend",
    "yt-collection-preflight": "youtube_automation.scripts.collection_preflight",
    "yt-collection-serve": "youtube_automation.scripts.collection_serve",
    "yt-comments-reply": "youtube_automation.scripts.comment_reply",
    "yt-config-migrate": "youtube_automation.cli.config_migrate",
    "yt-cost-report": "youtube_automation.cli.cost_report",
    "yt-discover-competitors": "youtube_automation.scripts.discover_competitors",
    "yt-distrokid-migrate": "youtube_automation.cli.distrokid_migrate",
    "yt-distrokid-prepare": "youtube_automation.scripts.distrokid_prepare",
    "yt-doctor": "youtube_automation.cli.doctor",
    "yt-fetch-stream-key": "youtube_automation.scripts.fetch_stream_key",
    "yt-finalize-master": "youtube_automation.scripts.finalize_master",
    "yt-fix-timestamps": "youtube_automation.scripts.fix_per_theme_timestamps",
    "yt-generate-image": "youtube_automation.scripts.generate_image",
    "yt-generate-loop-video": "youtube_automation.scripts.generate_loop_video",
    "yt-generate-lyria-master": "youtube_automation.scripts.generate_lyria_master",
    "yt-generate-master": "youtube_automation.scripts.generate_master",
    "yt-generate-suno": "youtube_automation.scripts.generate_suno_prompts",
    "yt-init-collection": "youtube_automation.scripts.init_collection",
    "yt-launch-curve": "youtube_automation.scripts.launch_curve",
    "yt-metadata-audit": "youtube_automation.scripts.metadata_audit",
    "yt-pinned-comment": "youtube_automation.scripts.pinned_comment",
    "yt-playlist-manager": "youtube_automation.scripts.playlist_manager",
    "yt-playlist-status": "youtube_automation.scripts.playlist_status",
    "yt-populate-scene-phrases": "youtube_automation.scripts.populate_scene_phrases",
    "yt-stock-archive": "youtube_automation.scripts.stock_archive",
    "yt-stock-list": "youtube_automation.scripts.stock_list",
    "yt-stock-preview": "youtube_automation.scripts.stock_preview",
    "yt-stock-prune": "youtube_automation.scripts.stock_prune",
    "yt-suno-audio-cleanup": "youtube_automation.scripts.suno_audio_cleanup",
    "yt-suno-select-tracks": "youtube_automation.scripts.suno_select_tracks",
    "yt-stream-archive-check": "youtube_automation.scripts.streaming_archive_check",
    "yt-stream-bandwidth": "youtube_automation.cli.stream_bandwidth",
    "yt-theme-compare": "youtube_automation.scripts.theme_compare",
    "yt-thumbnail-auto-select": "youtube_automation.scripts.auto_select_thumbnail",
    "yt-thumbnail-check": "youtube_automation.scripts.thumbnail_check",
    "yt-thumbnail-compare": "youtube_automation.scripts.compare_thumbnails",
    "yt-thumbnail-correlate": "youtube_automation.scripts.thumbnail_correlate",
    "yt-thumbnail-text": "youtube_automation.scripts.thumbnail_text",
    "yt-title-duplicate-check": "youtube_automation.scripts.title_duplicate_check",
    "yt-video-analyze": "youtube_automation.scripts.video_analyze",
    "yt-vote-log": "youtube_automation.scripts.vote_log",
    "yt-upload-auto": "youtube_automation.agents.youtube_auto_uploader",
    "yt-upload-collection": "youtube_automation.agents.collection_uploader",
    "yt-upload-shorts": "youtube_automation.agents.short_uploader",
    "yt-generate-shorts-loop": "youtube_automation.scripts.generate_short_loop",
    "yt-shorts-bulk-update-loc": "youtube_automation.scripts.bulk_update_short_localizations",
    "yt-skills": "youtube_automation.cli.skills_sync",
    "yt-setup-dirs": "youtube_automation.cli.setup_dirs",
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
    from youtube_automation import cli_entrypoints

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

    monkeypatch.setattr(cli_entrypoints, "import_module", fake_import_module)

    assert cli_entrypoints._run("dummy_cli_module") == 7

    assert stdout_buffer.getvalue().decode("utf-8") == "import 時出力 — 完了\n"
    assert stderr_buffer.getvalue().decode("utf-8") == "import 時エラー — 続行\n"


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
    from youtube_automation import cli_entrypoints

    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    scripts = pyproject["project"]["scripts"]

    assert scripts
    assert set(scripts) == set(EXPECTED_ENTRYPOINT_MODULES)
    for script_name, target in scripts.items():
        module_name, _, function_name = target.partition(":")
        assert script_name.startswith("yt-")
        assert module_name == "youtube_automation.cli_entrypoints"
        assert function_name
        assert hasattr(cli_entrypoints, function_name)


@pytest.mark.parametrize(
    ("script_name", "expected_module_path"),
    sorted(EXPECTED_ENTRYPOINT_MODULES.items()),
)
def test_cli_entrypoint_wrapper_dispatches_to_legacy_module(monkeypatch, script_name, expected_module_path):
    from youtube_automation import cli_entrypoints

    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    _, _, function_name = pyproject["project"]["scripts"][script_name].partition(":")
    calls: list[tuple[str, str]] = []

    def fake_run(module_path: str, function_name: str = "main") -> int:
        calls.append((module_path, function_name))
        return 42

    monkeypatch.setattr(cli_entrypoints, "_run", fake_run)

    assert getattr(cli_entrypoints, function_name)() == 42
    assert calls == [(expected_module_path, "main")]
