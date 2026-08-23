"""リポジトリ再配置の owner、依存方向、公開境界を固定する契約テスト。"""

# The exact owner table is intentionally kept one entry per moved file.
# ruff: noqa: E501

from __future__ import annotations

import ast
import importlib
import json
import shutil
import stat
import subprocess
import sys
import tarfile
import tomllib
import zipfile
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
    "ScheduleConfig",
    "Shorts",
    "channel_dir",
    "explicit_channel_selection",
    "find_workspace_root",
    "load_config",
    "load_schedule_config",
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

EXPECTED_CORE_ADAPTER_FILES = frozenset(
    {
        "core/adapters/__init__.py",
        "core/adapters/google/__init__.py",
        "core/adapters/media.py",
        "core/adapters/observability.py",
        "core/adapters/runtime.py",
        "core/adapters/security.py",
        "core/adapters/youtube.py",
    }
)

CORE_ADAPTER_DOC_START = "<!-- core-adapter-surface:start -->"
CORE_ADAPTER_DOC_END = "<!-- core-adapter-surface:end -->"

LEGACY_UTILS = SRC / "infrastructure" / "legacy_utils"
REMOVED_DUPLICATE_LEGACY_UTILS = frozenset(
    {
        "infrastructure/legacy_utils/profile.py",
        "infrastructure/legacy_utils/worktree.py",
    }
)
CANONICAL_LEGACY_UTILS_OWNERS = frozenset(
    {
        "infrastructure/observability/profile.py",
        "infrastructure/vcs/worktree.py",
    }
)
CONFIRMED_DOWNSTREAM_FACADES = (
    (
        "youtube_automation.infrastructure.errors",
        "youtube_automation.core.errors",
        "ConfigError",
    ),
    (
        "youtube_automation.utils.skill_config",
        "youtube_automation.configuration.skills",
        "reset",
    ),
    (
        "youtube_automation.utils.collection_paths",
        "youtube_automation.infrastructure.media.collection_paths",
        "CollectionPaths",
    ),
    (
        "youtube_automation.utils.image_provider",
        "youtube_automation.infrastructure.media.image_provider",
        "PromptSchema",
    ),
    (
        "youtube_automation.utils.audio_visualizer_mask",
        "youtube_automation.infrastructure.media.audio_visualizer_mask",
        "parse_size",
    ),
)


def test_core_adapter_source_surface_is_exact() -> None:
    # Given: #3895 後に保持する明示 adapter と package file の最終集合
    # When: source tree の adapter member を file type に関係なく列挙する
    actual = _core_adapter_source_files(SRC)

    # Then: file の追加・削除をどちらも許可しない
    assert actual == EXPECTED_CORE_ADAPTER_FILES


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
    imports.update(imported for _, imported in _literal_dynamic_imports(tree))
    return imports


def _literal_dynamic_imports(tree: ast.AST) -> list[tuple[int, str]]:
    importlib_bindings: set[str] = set()
    import_module_bindings: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            importlib_bindings.update(alias.asname or "importlib" for alias in node.names if alias.name == "importlib")
        elif isinstance(node, ast.ImportFrom) and node.module == "importlib":
            import_module_bindings.update(
                alias.asname or alias.name for alias in node.names if alias.name == "import_module"
            )

    imports: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        module = node.args[0]
        if not isinstance(module, ast.Constant) or not isinstance(module.value, str):
            continue
        builtin_loader = isinstance(node.func, ast.Name) and node.func.id == "__import__"
        direct_loader = isinstance(node.func, ast.Name) and node.func.id in import_module_bindings
        module_loader = (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "import_module"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in importlib_bindings
        )
        if builtin_loader or direct_loader or module_loader:
            imports.append((node.lineno, module.value))
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


def _core_adapter_source_files(source_root: Path) -> set[str]:
    adapter_root = source_root / "core" / "adapters"
    return {
        path.relative_to(source_root).as_posix()
        for path in adapter_root.rglob("*")
        if path.is_file() and "__pycache__" not in path.relative_to(adapter_root).parts
    }


def _core_adapter_surface_offenders(source_root: Path = SRC) -> list[str]:
    adapter_root = source_root / "core" / "adapters"
    actual_files = _core_adapter_source_files(source_root)
    offenders = [f"missing core adapter file: {path}" for path in sorted(EXPECTED_CORE_ADAPTER_FILES - actual_files)]
    offenders.extend(
        f"unexpected core adapter file: {path}" for path in sorted(actual_files - EXPECTED_CORE_ADAPTER_FILES)
    )

    adapter_namespace = "youtube_automation.core.adapters"
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        display_path: str | Path = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        for lineno, imported in _literal_dynamic_imports(tree):
            if imported == adapter_namespace or imported.startswith(f"{adapter_namespace}."):
                offenders.append(f"{display_path}:{lineno} -> {imported} dynamic import")
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or all(alias.name != "*" for alias in node.names):
                continue
            imported = _resolve_from_module(node, path, source_root)
            imports_core_adapter = imported == adapter_namespace or (
                imported is not None and imported.startswith(f"{adapter_namespace}.")
            )
            if path.is_relative_to(adapter_root) or imports_core_adapter:
                offenders.append(f"{display_path}:{node.lineno} -> {imported or '<relative>'} import *")
    return offenders


def _repository_reorganization_offenders(source_root: Path = SRC) -> list[str]:
    offenders = _core_adapter_surface_offenders(source_root)
    for layer in LAYER_FORBIDDEN_IMPORTS:
        offenders.extend(_layer_import_offenders(layer, source_root))
    return sorted(offenders)


def _mutation_source_root(tmp_path: Path) -> Path:
    source_root = tmp_path / "youtube_automation"
    shutil.copytree(SRC / "core" / "adapters", source_root / "core" / "adapters")
    return source_root


def _documented_core_adapter_files() -> frozenset[str]:
    architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    _, separator, remainder = architecture.partition(CORE_ADAPTER_DOC_START)
    assert separator, f"missing {CORE_ADAPTER_DOC_START}"
    surface, separator, _ = remainder.partition(CORE_ADAPTER_DOC_END)
    assert separator, f"missing {CORE_ADAPTER_DOC_END}"
    return frozenset(
        line.removeprefix("- `").removesuffix("`")
        for line in surface.splitlines()
        if line.startswith("- `src/youtube_automation/core/adapters/") and line.endswith("`")
    )


