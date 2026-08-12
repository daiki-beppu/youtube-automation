"""リポジトリ再配置の owner、依存方向、公開境界を固定する契約テスト。"""

# The exact owner table is intentionally kept one entry per moved file.
# ruff: noqa: E501

from __future__ import annotations

import ast
import importlib
import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from tests.helpers.paths import REPO_ROOT

pytestmark = pytest.mark.repo_contract

ROOT = REPO_ROOT
SRC = ROOT / "src" / "youtube_automation"
RECEIPT = ROOT / "docs" / "architecture" / "repository-reorganization-receipt.json"

EXPECTED_MOVED_SOURCES = frozenset(
    {
        "src/youtube_automation/utils/audio_visualizer_fill.py",
        "src/youtube_automation/utils/audio_visualizer_mask.py",
        "src/youtube_automation/utils/benchmark_analyzer.py",
        "src/youtube_automation/utils/channel_registry.py",
        "src/youtube_automation/utils/channel_target.py",
        "src/youtube_automation/utils/chrome_extensions.py",
        "src/youtube_automation/utils/cli_arguments.py",
        "src/youtube_automation/utils/collection_paths.py",
        "src/youtube_automation/utils/comments/__init__.py",
        "src/youtube_automation/utils/comments/codex_generator.py",
        "src/youtube_automation/utils/comments/fetcher.py",
        "src/youtube_automation/utils/comments/generator.py",
        "src/youtube_automation/utils/comments/generator_factory.py",
        "src/youtube_automation/utils/comments/history.py",
        "src/youtube_automation/utils/comments/prompt_safety.py",
        "src/youtube_automation/utils/comments/replier.py",
        "src/youtube_automation/utils/competitor_discovery.py",
        "src/youtube_automation/utils/competitor_scoring.py",
        "src/youtube_automation/utils/composition_lock.py",
        "src/youtube_automation/utils/ctr_resolver.py",
        "src/youtube_automation/utils/dashboard_read_model.py",
        "src/youtube_automation/utils/dashboard_refresh.py",
        "src/youtube_automation/utils/genai_client.py",
        "src/youtube_automation/utils/google_cloud_project.py",
        "src/youtube_automation/utils/image_provider/__init__.py",
        "src/youtube_automation/utils/image_provider/composition.py",
        "src/youtube_automation/utils/image_provider/config.py",
        "src/youtube_automation/utils/image_provider/gemini.py",
        "src/youtube_automation/utils/image_provider/openai.py",
        "src/youtube_automation/utils/image_provider/prompt_schema.py",
        "src/youtube_automation/utils/kpi_dashboard.py",
        "src/youtube_automation/utils/launch_curve_data.py",
        "src/youtube_automation/utils/live_chat/__init__.py",
        "src/youtube_automation/utils/live_chat/codex.py",
        "src/youtube_automation/utils/live_chat/filters.py",
        "src/youtube_automation/utils/live_chat/history.py",
        "src/youtube_automation/utils/live_chat/models.py",
        "src/youtube_automation/utils/live_chat/runner.py",
        "src/youtube_automation/utils/lyria_client.py",
        "src/youtube_automation/utils/notification.py",
        "src/youtube_automation/utils/numbered_duplicates.py",
        "src/youtube_automation/utils/omni_generator.py",
        "src/youtube_automation/utils/probe.py",
        "src/youtube_automation/utils/profile.py",
        "src/youtube_automation/utils/progress.py",
        "src/youtube_automation/utils/publish_schedule.py",
        "src/youtube_automation/utils/reporting_api.py",
        "src/youtube_automation/utils/retention_timeline.py",
        "src/youtube_automation/utils/schedule.py",
        "src/youtube_automation/utils/schemas/__init__.py",
        "src/youtube_automation/utils/setup_directory_contract.py",
        "src/youtube_automation/utils/skill_config.py",
        "src/youtube_automation/utils/stock.py",
        "src/youtube_automation/utils/streaming/__init__.py",
        "src/youtube_automation/utils/streaming/cycle_uptime.py",
        "src/youtube_automation/utils/streaming/daily_archive.py",
        "src/youtube_automation/utils/streaming/instance_resolver.py",
        "src/youtube_automation/utils/streaming/monthly_archive.py",
        "src/youtube_automation/utils/streaming/monthly_report.py",
        "src/youtube_automation/utils/streaming/threshold.py",
        "src/youtube_automation/utils/streaming/vultr_bandwidth.py",
        "src/youtube_automation/utils/theme_performance.py",
        "src/youtube_automation/utils/time_utils.py",
        "src/youtube_automation/utils/traffic_trend.py",
        "src/youtube_automation/utils/ttp_health.py",
        "src/youtube_automation/utils/veo_generator.py",
        "src/youtube_automation/utils/veo_operation_store.py",
        "src/youtube_automation/utils/video_analyzer.py",
        "src/youtube_automation/utils/worktree.py",
        "src/youtube_automation/utils/youtube_quota.py",
        "src/youtube_automation/utils/youtube_tag.py",
        "src/youtube_automation/infrastructure/errors.py",
    }
)