@pytest.mark.parametrize("allowed_import", sorted(DOMAIN_ALLOWED_INFRASTRUCTURE_IMPORTS))
def test_repository_scanner_allows_each_provider_neutral_import_mutation(
    tmp_path: Path,
    allowed_import: str,
) -> None:
    # Given: the frozen adapter surface plus one exact provider-neutral domain import
    source_root = _mutation_source_root(tmp_path)
    domain = source_root / "domains" / "probe.py"
    domain.parent.mkdir(parents=True)
    domain.write_text(f"import {allowed_import}\n", encoding="utf-8")

    # When: the same scanner used for the real repository evaluates the mutation
    offenders = _repository_reorganization_offenders(source_root)

    # Then: every enumerated authoritative owner remains allowed
    assert offenders == []


@pytest.mark.parametrize("forbidden_import", DOMAIN_FORBIDDEN_EXTERNAL_IMPORTS)
def test_repository_scanner_rejects_each_external_import_mutation(
    tmp_path: Path,
    forbidden_import: str,
) -> None:
    # Given: the frozen adapter surface plus one SDK, auth, network, or process import
    source_root = _mutation_source_root(tmp_path)
    domain = source_root / "domains" / "probe.py"
    domain.parent.mkdir(parents=True)
    domain.write_text(f"import {forbidden_import}\n", encoding="utf-8")

    # When: the same scanner used for the real repository evaluates the mutation
    offenders = _repository_reorganization_offenders(source_root)

    # Then: every namespace in the explicit external inventory is rejected
    assert offenders == [f"{domain} -> {forbidden_import}"]


@pytest.mark.parametrize(
    ("mutation", "expected_offender"),
    [
        ("add", "unexpected core adapter file: core/adapters/reintroduced.pyi"),
        ("remove", "missing core adapter file: core/adapters/security.py"),
    ],
)
def test_repository_scanner_rejects_core_adapter_file_surface_mutations(
    tmp_path: Path,
    mutation: str,
    expected_offender: str,
) -> None:
    # Given: one file is added to or removed from the frozen adapter surface
    source_root = _mutation_source_root(tmp_path)
    adapter_root = source_root / "core" / "adapters"
    if mutation == "add":
        (adapter_root / "reintroduced.pyi").write_text("def reintroduced() -> None: ...\n", encoding="utf-8")
    else:
        (adapter_root / "security.py").unlink()

    # When: the production repository scanner evaluates the mutated source tree
    offenders = _repository_reorganization_offenders(source_root)

    # Then: both additions and removals fail the exact surface contract
    assert expected_offender in offenders


@pytest.mark.parametrize("loader", ["importlib", "builtin"])
@pytest.mark.parametrize("forbidden_import", DOMAIN_FORBIDDEN_EXTERNAL_IMPORTS)
def test_repository_scanner_rejects_literal_dynamic_external_import_mutations(
    tmp_path: Path,
    loader: str,
    forbidden_import: str,
) -> None:
    # Given: a domain resolves an SDK, auth, network, or process module from a literal
    source_root = _mutation_source_root(tmp_path)
    domain = source_root / "domains" / "probe.py"
    domain.parent.mkdir(parents=True)
    source = (
        f'import importlib\nimportlib.import_module("{forbidden_import}")\n'
        if loader == "importlib"
        else f'__import__("{forbidden_import}")\n'
    )
    domain.write_text(source, encoding="utf-8")

    # When: the production repository scanner resolves literal dynamic imports
    offenders = _repository_reorganization_offenders(source_root)

    # Then: a dynamic loader cannot bypass the explicit external inventory
    assert offenders == [f"{domain} -> {forbidden_import}"]


@pytest.mark.parametrize("loader", ["importlib", "builtin"])
def test_repository_scanner_rejects_literal_dynamic_core_adapter_consumers(
    tmp_path: Path,
    loader: str,
) -> None:
    # Given: a domain dynamically resolves an otherwise explicit core adapter
    source_root = _mutation_source_root(tmp_path)
    domain = source_root / "domains" / "probe.py"
    domain.parent.mkdir(parents=True)
    adapter_import = "youtube_automation.core.adapters.runtime"
    source = (
        f'import importlib\nimportlib.import_module("{adapter_import}")\n'
        if loader == "importlib"
        else f'__import__("{adapter_import}")\n'
    )
    domain.write_text(source, encoding="utf-8")

    # When: the production repository scanner resolves literal dynamic imports
    offenders = _repository_reorganization_offenders(source_root)

    # Then: dynamic adapter consumers cannot recreate an opaque facade path
    assert any(adapter_import in offender and "dynamic import" in offender for offender in offenders)


@pytest.mark.parametrize(
    ("relative_path", "source", "expected_fragment"),
    [
        (
            "core/adapters/reintroduced.py",
            "from youtube_automation.infrastructure.filesystem import *\n",
            "youtube_automation.infrastructure.filesystem import *",
        ),
        (
            "core/adapters/runtime.py",
            "from youtube_automation.infrastructure.runtime import *\n",
            "youtube_automation.infrastructure.runtime import *",
        ),
        (
            "domains/probe.py",
            "from youtube_automation.core.adapters.runtime import *\n",
            "youtube_automation.core.adapters.runtime import *",
        ),
    ],
)
def test_repository_scanner_rejects_wildcard_facade_and_consumer_mutations(
    tmp_path: Path,
    relative_path: str,
    source: str,
    expected_fragment: str,
) -> None:
    # Given: an import-star facade definition or consumer is reintroduced
    source_root = _mutation_source_root(tmp_path)
    mutation = source_root / relative_path
    mutation.parent.mkdir(parents=True, exist_ok=True)
    mutation.write_text(source, encoding="utf-8")

    # When: the production repository scanner evaluates the mutation
    offenders = _repository_reorganization_offenders(source_root)

    # Then: wildcard reintroduction cannot pass through an otherwise allowed boundary
    assert any(expected_fragment in offender for offender in offenders)


def test_architecture_enumerates_the_exact_core_adapter_surface() -> None:
    # Given: the machine-readable final-surface enumeration in architecture.md
    # When: documented repository paths are read from the bounded contract section
    documented = _documented_core_adapter_files()

    # Then: docs and executable source contract enumerate the same files
    expected = frozenset(f"src/youtube_automation/{path}" for path in EXPECTED_CORE_ADAPTER_FILES)
    assert documented == expected


def _build_distributions(repository_root: Path, dist: Path) -> tuple[Path, Path]:
    result = subprocess.run(
        ["uv", "build", "--out-dir", str(dist)],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    wheels = list(dist.glob("*.whl"))
    sdists = list(dist.glob("*.tar.gz"))
    assert len(wheels) == 1
    assert len(sdists) == 1
    return wheels[0], sdists[0]


def _built_core_adapter_surfaces(wheel: Path, sdist: Path) -> tuple[set[str], set[str]]:
    wheel_prefix = "youtube_automation/core/adapters/"
    with zipfile.ZipFile(wheel) as archive:
        wheel_surface = {
            member for member in archive.namelist() if member.startswith(wheel_prefix) and not member.endswith("/")
        }
    sdist_prefix = "src/youtube_automation/core/adapters/"
    with tarfile.open(sdist) as archive:
        sdist_surface = set()
        for member in archive.getmembers():
            relative = Path(*Path(member.name).parts[1:]).as_posix()
            if member.isfile() and relative.startswith(sdist_prefix):
                sdist_surface.add(relative)
    return wheel_surface, sdist_surface


def _built_core_adapter_surface_offenders(wheel: Path, sdist: Path) -> list[str]:
    wheel_surface, sdist_surface = _built_core_adapter_surfaces(wheel, sdist)
    expected_wheel = {f"youtube_automation/{path}" for path in EXPECTED_CORE_ADAPTER_FILES}
    expected_sdist = {f"src/youtube_automation/{path}" for path in EXPECTED_CORE_ADAPTER_FILES}
    offenders = [f"wheel missing core adapter file: {path}" for path in sorted(expected_wheel - wheel_surface)]
    offenders.extend(f"wheel unexpected core adapter file: {path}" for path in sorted(wheel_surface - expected_wheel))
    offenders.extend(f"sdist missing core adapter file: {path}" for path in sorted(expected_sdist - sdist_surface))
    offenders.extend(f"sdist unexpected core adapter file: {path}" for path in sorted(sdist_surface - expected_sdist))
    return offenders


def _distribution_python_sources(wheel: Path, sdist: Path) -> tuple[set[str], set[str]]:
    with zipfile.ZipFile(wheel) as archive:
        wheel_sources = {member for member in archive.namelist() if member.endswith(".py")}
    with tarfile.open(sdist) as archive:
        sdist_sources = {
            Path(*Path(member.name).parts[1:]).as_posix()
            for member in archive.getmembers()
            if member.name.endswith(".py")
        }
    return wheel_sources, sdist_sources


def _source_python_entries(source_root: Path) -> set[str]:
    return {path.relative_to(source_root).as_posix() for path in source_root.rglob("*.py")}


def _duplicate_legacy_utils_source_offenders(source_root: Path) -> list[str]:
    entries = _source_python_entries(source_root)
    offenders = [f"reintroduced duplicate source: {path}" for path in sorted(entries & REMOVED_DUPLICATE_LEGACY_UTILS)]
    offenders.extend(f"missing canonical owner: {path}" for path in sorted(CANONICAL_LEGACY_UTILS_OWNERS - entries))
    return offenders


def _duplicate_legacy_utils_artifact_offenders(wheel: Path, sdist: Path) -> list[str]:
    wheel_sources, sdist_sources = _distribution_python_sources(wheel, sdist)
    removed_wheel = {f"youtube_automation/{path}" for path in REMOVED_DUPLICATE_LEGACY_UTILS}
    removed_sdist = {f"src/youtube_automation/{path}" for path in REMOVED_DUPLICATE_LEGACY_UTILS}
    canonical_wheel = {f"youtube_automation/{path}" for path in CANONICAL_LEGACY_UTILS_OWNERS}
    canonical_sdist = {f"src/youtube_automation/{path}" for path in CANONICAL_LEGACY_UTILS_OWNERS}
    offenders = [f"wheel reintroduced duplicate source: {path}" for path in sorted(wheel_sources & removed_wheel)]
    offenders.extend(f"sdist reintroduced duplicate source: {path}" for path in sorted(sdist_sources & removed_sdist))
    offenders.extend(f"wheel missing canonical owner: {path}" for path in sorted(canonical_wheel - wheel_sources))
    offenders.extend(f"sdist missing canonical owner: {path}" for path in sorted(canonical_sdist - sdist_sources))
    return offenders


_LEGACY_FACADE_IMPORTS = {
    "audio_visualizer_mask.py": {
        ("youtube_automation.infrastructure.media.audio_visualizer_mask", (("*", None),)),
    },
    "channel_target.py": {
        ("youtube_automation.configuration", (("channel_target", "_canonical"),)),
    },
    "cli_arguments.py": {
        ("youtube_automation.commands._shared", (("arguments", "_canonical"),)),
    },
    "collection_paths.py": {
        ("youtube_automation.infrastructure.media.collection_paths", (("*", None),)),
    },
    "genai_client.py": {
        (
            "youtube_automation.infrastructure.media.genai_client",
            (
                ("GLOBAL_LOCATION", None),
                ("VEO_LOCATION", None),
                ("create_genai_client", None),
                ("create_global_genai_client", None),
                ("create_veo_genai_client", None),
            ),
        ),
    },
    "image_provider/__init__.py": {
        ("youtube_automation.infrastructure.media.image_provider", (("*", None),)),
        (
            "youtube_automation.infrastructure.media.image_provider",
            (("composition", "composition"),),
        ),
        ("youtube_automation.infrastructure.media.image_provider", (("config", "config"),)),
        ("youtube_automation.infrastructure.media.image_provider", (("gemini", "gemini"),)),
        ("youtube_automation.infrastructure.media.image_provider", (("openai", "openai"),)),
        (
            "youtube_automation.infrastructure.media.image_provider",
            (("prompt_schema", "prompt_schema"),),
        ),
    },
    "image_provider/composition.py": {
        (
            "youtube_automation.infrastructure.media.image_provider",
            (("composition", "_canonical"),),
        ),
    },
    "image_provider/config.py": {
        ("youtube_automation.infrastructure.media.image_provider", (("config", "_canonical"),)),
    },
    "image_provider/gemini.py": {
        ("youtube_automation.infrastructure.media.image_provider", (("gemini", "_canonical"),)),
    },
    "image_provider/openai.py": {
        ("youtube_automation.infrastructure.media.image_provider", (("openai", "_canonical"),)),
    },
    "image_provider/prompt_schema.py": {
        (
            "youtube_automation.infrastructure.media.image_provider",
            (("prompt_schema", "_canonical"),),
        ),
    },
    "setup_directory_contract.py": {
        ("youtube_automation.infrastructure.collections.setup_directory_contract", (("*", None),)),
        (
            "youtube_automation.infrastructure.collections.setup_directory_contract",
            (
                ("SETUP_DIRECTORIES", None),
                ("validate_existing_setup_directories", None),
                ("validate_setup_directory_target", None),
            ),
        ),
    },
    "skill_config.py": {
        ("youtube_automation.configuration", (("skills", "_canonical"),)),
    },
}
_LEGACY_FACADE_SYMBOL_ALIASES = {
    "cli_arguments.py": {"CompetitorArgumentParser": "CompetitorArgumentParser"},
    "skill_config.py": {
        "_cache": "_cache",
        "_collect_deprecated_override_keys": "_collect_deprecated_override_keys",
        "_warn_deprecated_override_keys": "_warn_deprecated_override_keys",
        "_default_path": "_default_path",
        "_channel_override_path": "_channel_override_path",
        "_channel_override_candidates": "_channel_override_candidates",
        "_override_candidate_exists": "_override_candidate_exists",
        "_resolve_channel_override": "_resolve_channel_override",
        "_deep_merge": "_deep_merge",
        "_load_yaml": "_load_yaml",
        "_load_json": "_load_json",
        "_load_override": "_load_override",
        "THUMBNAIL_MODE_PARALLEL": "THUMBNAIL_MODE_PARALLEL",
        "THUMBNAIL_MODE_SEQUENTIAL": "THUMBNAIL_MODE_SEQUENTIAL",
        "load_skill_config": "load_skill_config",
        "load_channel_override": "load_channel_override",
        "get_collection_ideate_thumbnail_mode": "get_collection_ideate_thumbnail_mode",
        "reset": "reset",
    },
}
_LEGACY_FACADE_ALL = {
    "genai_client.py": (
        "GLOBAL_LOCATION",
        "VEO_LOCATION",
        "create_genai_client",
        "create_global_genai_client",
        "create_veo_genai_client",
    ),
    "setup_directory_contract.py": (
        "SETUP_DIRECTORIES",
        "validate_existing_setup_directories",
        "validate_setup_directory_target",
    ),
}
_LEGACY_FACADE_MODULE_ALIASES = frozenset(
    {
        "channel_target.py",
        "image_provider/composition.py",
        "image_provider/config.py",
        "image_provider/gemini.py",
        "image_provider/openai.py",
        "image_provider/prompt_schema.py",
    }
)
_LEGACY_FACADE_CHILD_MODULE_ALIASES = {
    "image_provider/__init__.py": frozenset({"composition", "config", "gemini", "openai", "prompt_schema"}),
}
_LEGACY_FACADE_PATHS = frozenset(
    {
        "__init__.py",
        "schemas/__init__.py",
        *_LEGACY_FACADE_IMPORTS,
    }
)


def _is_module_alias_target(node: ast.AST) -> bool:
    if not isinstance(node, ast.Subscript):
        return False
    modules = node.value
    if not (
        isinstance(modules, ast.Attribute)
        and isinstance(modules.value, ast.Name)
        and modules.value.id == "sys"
        and modules.attr == "modules"
    ):
        return False
    key = node.slice
    return isinstance(key, ast.Name) and key.id == "__name__"


def _historical_child_alias_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Subscript):
        return None
    modules = node.value
    if not (
        isinstance(modules, ast.Attribute)
        and isinstance(modules.value, ast.Name)
        and modules.value.id == "sys"
        and modules.attr == "modules"
    ):
        return None
    key = node.slice
    if not isinstance(key, ast.JoinedStr) or len(key.values) != 2:
        return None
    parent, suffix = key.values
    if not (
        isinstance(parent, ast.FormattedValue)
        and isinstance(parent.value, ast.Name)
        and parent.value.id == "__name__"
        and parent.conversion == -1
        and parent.format_spec is None
        and isinstance(suffix, ast.Constant)
        and isinstance(suffix.value, str)
        and suffix.value.startswith(".")
    ):
        return None
    return suffix.value.removeprefix(".")