EXPECTED_MOVED_OWNERS = {
    "src/youtube_automation/utils/audio_visualizer_fill.py": "src/youtube_automation/infrastructure/media/audio_visualizer_fill.py",
    "src/youtube_automation/utils/audio_visualizer_mask.py": "src/youtube_automation/infrastructure/media/audio_visualizer_mask.py",
    "src/youtube_automation/utils/benchmark_analyzer.py": "src/youtube_automation/infrastructure/analytics/benchmark_analyzer.py",
    "src/youtube_automation/utils/channel_registry.py": "src/youtube_automation/infrastructure/analytics/channel_registry.py",
    "src/youtube_automation/utils/channel_target.py": "src/youtube_automation/configuration/channel_target.py",
    "src/youtube_automation/utils/chrome_extensions.py": "src/youtube_automation/infrastructure/collections/chrome_extensions.py",
    "src/youtube_automation/utils/cli_arguments.py": "src/youtube_automation/commands/_shared/arguments.py",
    "src/youtube_automation/utils/collection_paths.py": "src/youtube_automation/infrastructure/media/collection_paths.py",
    "src/youtube_automation/utils/comments/__init__.py": "src/youtube_automation/application/comments/__init__.py",
    "src/youtube_automation/utils/comments/codex_generator.py": "src/youtube_automation/application/comments/codex_generator.py",
    "src/youtube_automation/utils/comments/fetcher.py": "src/youtube_automation/application/comments/fetcher.py",
    "src/youtube_automation/utils/comments/generator.py": "src/youtube_automation/application/comments/generator.py",
    "src/youtube_automation/utils/comments/generator_factory.py": "src/youtube_automation/application/comments/generator_factory.py",
    "src/youtube_automation/utils/comments/history.py": "src/youtube_automation/application/comments/history.py",
    "src/youtube_automation/utils/comments/prompt_safety.py": "src/youtube_automation/application/comments/prompt_safety.py",
    "src/youtube_automation/utils/comments/replier.py": "src/youtube_automation/application/comments/replier.py",
    "src/youtube_automation/utils/competitor_discovery.py": "src/youtube_automation/infrastructure/analytics/competitor_discovery.py",
    "src/youtube_automation/utils/competitor_scoring.py": "src/youtube_automation/infrastructure/analytics/competitor_scoring.py",
    "src/youtube_automation/utils/composition_lock.py": "src/youtube_automation/infrastructure/media/composition_lock.py",
    "src/youtube_automation/utils/ctr_resolver.py": "src/youtube_automation/infrastructure/analytics/ctr_resolver.py",
    "src/youtube_automation/utils/dashboard_read_model.py": "src/youtube_automation/infrastructure/analytics/dashboard_read_model.py",
    "src/youtube_automation/utils/dashboard_refresh.py": "src/youtube_automation/infrastructure/analytics/dashboard_refresh.py",
    "src/youtube_automation/utils/genai_client.py": "src/youtube_automation/infrastructure/media/genai_client.py",
    "src/youtube_automation/utils/google_cloud_project.py": "src/youtube_automation/infrastructure/runtime/google_cloud_project.py",
    "src/youtube_automation/utils/image_provider/__init__.py": "src/youtube_automation/infrastructure/media/image_provider/__init__.py",
    "src/youtube_automation/utils/image_provider/composition.py": "src/youtube_automation/infrastructure/media/image_provider/composition.py",
    "src/youtube_automation/utils/image_provider/config.py": "src/youtube_automation/infrastructure/media/image_provider/config.py",
    "src/youtube_automation/utils/image_provider/gemini.py": "src/youtube_automation/infrastructure/media/image_provider/gemini.py",
    "src/youtube_automation/utils/image_provider/openai.py": "src/youtube_automation/infrastructure/media/image_provider/openai.py",
    "src/youtube_automation/utils/image_provider/prompt_schema.py": "src/youtube_automation/infrastructure/media/image_provider/prompt_schema.py",
    "src/youtube_automation/utils/kpi_dashboard.py": "src/youtube_automation/infrastructure/analytics/kpi_dashboard.py",
    "src/youtube_automation/utils/launch_curve_data.py": "src/youtube_automation/infrastructure/analytics/launch_curve_data.py",
    "src/youtube_automation/utils/live_chat/__init__.py": "src/youtube_automation/application/live_chat/__init__.py",
    "src/youtube_automation/utils/live_chat/codex.py": "src/youtube_automation/application/live_chat/codex.py",
    "src/youtube_automation/utils/live_chat/filters.py": "src/youtube_automation/application/live_chat/filters.py",
    "src/youtube_automation/utils/live_chat/history.py": "src/youtube_automation/application/live_chat/history.py",
    "src/youtube_automation/utils/live_chat/models.py": "src/youtube_automation/application/live_chat/models.py",
    "src/youtube_automation/utils/live_chat/runner.py": "src/youtube_automation/application/live_chat/runner.py",
    "src/youtube_automation/utils/lyria_client.py": "src/youtube_automation/infrastructure/media/lyria_client.py",
    "src/youtube_automation/utils/notification.py": "src/youtube_automation/infrastructure/youtube/notification.py",
    "src/youtube_automation/utils/numbered_duplicates.py": "src/youtube_automation/infrastructure/collections/numbered_duplicates.py",
    "src/youtube_automation/utils/omni_generator.py": "src/youtube_automation/infrastructure/media/omni_generator.py",
    "src/youtube_automation/utils/probe.py": "src/youtube_automation/infrastructure/media/probe.py",
    "src/youtube_automation/utils/profile.py": "src/youtube_automation/infrastructure/observability/profile.py",
    "src/youtube_automation/utils/progress.py": "src/youtube_automation/infrastructure/runtime/progress.py",
    "src/youtube_automation/utils/publish_schedule.py": "src/youtube_automation/infrastructure/runtime/publish_schedule.py",
    "src/youtube_automation/utils/reporting_api.py": "src/youtube_automation/infrastructure/youtube/reporting_api.py",
    "src/youtube_automation/utils/retention_timeline.py": "src/youtube_automation/infrastructure/analytics/retention_timeline.py",
    "src/youtube_automation/utils/schedule.py": "src/youtube_automation/infrastructure/runtime/schedule.py",
    "src/youtube_automation/utils/schemas/__init__.py": "src/youtube_automation/infrastructure/legacy_utils/schemas/__init__.py",
    "src/youtube_automation/utils/setup_directory_contract.py": "src/youtube_automation/infrastructure/collections/setup_directory_contract.py",
    "src/youtube_automation/utils/skill_config.py": "src/youtube_automation/configuration/skills.py",
    "src/youtube_automation/utils/stock.py": "src/youtube_automation/infrastructure/media/stock.py",
    "src/youtube_automation/utils/streaming/__init__.py": "src/youtube_automation/infrastructure/youtube/streaming/__init__.py",
    "src/youtube_automation/utils/streaming/cycle_uptime.py": "src/youtube_automation/infrastructure/youtube/streaming/cycle_uptime.py",
    "src/youtube_automation/utils/streaming/daily_archive.py": "src/youtube_automation/infrastructure/youtube/streaming/daily_archive.py",
    "src/youtube_automation/utils/streaming/instance_resolver.py": "src/youtube_automation/infrastructure/youtube/streaming/instance_resolver.py",
    "src/youtube_automation/utils/streaming/monthly_archive.py": "src/youtube_automation/infrastructure/youtube/streaming/monthly_archive.py",
    "src/youtube_automation/utils/streaming/monthly_report.py": "src/youtube_automation/infrastructure/youtube/streaming/monthly_report.py",
    "src/youtube_automation/utils/streaming/threshold.py": "src/youtube_automation/infrastructure/youtube/streaming/threshold.py",
    "src/youtube_automation/utils/streaming/vultr_bandwidth.py": "src/youtube_automation/infrastructure/youtube/streaming/vultr_bandwidth.py",
    "src/youtube_automation/utils/theme_performance.py": "src/youtube_automation/infrastructure/analytics/theme_performance.py",
    "src/youtube_automation/utils/time_utils.py": "src/youtube_automation/infrastructure/runtime/time_utils.py",
    "src/youtube_automation/utils/traffic_trend.py": "src/youtube_automation/infrastructure/analytics/traffic_trend.py",
    "src/youtube_automation/utils/ttp_health.py": "src/youtube_automation/infrastructure/analytics/ttp_health.py",
    "src/youtube_automation/utils/veo_generator.py": "src/youtube_automation/infrastructure/media/veo_generator.py",
    "src/youtube_automation/utils/veo_operation_store.py": "src/youtube_automation/infrastructure/media/veo_operation_store.py",
    "src/youtube_automation/utils/video_analyzer.py": "src/youtube_automation/infrastructure/media/video_analyzer.py",
    "src/youtube_automation/utils/worktree.py": "src/youtube_automation/infrastructure/vcs/worktree.py",
    "src/youtube_automation/utils/youtube_quota.py": "src/youtube_automation/infrastructure/youtube/youtube_quota.py",
    "src/youtube_automation/utils/youtube_tag.py": "src/youtube_automation/infrastructure/youtube/youtube_tag.py",
    "src/youtube_automation/infrastructure/errors.py": "src/youtube_automation/core/errors.py",
}