def _is_allowed_reexport_assignment(relative: str, node: ast.Assign) -> bool:
    if len(node.targets) != 1:
        return False
    target = node.targets[0]
    if isinstance(target, ast.Name) and target.id == "__all__":
        if not isinstance(node.value, (ast.List, ast.Tuple)):
            return False
        values = tuple(
            element.value
            for element in node.value.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        )
        return len(values) == len(node.value.elts) and values == _LEGACY_FACADE_ALL.get(relative)
    if isinstance(target, ast.Name):
        aliases = _LEGACY_FACADE_SYMBOL_ALIASES.get(relative, {})
        return (
            aliases.get(target.id) is not None
            and isinstance(node.value, ast.Attribute)
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id == "_canonical"
            and node.value.attr == aliases[target.id]
        )
    is_whole_module_alias = (
        relative in _LEGACY_FACADE_MODULE_ALIASES
        and _is_module_alias_target(target)
        and isinstance(node.value, ast.Name)
        and node.value.id == "_canonical"
    )
    child_alias = _historical_child_alias_name(target)
    is_child_module_alias = (
        child_alias in _LEGACY_FACADE_CHILD_MODULE_ALIASES.get(relative, frozenset())
        and isinstance(node.value, ast.Name)
        and node.value.id == child_alias
    )
    return is_whole_module_alias or is_child_module_alias


def _legacy_facade_purity_offenders(legacy_root: Path) -> list[str]:
    offenders: list[str] = []
    for path in sorted(legacy_root.rglob("*.py")):
        relative = path.relative_to(legacy_root).as_posix()
        if relative not in _LEGACY_FACADE_PATHS:
            offenders.append(f"{relative}: unexpected facade path")
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for statement in tree.body:
            is_docstring = (
                isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Constant)
                and isinstance(statement.value.value, str)
            )
            import_signature = (
                (
                    statement.module,
                    tuple((alias.name, alias.asname) for alias in statement.names),
                )
                if isinstance(statement, ast.ImportFrom) and statement.level == 0
                else None
            )
            is_reexport_import = import_signature in _LEGACY_FACADE_IMPORTS.get(relative, set())
            is_sys_import = (
                (relative in _LEGACY_FACADE_MODULE_ALIASES or relative in _LEGACY_FACADE_CHILD_MODULE_ALIASES)
                and isinstance(statement, ast.Import)
                and tuple((alias.name, alias.asname) for alias in statement.names) == (("sys", None),)
            )
            is_reexport_assignment = isinstance(statement, ast.Assign) and _is_allowed_reexport_assignment(
                relative, statement
            )
            if is_docstring or is_reexport_import or is_sys_import or is_reexport_assignment:
                continue
            offenders.append(f"{relative}:{statement.lineno}: {type(statement).__name__}")
    return offenders


def test_legacy_utils_contains_only_declarative_reexport_facades() -> None:
    # Given: every Python member of the recursive compatibility-facade namespace
    # When: the facade purity contract classifies every top-level statement
    offenders = _legacy_facade_purity_offenders(LEGACY_UTILS)

    # Then: no implementation, control flow, or import-time execution remains
    assert offenders == []


@pytest.mark.parametrize(
    ("mutation_name", "source"),
    [
        ("function", "def implementation():\n    return 1\n"),
        ("class", "class Implementation:\n    pass\n"),
        ("assignment", "state = {}\n"),
        ("control-flow", "if True:\n    value = 1\n"),
        ("side-effect", "print('facade import')\n"),
        ("import-time-call", "initialize()\n"),
        ("plain-import", "import side_effect_module\n"),
    ],
)
def test_legacy_utils_purity_rejects_implementation_reintroduction_mutations(
    tmp_path: Path,
    mutation_name: str,
    source: str,
) -> None:
    # Given: a real allowed facade with one prohibited implementation shape appended
    facades = tmp_path / "facades"
    shutil.copytree(LEGACY_UTILS, facades, symlinks=True)
    facade = facades / "cli_arguments.py"
    facade.write_text(f"{facade.read_text(encoding='utf-8')}\n{source}", encoding="utf-8")

    # When: the same recursive scanner used for production source inspects it
    offenders = _legacy_facade_purity_offenders(facade.parent)

    # Then: the mutation cannot reintroduce executable implementation into a facade
    assert offenders, mutation_name


@pytest.mark.parametrize(
    ("relative_path", "source"),
    [
        (
            "cli_arguments.py",
            "from youtube_automation.commands._shared import arguments as _canonical\n__path__ = _canonical.__path__\n",
        ),
        (
            "cli_arguments.py",
            "from youtube_automation.commands._shared import arguments as _canonical\n"
            "__builtins__ = _canonical.__builtins__\n",
        ),
        (
            "cli_arguments.py",
            "from youtube_automation.commands._shared import arguments as _canonical\nrun = _canonical.side_effect\n",
        ),
        (
            "channel_target.py",
            "import sys\nimport evil as _canonical\nsys.modules[__name__] = _canonical\n",
        ),
        (
            "image_provider/config.py",
            "import sys\n"
            "from youtube_automation.infrastructure.media.image_provider import openai as _canonical\n"
            "sys.modules[__name__] = _canonical\n",
        ),
        ("collection_paths.py", "from evil.side_effect import *\n"),
    ],
)
def test_legacy_utils_purity_rejects_fail_open_declarative_mutations(
    tmp_path: Path,
    relative_path: str,
    source: str,
) -> None:
    # Given: an existing facade is replaced by a superficially declarative mutation
    facades = tmp_path / "facades"
    shutil.copytree(LEGACY_UTILS, facades, symlinks=True)
    (facades / relative_path).write_text(source, encoding="utf-8")

    # When: the production purity scanner checks the path-specific facade contract
    offenders = _legacy_facade_purity_offenders(facades)

    # Then: arbitrary aliases, import dunders, and external import redirects are rejected
    assert offenders, relative_path


@pytest.mark.parametrize(
    ("expected", "mutation"),
    [
        (
            'sys.modules[f"{__name__}.config"] = config',
            'sys.modules[f"{__name__}.evil"] = config',
        ),
        (
            'sys.modules[f"{__name__}.config"] = config',
            'sys.modules[f"{__name__}.config"] = openai',
        ),
        (
            'sys.modules[f"{__name__}.config"] = config',
            'sys.modules[f"{__name__!r}.config"] = config',
        ),
        (
            'sys.modules[f"{__name__}.config"] = config',
            'sys.modules[f"{__name__!a}.config"] = config',
        ),
        (
            'sys.modules[f"{__name__}.config"] = config',
            'sys.modules[f"{__name__:>80}.config"] = config',
        ),
        (
            'sys.modules[f"{__name__}.config"] = config',
            "sys.modules[f\"{__name__:{print('facade side effect')}}.config\"] = config",
        ),
    ],
)
def test_legacy_utils_purity_rejects_unapproved_parent_child_module_aliases(
    tmp_path: Path,
    expected: str,
    mutation: str,
) -> None:
    # Given: a real parent facade redirects an unknown key or the wrong canonical child
    facades = tmp_path / "facades"
    shutil.copytree(LEGACY_UTILS, facades, symlinks=True)
    parent = facades / "image_provider" / "__init__.py"
    source = parent.read_text(encoding="utf-8")
    assert expected in source
    parent.write_text(source.replace(expected, mutation), encoding="utf-8")

    # When: the path-aware purity scanner checks its exact child alias declarations
    offenders = _legacy_facade_purity_offenders(facades)

    # Then: only the five approved key-to-canonical-module pairs are accepted
    assert offenders