PUBLIC_CONFIGURATION_SYMBOLS = {
    "ChannelConfig",
    "CommunityDraft",
    "Distrokid",
    "PinnedComment",
    "Shorts",
    "channel_dir",
    "find_workspace_root",
    "load_config",
    "reset",
    "select_channel",
    "workspace_channels",
}

LAYER_FORBIDDEN_IMPORTS = {
    "configuration": ("commands", "application", "domains", "utils"),
    "infrastructure": ("commands", "application"),
    "domains": ("commands", "application", "infrastructure"),
    "application": ("commands", "utils"),
    "commands": ("utils",),
}

DOMAIN_ALLOWED_INFRASTRUCTURE_IMPORTS = frozenset(
    {
        "youtube_automation.infrastructure.browser",
        "youtube_automation.infrastructure.filesystem",
        "youtube_automation.infrastructure.google.upload",
        "youtube_automation.infrastructure.google.youtube",
        "youtube_automation.infrastructure.process",
        "youtube_automation.infrastructure.quota",
    }
)

DOMAIN_FORBIDDEN_SDK_AUTH_IMPORTS = (
    "google.auth",
    "google.genai",
    "google.oauth2",
    "google_auth_httplib2",
    "google_auth_oauthlib",
    "googleapiclient",
    "httplib2",
    "oauthlib",
    "openai",
)

DOMAIN_FORBIDDEN_EXTERNAL_IO_IMPORTS = (
    "aiohttp",
    "http.client",
    "httpx",
    "requests",
    "socket",
    "subprocess",
    "urllib.error",
    "urllib.request",
)

DOMAIN_FORBIDDEN_EXTERNAL_IMPORTS = DOMAIN_FORBIDDEN_SDK_AUTH_IMPORTS + DOMAIN_FORBIDDEN_EXTERNAL_IO_IMPORTS

DOMAIN_EXISTING_EXTERNAL_IMPORT_EXCEPTIONS = frozenset(
    {
        ("domains/metadata/service.py", "subprocess"),
    }
)


def _receipt() -> dict[str, object]:
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def _module_source_path(module_name: str, source_root: Path) -> Path | None:
    package_prefix = "youtube_automation"
    if module_name == package_prefix:
        relative = Path()
    elif module_name.startswith(f"{package_prefix}."):
        relative = Path(*module_name.removeprefix(f"{package_prefix}.").split("."))
    else:
        return None
    if relative.parts:
        module_path = source_root / relative.with_suffix(".py")
        if module_path.is_file():
            return module_path
    package_path = source_root / relative / "__init__.py"
    return package_path if package_path.is_file() else None