def test_duplicate_legacy_utils_sources_are_removed_but_canonical_owners_remain() -> None:
    # Given: the duplicate facade paths and their canonical implementation owners
    # When: the source distribution boundary is enumerated
    offenders = _duplicate_legacy_utils_source_offenders(SRC)

    # Then: duplicate paths are absent and both canonical owners remain present
    assert offenders == []


def test_duplicate_legacy_utils_source_symlink_mutation_is_detected(tmp_path: Path) -> None:
    # Given: a dangling symlink reintroduces one deleted Python path
    source_root = tmp_path / "youtube_automation"
    shutil.copytree(LEGACY_UTILS, source_root / "infrastructure" / "legacy_utils", symlinks=True)
    for owner in CANONICAL_LEGACY_UTILS_OWNERS:
        canonical = source_root / owner
        canonical.parent.mkdir(parents=True, exist_ok=True)
        canonical.write_text("# canonical owner\n", encoding="utf-8")
    mutation = source_root / "infrastructure" / "legacy_utils" / "profile.py"
    mutation.symlink_to("../observability/missing-profile.py")

    # When: every Python directory entry is enumerated regardless of file type
    offenders = _duplicate_legacy_utils_source_offenders(source_root)

    # Then: the deleted path cannot return as a dangling symlink unnoticed
    assert "reintroduced duplicate source: infrastructure/legacy_utils/profile.py" in offenders


def test_built_distributions_exclude_duplicate_legacy_utils_sources(tmp_path: Path) -> None:
    # Given: wheel and sdist built from the current repository source
    wheel, sdist = _build_distributions(ROOT, tmp_path / "legacy-utils-dist")

    # When: every Python source member in both archives is enumerated
    offenders = _duplicate_legacy_utils_artifact_offenders(wheel, sdist)

    # Then: neither archive ships a duplicate and both ship the canonical owners
    assert offenders == []


def test_distribution_symlink_and_hardlink_mutations_are_detected(tmp_path: Path) -> None:
    # Given: real built archives are copied with deleted paths restored as links
    wheel, sdist = _build_distributions(ROOT, tmp_path / "original-dist")
    mutated_wheel = tmp_path / "mutated.whl"
    with zipfile.ZipFile(wheel) as source, zipfile.ZipFile(mutated_wheel, "w") as target:
        for member in source.infolist():
            target.writestr(member, source.read(member.filename))
        link = zipfile.ZipInfo("youtube_automation/infrastructure/legacy_utils/profile.py")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        target.writestr(link, "../observability/profile.py")

    mutated_sdist = tmp_path / "mutated.tar.gz"
    with tarfile.open(sdist) as source, tarfile.open(mutated_sdist, "w:gz") as target:
        members = source.getmembers()
        for member in members:
            target.addfile(member, source.extractfile(member) if member.isfile() else None)
        package_root = Path(members[0].name).parts[0]
        symlink = tarfile.TarInfo(f"{package_root}/src/youtube_automation/infrastructure/legacy_utils/profile.py")
        symlink.type = tarfile.SYMTYPE
        symlink.linkname = "../observability/profile.py"
        target.addfile(symlink)
        hardlink = tarfile.TarInfo(f"{package_root}/src/youtube_automation/infrastructure/legacy_utils/worktree.py")
        hardlink.type = tarfile.LNKTYPE
        hardlink.linkname = f"{package_root}/src/youtube_automation/infrastructure/vcs/worktree.py"
        target.addfile(hardlink)

    # When: every Python archive member name is enumerated regardless of member type
    offenders = _duplicate_legacy_utils_artifact_offenders(mutated_wheel, mutated_sdist)

    # Then: wheel symlinks and sdist symlink/hardlink entries all violate the absence contract
    assert (
        "wheel reintroduced duplicate source: youtube_automation/infrastructure/legacy_utils/profile.py"
    ) in offenders
    assert (
        "sdist reintroduced duplicate source: src/youtube_automation/infrastructure/legacy_utils/profile.py"
    ) in offenders
    assert (
        "sdist reintroduced duplicate source: src/youtube_automation/infrastructure/legacy_utils/worktree.py"
    ) in offenders


def test_built_distributions_contain_the_exact_core_adapter_surface(tmp_path: Path) -> None:
    # Given: wheel and sdist built from the current repository source
    wheel, sdist = _build_distributions(ROOT, tmp_path / "dist")

    # When: every archive member under core/adapters is checked by the artifact contract
    offenders = _built_core_adapter_surface_offenders(wheel, sdist)

    # Then: packaging preserves exactly the frozen source surface
    assert offenders == []


def test_non_python_core_adapter_mutation_fails_source_and_built_artifact_contracts(tmp_path: Path) -> None:
    # Given: a real repository snapshot with an unapproved typed-stub member added
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    snapshot = subprocess.run(
        ["git", "archive", "--format=tar", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    snapshot_path = tmp_path / "repository.tar"
    snapshot_path.write_bytes(snapshot.stdout)
    with tarfile.open(snapshot_path) as archive:
        archive.extractall(repository_root, filter="data")
    source_root = repository_root / "src" / "youtube_automation"
    mutation = source_root / "core" / "adapters" / "reintroduced.pyi"
    mutation.write_text("def reintroduced() -> None: ...\n", encoding="utf-8")

    # When: production source and built-artifact contracts inspect the same mutation
    source_offenders = _repository_reorganization_offenders(source_root)
    wheel, sdist = _build_distributions(repository_root, tmp_path / "mutated-dist")
    artifact_offenders = _built_core_adapter_surface_offenders(wheel, sdist)

    # Then: the unapproved file type cannot enter source, wheel, or sdist unnoticed
    assert "unexpected core adapter file: core/adapters/reintroduced.pyi" in source_offenders
    assert "wheel unexpected core adapter file: youtube_automation/core/adapters/reintroduced.pyi" in artifact_offenders
    assert (
        "sdist unexpected core adapter file: src/youtube_automation/core/adapters/reintroduced.pyi"
        in artifact_offenders
    )


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
    source_root = _mutation_source_root(tmp_path)
    domain = source_root / "domains" / "probe.py"
    domain.parent.mkdir(parents=True)
    domain.write_text("from youtube_automation import infrastructure\n", encoding="utf-8")

    # When: the production layer scanner resolves the effective import target
    offenders = _repository_reorganization_offenders(source_root)

    # Then: the alias resolves to the forbidden infrastructure package
    assert offenders == [f"{domain} -> youtube_automation.infrastructure"]


def test_domain_layer_rejects_relative_unlisted_from_import_mutation(tmp_path: Path) -> None:
    # Given: a domain reaches an unlisted infrastructure package through a relative import
    source_root = _mutation_source_root(tmp_path)
    domain = source_root / "domains" / "probe.py"
    domain.parent.mkdir(parents=True)
    domain.write_text("from ..infrastructure import auth\n", encoding="utf-8")

    # When: the production layer scanner resolves the relative level and alias
    offenders = _repository_reorganization_offenders(source_root)

    # Then: the effective infrastructure owner remains forbidden
    assert offenders == [f"{domain} -> youtube_automation.infrastructure.auth"]


def test_domain_layer_allows_actual_symbol_from_exact_module_mutation(tmp_path: Path) -> None:
    # Given: an exact allowed module defines the symbol imported by a domain
    source_root = _mutation_source_root(tmp_path)
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
    offenders = _repository_reorganization_offenders(source_root)

    # Then: importing an actual symbol from the exact authoritative module is allowed
    assert offenders == []


def test_domain_layer_rejects_child_module_from_allowed_package_mutation(tmp_path: Path) -> None:
    # Given: a domain imports a child module from an otherwise allowed package
    source_root = _mutation_source_root(tmp_path)
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
    offenders = _repository_reorganization_offenders(source_root)

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
    source_root = _mutation_source_root(tmp_path)
    domain = source_root / "domains" / domain_path
    domain.parent.mkdir(parents=True)
    domain.write_text(source, encoding="utf-8")

    # When: the central production layer scanner evaluates every domain package
    offenders = _repository_reorganization_offenders(source_root)

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

    historical_consumer_moves = {
        ".claude/skills/metadata-audit/SKILL.md": ".claude/skills/audit/references/metadata.md",
        ".claude/skills/video-analyze/SKILL.md": ".claude/skills/audit/references/video.md",
        ".claude/skills/channel-new/SKILL.md": ".claude/skills/channel-strategy/SKILL.md",
        ".claude/skills/channel-new/references/analysis-mode.md": ".claude/skills/channel-research/references/market.md",
        ".claude/skills/channel-new/references/claude-md-template.md": ".claude/skills/setup/references/claude-md-template.md",
        ".claude/skills/channel-new/references/config-generation-rules.md": ".claude/skills/setup/references/config-generation-rules.md",
        ".claude/skills/channel-new/references/desire-vocabulary.md": ".claude/skills/channel-strategy/references/desire-vocabulary.md",
        ".claude/skills/channel-new/references/direction-mode.md": ".claude/skills/channel-strategy/references/direction.md",
        ".claude/skills/channel-new/references/directory-structure.md": ".claude/skills/setup/references/directory-structure.md",
        ".claude/skills/channel-new/references/fetch_branding_snapshot.py": ".claude/skills/setup/references/fetch_branding_snapshot.py",
        ".claude/skills/channel-new/references/generate_image.py": ".claude/skills/setup/references/generate_image.py",
        ".claude/skills/channel-new/references/benchmark_collector.py": ".claude/skills/channel-research/references/benchmark_collector.py",
        ".claude/skills/channel-new/references/fetch_benchmark_comments.py": ".claude/skills/channel-research/references/fetch_benchmark_comments.py",
        ".claude/skills/channel-new/references/verification.md": ".claude/skills/setup/references/verification.md",
        ".claude/skills/automation-schedule/references/schedule_config.py": (
            ".claude/skills/wf-new/references/schedule_config.py"
        ),
        ".claude/skills/collection-ideate/SKILL.md": ".claude/skills/wf-new/references/ideate.md",
        ".claude/skills/collection-ideate/references/benchmark_collector.py": (
            ".claude/skills/channel-research/references/benchmark_collector.py"
        ),
        ".claude/skills/wf-new/references/benchmark_collector.py": (
            ".claude/skills/channel-research/references/benchmark_collector.py"
        ),
        ".claude/skills/setup/references/benchmark_collector.py": (
            ".claude/skills/channel-research/references/benchmark_collector.py"
        ),
        ".claude/skills/benchmark/references/benchmark_collector.py": (
            ".claude/skills/channel-research/references/benchmark_collector.py"
        ),
        ".claude/skills/benchmark/SKILL.md": ".claude/skills/channel-research/references/benchmark.md",
        ".claude/skills/discover-competitors/SKILL.md": (".claude/skills/channel-research/references/discover.md"),
        ".claude/skills/setup/references/analysis-mode.md": (".claude/skills/channel-research/references/market.md"),
        ".claude/skills/market-research/SKILL.md": ".claude/skills/channel-research/references/market.md",
        ".claude/skills/market-research/references/report-contract.md": (
            ".claude/skills/channel-research/references/report-contract.md"
        ),
        ".claude/skills/viewer-voice/SKILL.md": ".claude/skills/channel-research/references/voice.md",
        ".claude/skills/viewer-voice/references/fetch_benchmark_comments.py": (
            ".claude/skills/channel-research/references/fetch_benchmark_comments.py"
        ),
        ".claude/skills/setup/references/fetch_benchmark_comments.py": (
            ".claude/skills/channel-research/references/fetch_benchmark_comments.py"
        ),
        ".claude/skills/thumbnail-research/SKILL.md": ".claude/skills/channel-research/references/thumbnail.md",
        ".claude/skills/audience-persona-design/SKILL.md": ".claude/skills/channel-strategy/references/persona.md",
        ".claude/skills/viewing-scene/SKILL.md": ".claude/skills/channel-strategy/references/scene.md",
        ".claude/skills/creative-constraints/SKILL.md": (".claude/skills/channel-strategy/references/constraints.md"),
        ".claude/skills/short-release/SKILL.md": ".claude/skills/short/SKILL.md",
        ".claude/skills/short-thumbnail/SKILL.md": ".claude/skills/short/references/thumbnail.md",
        ".claude/skills/short-thumbnail/references/generate_short_loop.py": (
            ".claude/skills/short/references/generate_short_loop.py"
        ),
        ".claude/skills/collection-ideate/references/generate_image.py": (
            ".claude/skills/wf-new/references/generate_image.py"
        ),
        ".claude/skills/collection-ideate/references/object-design-examples.md": (
            ".claude/skills/wf-new/references/object-design-examples.md"
        ),
        ".claude/skills/collection-ideate/references/select-ttp-references.py": (
            ".claude/skills/wf-new/references/select-ttp-references.py"
        ),
        "src/youtube_automation/commands/uploads/_upload_cli_error_boundary.py": (
            "src/youtube_automation/commands/_shared/cli_harness.py"
        ),
    }
    resolved_paths = [historical_consumer_moves.get(path, path) for path in consumer_paths]

    # Then: receipt の証跡は契約テスト自身だけでなく、現在の owner へ解決できる consumer を指す
    assert all((ROOT / path).is_file() for path in resolved_paths)


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


def test_repository_reorganization_scanner_accepts_real_source() -> None:
    # Given: #3895 後の canonical source tree と最終 adapter surface
    # When: mutation tests と同じ production repository scanner で全契約を評価する
    offenders = _repository_reorganization_offenders()

    # Then: layer 依存、adapter file、wildcard import の違反がない
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
    flop_analysis = (ROOT / ".claude" / "skills" / "analytics" / "references" / "flop.md").read_text(encoding="utf-8")

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


@pytest.mark.parametrize(("legacy_module", "canonical_module", "symbol"), CONFIRMED_DOWNSTREAM_FACADES)
def test_only_confirmed_downstream_imports_remain_as_compatibility_facades(
    legacy_module: str,
    canonical_module: str,
    symbol: str,
) -> None:
    # Given: 計画で下流利用を確認した旧 import path
    # When: 旧 path を下流利用可能な facade として解決する
    module = importlib.import_module(legacy_module)
    canonical = importlib.import_module(canonical_module)

    # Then: facade は公開 module としてロードでき、canonical symbol identity を保つ
    assert module.__name__ == legacy_module
    assert getattr(module, symbol) is getattr(canonical, symbol)


def test_confirmed_downstream_facades_preserve_runtime_behavior() -> None:
    # Given: the five confirmed downstream facades loaded in an isolated interpreter
    code = """
import importlib
from pathlib import Path

errors = importlib.import_module("youtube_automation.infrastructure.errors")
try:
    raise errors.ConfigError("facade-behavior")
except errors.ConfigError as exc:
    assert str(exc) == "facade-behavior"

skills = importlib.import_module("youtube_automation.utils.skill_config")
canonical_skills = importlib.import_module("youtube_automation.configuration.skills")
skills.reset()
skills._cache["facade-behavior"] = {}
canonical_skills.reset("facade-behavior")
assert "facade-behavior" not in skills._cache

paths = importlib.import_module("youtube_automation.utils.collection_paths")
assert paths.CollectionPaths("example").root == Path("example").resolve()

image_provider = importlib.import_module("youtube_automation.utils.image_provider")
assert image_provider.PromptSchema(primary_request="facade-behavior").primary_request == "facade-behavior"

mask = importlib.import_module("youtube_automation.utils.audio_visualizer_mask")
assert mask.parse_size("12x34") == (12, 34)
"""

    # When: representative behavior is exercised through each historical path
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    # Then: every facade delegates behavior to its canonical owner without divergence
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("submodule", ("config", "composition", "prompt_schema", "gemini", "openai"))
def test_image_provider_submodule_facades_preserve_canonical_module_identity(submodule: str) -> None:
    # Given: a downstream image-provider submodule path and its canonical owner
    code = f"""
import importlib

facade = importlib.import_module("youtube_automation.utils.image_provider.{submodule}")
canonical = importlib.import_module("youtube_automation.infrastructure.media.image_provider.{submodule}")
assert facade is canonical
"""

    # When: both paths are imported in an isolated interpreter
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    # Then: patching and module state share the exact canonical module object
    assert result.returncode == 0, result.stderr


def test_image_provider_parent_import_registers_exact_canonical_child_modules() -> None:
    # Given: a fresh interpreter that imports only the historical parent facade
    code = """
import importlib
import sys

parent_name = "youtube_automation.utils.image_provider"
parent = importlib.import_module(parent_name)
for child in ("config", "composition", "prompt_schema", "gemini", "openai"):
    canonical_name = f"youtube_automation.infrastructure.media.image_provider.{child}"
    canonical = sys.modules[canonical_name]
    assert getattr(parent, child) is canonical
    assert sys.modules[f"{parent_name}.{child}"] is canonical
"""

    # When: parent attributes and import registry entries are observed without child imports
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    # Then: all five historical child surfaces retain exact canonical module identity
    assert result.returncode == 0, result.stderr


def test_image_provider_composition_facade_preserves_patch_and_globals_seam() -> None:
    # Given: downstream code imports the historical composition submodule
    code = """
import importlib

facade = importlib.import_module("youtube_automation.utils.image_provider.composition")
canonical = importlib.import_module("youtube_automation.infrastructure.media.image_provider.composition")
original = facade.log_image_cost
assert original.__globals__ is facade.__dict__
replacement = object()
facade.log_image_cost = replacement
assert canonical.log_image_cost is replacement
"""

    # When: a downstream patch mutates the facade module
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    # Then: the canonical owner observes the same patch and function globals
    assert result.returncode == 0, result.stderr