def _module_binding_names(module_name: str, source_root: Path) -> set[str]:
    module_path = _module_source_path(module_name, source_root)
    if module_path is None:
        return set()
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    bindings: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bindings.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            bindings.update(target.id for target in targets if isinstance(target, ast.Name))
        elif isinstance(node, ast.Import):
            bindings.update(alias.asname or alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            bindings.update(alias.asname or alias.name for alias in node.names if alias.name != "*")
    return bindings


def _module_parts_for_path(path: Path, source_root: Path) -> tuple[str, ...] | None:
    try:
        relative = path.relative_to(source_root).with_suffix("")
    except ValueError:
        return None
    parts = relative.parts
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ("youtube_automation", *parts)


def _resolve_from_module(node: ast.ImportFrom, path: Path, source_root: Path) -> str | None:
    if node.level == 0:
        return node.module
    module_parts = _module_parts_for_path(path, source_root)
    if module_parts is None:
        return node.module
    package_parts = module_parts if path.name == "__init__.py" else module_parts[:-1]
    retained_count = len(package_parts) - node.level + 1
    if retained_count < 0:
        return node.module
    resolved = [*package_parts[:retained_count]]
    if node.module:
        resolved.extend(node.module.split("."))
    return ".".join(resolved) or None


def _imports(path: Path, source_root: Path = SRC) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module_name = _resolve_from_module(node, path, source_root)
            if module_name is None:
                continue
            bindings = _module_binding_names(module_name, source_root)
            for alias in node.names:
                if alias.name == "*":
                    imports.add(module_name)
                    continue
                candidate = f"{module_name}.{alias.name}"
                if _module_source_path(candidate, source_root) is not None or alias.name not in bindings:
                    imports.add(candidate)
                else:
                    imports.add(module_name)
    return imports


def _is_forbidden_layer_import(layer: str, imported: str) -> bool:
    if layer == "domains" and any(
        imported == namespace or imported.startswith(f"{namespace}.") for namespace in DOMAIN_FORBIDDEN_EXTERNAL_IMPORTS
    ):
        return True
    for forbidden_layer in LAYER_FORBIDDEN_IMPORTS[layer]:
        forbidden_namespace = f"youtube_automation.{forbidden_layer}"
        if imported != forbidden_namespace and not imported.startswith(f"{forbidden_namespace}."):
            continue
        if layer == "domains" and imported in DOMAIN_ALLOWED_INFRASTRUCTURE_IMPORTS:
            return False
        return True
    return False


def _layer_import_offenders(layer: str, source_root: Path = SRC) -> list[str]:
    offenders: list[str] = []
    for path in (source_root / layer).rglob("*.py"):
        if path.is_relative_to(source_root / "infrastructure" / "legacy_utils"):
            continue
        relative_path = path.relative_to(source_root).as_posix()
        display_path: str | Path = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        for imported in _imports(path, source_root):
            if (relative_path, imported) in DOMAIN_EXISTING_EXTERNAL_IMPORT_EXCEPTIONS:
                continue
            if _is_forbidden_layer_import(layer, imported):
                offenders.append(f"{display_path} -> {imported}")
    return offenders


@pytest.mark.parametrize("allowed_import", sorted(DOMAIN_ALLOWED_INFRASTRUCTURE_IMPORTS))
def test_domain_layer_allows_each_authoritative_provider_neutral_import(allowed_import: str) -> None:
    # Given: provider-neutral infrastructure owner explicitly approved for domains
    # When: the domain layer evaluates the direct import edge
    # Then: the exact authoritative module is allowed
    assert not _is_forbidden_layer_import("domains", allowed_import)


@pytest.mark.parametrize(
    "forbidden_import",
    [
        "google.auth",
        "google.genai",
        "google_auth_httplib2",
        "google_auth_oauthlib",
        "googleapiclient",
        "openai",
        "subprocess",
        "urllib.request",
        "youtube_automation.infrastructure",
        "youtube_automation.infrastructure.auth",
        "youtube_automation.infrastructure.browser.extension",
        "youtube_automation.infrastructure.browser_evasion",
        "youtube_automation.infrastructure.filesystem.path",
        "youtube_automation.infrastructure.filesystem_backup",
        "youtube_automation.infrastructure.google",
        "youtube_automation.infrastructure.google.upload.client",
        "youtube_automation.infrastructure.google.upload_backup",
        "youtube_automation.infrastructure.google.youtube.client",
        "youtube_automation.infrastructure.google.youtube_backup",
        "youtube_automation.infrastructure.media",
        "youtube_automation.infrastructure.network",
        "youtube_automation.infrastructure.process.runner",
        "youtube_automation.infrastructure.process_backup",
        "youtube_automation.infrastructure.quota.internal",
        "youtube_automation.infrastructure.quota_backup",
        "youtube_automation.infrastructure.subprocess",
    ],
)
def test_domain_layer_rejects_unlisted_external_and_non_exact_imports(forbidden_import: str) -> None:
    # Given: an unlisted infrastructure owner or a prefix/substring lookalike
    # When: the domain layer evaluates the direct import edge
    # Then: broad and near-match infrastructure imports remain forbidden
    assert _is_forbidden_layer_import("domains", forbidden_import)


@pytest.mark.parametrize(
    "unrelated_import",
    [
        "google",
        "google.cloud",
        "google_auth_oauthlib_backup",
        "googleapiclient_backup",
        "openai_tools",
    ],
)
def test_domain_layer_external_inventory_does_not_use_broad_or_substring_matches(unrelated_import: str) -> None:
    # Given: a root namespace or substring lookalike outside the explicit SDK/auth inventory
    # When: the domain layer evaluates the import edge
    # Then: the inventory does not turn into a broad google or substring rejection
    assert not _is_forbidden_layer_import("domains", unrelated_import)


def test_domain_layer_rejects_broad_parent_from_import_mutation(tmp_path: Path) -> None:
    # Given: a domain imports the broad infrastructure package through an alias
    source_root = tmp_path / "youtube_automation"
    domain = source_root / "domains" / "probe.py"
    domain.parent.mkdir(parents=True)
    domain.write_text("from youtube_automation import infrastructure\n", encoding="utf-8")

    # When: the production layer scanner resolves the effective import target
    offenders = _layer_import_offenders("domains", source_root)

    # Then: the alias resolves to the forbidden infrastructure package
    assert offenders == [f"{domain} -> youtube_automation.infrastructure"]


def test_domain_layer_rejects_relative_unlisted_from_import_mutation(tmp_path: Path) -> None:
    # Given: a domain reaches an unlisted infrastructure package through a relative import
    source_root = tmp_path / "youtube_automation"
    domain = source_root / "domains" / "probe.py"
    domain.parent.mkdir(parents=True)
    domain.write_text("from ..infrastructure import auth\n", encoding="utf-8")

    # When: the production layer scanner resolves the relative level and alias
    offenders = _layer_import_offenders("domains", source_root)

    # Then: the effective infrastructure owner remains forbidden
    assert offenders == [f"{domain} -> youtube_automation.infrastructure.auth"]


def test_domain_layer_allows_actual_symbol_from_exact_module_mutation(tmp_path: Path) -> None:
    # Given: an exact allowed module defines the symbol imported by a domain
    source_root = tmp_path / "youtube_automation"
    filesystem = source_root / "infrastructure" / "filesystem" / "__init__.py"
    filesystem.parent.mkdir(parents=True)
    filesystem.write_text("def path_exists(path):\n    return True\n", encoding="utf-8")
    domain = source_root / "domains" / "probe.py"
    domain.parent.mkdir(parents=True)
    domain.write_text(
        "from youtube_automation.infrastructure.filesystem import path_exists\n",
        encoding="utf-8",
    )

    # When: the production layer scanner distinguishes the module from its symbol
    offenders = _layer_import_offenders("domains", source_root)

    # Then: importing an actual symbol from the exact authoritative module is allowed
    assert offenders == []


def test_domain_layer_rejects_child_module_from_allowed_package_mutation(tmp_path: Path) -> None:
    # Given: a domain imports a child module from an otherwise allowed package
    source_root = tmp_path / "youtube_automation"
    filesystem = source_root / "infrastructure" / "filesystem" / "__init__.py"
    filesystem.parent.mkdir(parents=True)
    filesystem.write_text("", encoding="utf-8")
    (filesystem.parent / "path.py").write_text("", encoding="utf-8")
    domain = source_root / "domains" / "probe.py"
    domain.parent.mkdir(parents=True)
    domain.write_text(
        "from youtube_automation.infrastructure.filesystem import path\n",
        encoding="utf-8",
    )

    # When: the production layer scanner resolves the alias as a child module
    offenders = _layer_import_offenders("domains", source_root)

    # Then: an allowed package cannot widen the exact allowlist to child modules
    assert offenders == [f"{domain} -> youtube_automation.infrastructure.filesystem.path"]


@pytest.mark.parametrize(
    ("domain_path", "source", "forbidden_import"),
    [
        ("collections/genai_import_probe.py", "import google.genai\n", "google.genai"),
        ("collections/genai_from_probe.py", "from google import genai\n", "google.genai"),
        ("collections/openai_import_probe.py", "import openai\n", "openai"),
        ("collections/openai_from_probe.py", "from openai import OpenAI\n", "openai.OpenAI"),
        (
            "metadata/oauth_import_probe.py",
            "import google_auth_oauthlib\n",
            "google_auth_oauthlib",
        ),
        (
            "metadata/oauth_from_probe.py",
            "from google_auth_oauthlib.flow import InstalledAppFlow\n",
            "google_auth_oauthlib.flow.InstalledAppFlow",
        ),
        ("collections/sdk_probe.py", "import googleapiclient\n", "googleapiclient"),
        (
            "collections/sdk_from_probe.py",
            "from googleapiclient.discovery import build\n",
            "googleapiclient.discovery.build",
        ),
        ("collections/auth_probe.py", "import google.auth\n", "google.auth"),
        ("metadata/network_probe.py", "import urllib.request\n", "urllib.request"),
        ("metadata/process_probe.py", "import subprocess\n", "subprocess"),
    ],
)
def test_domain_layer_rejects_external_import_mutations_outside_uploads(
    tmp_path: Path,
    domain_path: str,
    source: str,
    forbidden_import: str,
) -> None:
    # Given: a non-uploads domain directly imports an external I/O or auth dependency
    source_root = tmp_path / "youtube_automation"
    domain = source_root / "domains" / domain_path
    domain.parent.mkdir(parents=True)
    domain.write_text(source, encoding="utf-8")

    # When: the central production layer scanner evaluates every domain package
    offenders = _layer_import_offenders("domains", source_root)

    # Then: specialized uploads contracts are not required to reject the edge
    assert offenders == [f"{domain} -> {forbidden_import}"]


def test_reorganization_receipt_has_one_canonical_owner_per_moved_source() -> None:
    # Given: 実際に行った移動と参照修正を記録する機械可読 receipt
    receipt = _receipt()
    mappings = receipt["mappings"]

    # When: owner mapping を読み込む
    assert isinstance(mappings, list) and mappings
    old_owners = [mapping["old_owner"] for mapping in mappings]

    # Then: 同じ移動元を複数の owner に割り当てず、新 owner は実在する
    assert len(old_owners) == len(set(old_owners))
    for mapping in mappings:
        new_owner = ROOT / mapping["exact_new_owner"]
        assert new_owner.is_file(), mapping["exact_new_owner"]
        assert mapping["responsibility"]
        assert mapping["reference_updates"]


def test_reorganization_receipt_covers_every_moved_file_with_an_exact_owner() -> None:
    # Given: 再配置前に存在した責務別移動対象の完全な集合
    mappings = _receipt()["mappings"]
    old_owners = {mapping["old_owner"] for mapping in mappings}

    # When: receipt の移動元と canonical owner を照合する
    actual_owners = {mapping["old_owner"]: mapping["exact_new_owner"] for mapping in mappings}

    # Then: directory の代表記録や欠落を許さず、各移動元を一度だけ追跡できる
    assert old_owners == EXPECTED_MOVED_SOURCES
    assert len(mappings) == len(EXPECTED_MOVED_SOURCES)
    assert all(Path(owner).suffix == ".py" for owner in old_owners)
    assert actual_owners == EXPECTED_MOVED_OWNERS
    assert all(Path(owner).suffix == ".py" for owner in actual_owners.values())


def test_reorganization_receipt_describes_each_mapping_without_placeholders() -> None:
    # Given: 各移動元に固有の責務と参照更新を持つ receipt
    mappings = _receipt()["mappings"]

    # When: 説明欄を比較する
    responsibilities = {mapping["responsibility"] for mapping in mappings}
    reference_updates = {tuple(mapping["reference_updates"]) for mapping in mappings}

    # Then: 全件同じ抽象文ではなく、実際の責務と参照経路を記録する
    assert len(responsibilities) > 1
    assert len(reference_updates) > 1
    assert all(
        mapping["responsibility"] != "Canonical owner for the moved repository responsibility" for mapping in mappings
    )
    assert all(
        mapping["reference_updates"] != ["Production and documentation references use the canonical owner"]
        for mapping in mappings
    )
    assert all(
        Path(mapping["exact_new_owner"]).name in mapping["responsibility"]
        and mapping["exact_new_owner"] in mapping["reference_updates"][0]
        and mapping["old_owner"] in mapping["reference_updates"][1]
        for mapping in mappings
    )


def test_reorganization_receipt_names_existing_non_contract_consumers() -> None:
    # Given: 各移動元について、参照修正先を Updated consumer として記録した receipt
    mappings = _receipt()["mappings"]
    contract_path = "tests/contracts/architecture/test_repository_reorganization_contract.py"

    # When: consumer 記録を抽出し、リポジトリ上のファイルへ解決する
    consumer_paths: list[str] = []
    for mapping in mappings:
        updates = mapping["reference_updates"]
        consumers = [
            update.removeprefix("Updated consumer: ") for update in updates if update.startswith("Updated consumer: ")
        ]
        assert consumers, mapping["old_owner"]
        assert any(path != contract_path for path in consumers), mapping["old_owner"]
        consumer_paths.extend(consumers)

    # Then: receipt の証跡は契約テスト自身だけでなく、実在する consumer を指す
    assert all((ROOT / path).is_file() for path in consumer_paths)


def test_streaming_healthcheck_describes_the_canonical_daily_archive_owner() -> None:
    # Given: streaming healthcheck の active test source
    healthcheck = ROOT / "tests" / "test_streaming_healthcheck.py"
    source = healthcheck.read_text(encoding="utf-8")
    canonical_owner = "src/youtube_automation/infrastructure/youtube/streaming/daily_archive.py"
    legacy_owner = "src/youtube_automation/utils/streaming/daily_archive.py"
    legacy_package_owner = "src/youtube_automation/utils/streaming/__init__.py"

    # When: owner 表記と実行経路を確認する
    canonical_mentions = source.count(canonical_owner)

    # Then: active な説明は canonical owner を示し、旧 filesystem owner を再掲しない
    assert canonical_mentions >= 2
    assert legacy_owner not in source
    assert legacy_package_owner not in source


def test_canonical_layers_do_not_import_lower_boundary_owners() -> None:
    # Given: layer ごとの依存方向が再配置後の canonical source で定義される
    # When: source の import edge を layer 単位で収集する
    offenders = [offender for layer in LAYER_FORBIDDEN_IMPORTS for offender in _layer_import_offenders(layer)]

    # Then: CLI、application、domain、infrastructure の責務が逆流しない
    assert offenders == []


def test_configuration_public_import_surface_is_preserved() -> None:
    # Given: 下流 repository が利用する configuration package の公開契約
    module = importlib.import_module("youtube_automation.configuration")

    # When: package の明示 export を取得する
    exported = set(module.__all__)

    # Then: 再配置後も公開 symbol が欠落しない
    assert exported == PUBLIC_CONFIGURATION_SYMBOLS


def test_all_console_scripts_keep_the_entrypoint_module_and_callable() -> None:
    # Given: pyproject.toml に登録された下流向け console script
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    # When: すべての entry point target を解決する
    unresolved: list[str] = []
    for name, target in project["scripts"].items():
        module_name, separator, symbol_name = target.partition(":")
        if not separator:
            unresolved.append(f"{name}: malformed target {target}")
            continue
        try:
            module = importlib.import_module(module_name)
            if not callable(getattr(module, symbol_name)):
                unresolved.append(f"{name}: {target} is not callable")
        except (ImportError, AttributeError) as exc:
            unresolved.append(f"{name}: {target}: {exc}")

    # Then: 移動で CLI 名・入口・callable が壊れていない
    assert unresolved == []


def test_skill_source_is_canonical_and_agents_path_remains_a_symlink() -> None:
    # Given: skills の実体と Codex 用の互換参照位置
    agents_skills = ROOT / ".agents" / "skills"
    canonical_skills = ROOT / ".claude" / "skills"

    # When: filesystem contract を観測する
    # Then: 実体を .claude 側に置き、.agents 側は symlink のまま維持する
    assert canonical_skills.is_dir()
    assert agents_skills.is_symlink()
    assert agents_skills.resolve() == canonical_skills.resolve()


def test_legacy_compatibility_package_is_a_wheel_package() -> None:
    # Given: 旧公開 import を installed wheel でも解決する compatibility package
    utils_package = SRC / "utils"
    legacy_package = SRC / "infrastructure" / "legacy_utils"

    # When: package の配布対象となる filesystem 境界を観測する
    # Then: symlink ではなく実体 package として legacy implementation を参照する
    assert utils_package.is_dir()
    assert not utils_package.is_symlink()
    assert (utils_package / "__init__.py").is_file()
    assert (legacy_package / "skill_config.py").is_file()
    assert (legacy_package / "image_provider" / "__init__.py").is_file()


def test_reorganization_references_use_canonical_owner_paths() -> None:
    # Given: 再配置で更新対象になった CI と active documentation
    dashboard_workflow = (ROOT / ".github" / "workflows" / "dashboard.yml").read_text(encoding="utf-8")
    architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    flop_analysis = (ROOT / ".claude" / "skills" / "flop-analysis" / "SKILL.md").read_text(encoding="utf-8")

    # Then: 旧内部 path を案内せず、実在する owner を案内する
    assert "src/youtube_automation/utils/channel_registry.py" not in dashboard_workflow
    assert "src/youtube_automation/utils/dashboard_read_model.py" not in dashboard_workflow
    assert "src/youtube_automation/infrastructure/analytics/channel_registry.py" in dashboard_workflow
    assert "src/youtube_automation/infrastructure/analytics/dashboard_read_model.py" in dashboard_workflow
    assert "src/youtube_automation/infrastructure/legacy_utils/channel_registry.py" not in dashboard_workflow
    assert "src/youtube_automation/infrastructure/legacy_utils/dashboard_read_model.py" not in dashboard_workflow
    assert "src/youtube_automation/infrastructure/legacy_utils/" in architecture
    assert "youtube_automation.configuration.skills.load_skill_config" in flop_analysis
    assert (ROOT / "docs/architecture/reorganization-followups.md").is_file()


def test_active_streaming_tests_describe_canonical_owners() -> None:
    # Given: 再配置後の owner を説明する active test 群
    expected_descriptions = {
        "tests/infrastructure/youtube/test_stream_constants.py": (
            "infrastructure/youtube/streaming/__init__.py",
            "utils/streaming/__init__.py",
        ),
        "tests/infrastructure/youtube/test_stream_cycle_uptime.py": (
            "infrastructure/youtube/streaming/cycle_uptime.py",
            "utils/streaming/cycle_uptime.py",
        ),
        "tests/infrastructure/youtube/test_stream_instance_resolver.py": (
            "infrastructure/youtube/streaming/instance_resolver.py",
            "utils/streaming/instance_resolver.py",
        ),
        "tests/infrastructure/youtube/test_stream_monthly_archive.py": (
            "infrastructure/youtube/streaming/monthly_archive.py",
            "utils/streaming/monthly_archive.py",
        ),
        "tests/infrastructure/youtube/test_stream_monthly_report.py": (
            "infrastructure/youtube/streaming/monthly_report.py",
            "utils/streaming/monthly_report.py",
        ),
        "tests/infrastructure/youtube/test_stream_threshold.py": (
            "infrastructure/youtube/streaming/threshold.py",
            "utils/streaming/threshold.py",
        ),
        "tests/infrastructure/youtube/test_stream_vultr_bandwidth.py": (
            "infrastructure/youtube/streaming/vultr_bandwidth.py",
            "utils/streaming/vultr_bandwidth.py",
        ),
        "tests/infrastructure/youtube/test_notification.py": (
            "infrastructure/youtube/notification.py",
            "utils/notification.py",
        ),
        "tests/commands/youtube/test_stream_bandwidth_cli.py": (
            "commands/youtube/stream_bandwidth.py",
            "cli/stream_bandwidth.py",
        ),
        "tests/test_streaming_healthcheck.py": (
            "infrastructure/youtube/streaming/__init__.py",
            "utils/streaming/__init__.py",
        ),
    }

    # Then: active test の案内は canonical owner のみを現行 owner として示す
    for relative_path, (canonical_owner, legacy_owner) in expected_descriptions.items():
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert canonical_owner in source, relative_path
        assert legacy_owner not in source, relative_path


def test_internal_moved_owner_imports_do_not_route_through_legacy_facades() -> None:
    # Given: 移動済み責務の canonical owner と、互換性のために残る旧 namespace
    forbidden = (
        "youtube_automation.infrastructure.legacy_utils.channel_target",
        "youtube_automation.infrastructure.legacy_utils.cli_arguments",
        "youtube_automation.infrastructure.legacy_utils.skill_config",
    )

    # When: legacy facade 自身を除く production import を走査する
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        if "/infrastructure/legacy_utils/" in str(path):
            continue
        for imported in _imports(path):
            if imported in forbidden:
                offenders.append(f"{path.relative_to(ROOT)} -> {imported}")

    # Then: 内部経路は canonical owner を直接利用する
    assert offenders == []


def test_channel_target_facades_export_the_canonical_implementation() -> None:
    # Given: canonical module と下流互換 facade の公開関数
    code = """
import importlib

canonical = importlib.import_module("youtube_automation.configuration.channel_target")
legacy = importlib.import_module("youtube_automation.infrastructure.legacy_utils.channel_target")
compat = importlib.import_module("youtube_automation.utils.channel_target")
assert canonical.resolve_existing_target_dir is legacy.resolve_existing_target_dir
assert canonical.resolve_existing_target_dir is compat.resolve_existing_target_dir
"""

    # When: 3つの公開入口を新しい interpreter で解決する
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    # Then: 実装は canonical owner に一元化される
    assert result.returncode == 0, result.stderr


def test_channel_target_facade_exposes_only_the_canonical_target_module() -> None:
    # Given: channel-target の旧公開入口と canonical owner
    code = """
import importlib

canonical = importlib.import_module("youtube_automation.configuration.channel_target")
legacy = importlib.import_module("youtube_automation.infrastructure.legacy_utils.channel_target")
assert legacy.__name__ == canonical.__name__
assert not hasattr(legacy, "load_config")
"""

    # When: legacy entry point を新しい interpreter で解決する
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    # Then: loader 全体ではなく channel-target owner の公開面だけが見える
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "forbidden_namespace",
    [
        "youtube_automation.utils",
        "youtube_automation.infrastructure.legacy_utils",
    ],
)
def test_production_imports_do_not_use_compatibility_facades_as_owners(
    forbidden_namespace: str,
) -> None:
    """全 production import を走査し、旧 namespace の主経路化を防ぐ。"""
    offenders: list[str] = []

    for path in SRC.rglob("*.py"):
        if path.is_relative_to(SRC / "infrastructure" / "legacy_utils"):
            continue
        for imported in _imports(path):
            if imported.startswith(forbidden_namespace):
                offenders.append(f"{path.relative_to(ROOT)} -> {imported}")

    assert offenders == []


@pytest.mark.parametrize(
    "tree_root",
    [ROOT / "tests", ROOT / ".claude" / "skills", ROOT / "bench"],
)
def test_internal_consumers_use_canonical_moved_owners(tree_root: Path) -> None:
    # Given: repository-internal executable consumers, excluding compatibility tests themselves
    forbidden = (
        "youtube_automation.utils",
        "youtube_automation.infrastructure.errors",
        "youtube_automation.infrastructure.legacy_utils",
    )
    offenders: list[str] = []
    compatibility_tests = {
        "test_skills_sync_installed_wheel.py",
        "test_infrastructure_errors.py",
        "test_b4_reorganization_contract.py",
        "test_configuration_migration_contract.py",
        "test_streaming_healthcheck.py",
    }

    # When: Python imports and string patch targets are inspected in each consumer
    for path in tree_root.rglob("*.py"):
        if path.is_relative_to(ROOT / "tests" / "contracts"):
            continue
        if path.name in compatibility_tests:
            continue
        text = path.read_text(encoding="utf-8")
        imports = _imports(path)
        matches = [value for value in imports if value.startswith(forbidden)]
        matches.extend(value for value in forbidden if value in text and value not in matches)
        if matches:
            offenders.append(f"{path.relative_to(ROOT)} -> {sorted(set(matches))}")

    # Then: internal consumers do not create a second module identity through an old owner
    assert offenders == []


def test_compatibility_packages_do_not_extend_their_path_to_canonical_implementations() -> None:
    # Given: compatibility packages that must expose only explicit facades
    code = """
import importlib

for name in ("youtube_automation.utils", "youtube_automation.infrastructure.legacy_utils"):
    module = importlib.import_module(name)
    assert all("/application/" not in path for path in module.__path__)
    assert all("/infrastructure/analytics/" not in path for path in module.__path__)
    assert all("/infrastructure/media/" not in path for path in module.__path__)
    assert all("/infrastructure/youtube/" not in path for path in module.__path__)
"""

    # When: paths are observed in a fresh interpreter, independent of this test process
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    # Then: importing an old namespace cannot make canonical implementation directories importable
    assert result.returncode == 0, result.stderr


def test_canonical_modules_do_not_register_noop_namespace_aliases() -> None:
    # Given: canonical owners whose old namespace aliases were removed
    code = """
import importlib
import sys

modules = {
    "youtube_automation.infrastructure.analytics.competitor_discovery":
        "youtube_automation.utils.competitor_discovery",
    "youtube_automation.infrastructure.analytics.competitor_scoring":
        "youtube_automation.utils.competitor_scoring",
    "youtube_automation.infrastructure.media.video_analyzer":
        "youtube_automation.utils.video_analyzer",
    "youtube_automation.infrastructure.youtube.notification":
        "youtube_automation.utils.notification",
}
for canonical, legacy in modules.items():
    importlib.import_module(canonical)
    assert legacy not in sys.modules, (canonical, legacy)
"""

    # When: each canonical module is imported in a fresh interpreter
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    # Then: canonical imports do not create misleading old namespace entries
    assert result.returncode == 0, result.stderr


def test_comments_canonical_package_does_not_eagerly_import_submodules() -> None:
    # Given: the canonical comments package exposes only its explicit public exports
    code = """
import importlib
import sys

package = importlib.import_module("youtube_automation.application.comments")
assert package.__name__ == "youtube_automation.application.comments"
assert "youtube_automation.application.comments.codex_generator" not in sys.modules
"""

    # When: the package is imported in a fresh interpreter
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    # Then: importing the package does not create unrelated module side effects
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("import_order", [("legacy", "canonical"), ("canonical", "legacy")])
def test_genai_client_compatibility_import_orders_use_explicit_facade(import_order: tuple[str, str]) -> None:
    # Given: canonical GenAI client and its explicit historical facade
    imports = {
        "legacy": "youtube_automation.infrastructure.legacy_utils.genai_client",
        "canonical": "youtube_automation.infrastructure.media.genai_client",
    }
    code = f"""
import importlib
first = importlib.import_module({imports[import_order[0]]!r})
second = importlib.import_module({imports[import_order[1]]!r})
assert first.create_global_genai_client is second.create_global_genai_client
assert first.__name__ != second.__name__
assert 'youtube_automation.utils.genai_client' not in __import__('sys').modules
"""

    # When: both supported import orders are resolved in a fresh interpreter
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    # Then: the facade delegates explicitly without canonical-side alias registration
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("import_order", [("legacy", "canonical"), ("canonical", "legacy")])
def test_skill_config_compatibility_import_orders_share_identity_and_cache(import_order: tuple[str, str]) -> None:
    # Given: 下流向け旧 import と canonical import の両方が利用される
    imports = {
        "legacy": "youtube_automation.infrastructure.legacy_utils.skill_config",
        "canonical": "youtube_automation.configuration.skills",
    }
    code = f"""
import importlib
first = importlib.import_module({imports[import_order[0]]!r})
second = importlib.import_module({imports[import_order[1]]!r})
assert first.reset is second.reset
assert first._cache is second._cache
first.reset()
first._cache['identity-check'] = {{}}
second.reset('identity-check')
assert 'identity-check' not in first._cache
"""

    # When: 新しい interpreter で各 import 順を実行する
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    # Then: import 順によらず同じ module/cache が使われる
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "legacy_module",
    [
        "youtube_automation.infrastructure.errors",
        "youtube_automation.utils.skill_config",
        "youtube_automation.utils.collection_paths",
        "youtube_automation.utils.image_provider",
        "youtube_automation.utils.audio_visualizer_mask",
    ],
)
def test_only_confirmed_downstream_imports_remain_as_compatibility_facades(legacy_module: str) -> None:
    # Given: 計画で下流利用を確認した旧 import path
    # When: 旧 path を下流利用可能な facade として解決する
    module = importlib.import_module(legacy_module)

    # Then: facade は空の placeholder ではなく、公開 module としてロードできる
    assert module.__name__ == legacy_module
