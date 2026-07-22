"""Issue #2305: Suno/metadata domain ownership contracts.

要件とテストの対応:

* R1-R7, R19, R22: ``test_domain_modules_are_importable`` と
  ``test_legacy_modules_are_removed``
* R8, R14, R22: ``test_domain_dependency_edges_are_one_way``
* R9-R13, R15, R23: metadata facade/export/identity tests
* R18, R20, R21: この repository の active source/skill/docs は旧 import を
  残さない契約として ``test_active_files_have_no_legacy_owner_references`` で確認する。
  downstream 2 repository と receipt/handoff/changelog の本文は、この test の責務外
  なので未カバー（実ファイルがこの worktree にない、または非実行資産のため）。
* R16-R17: 既存の consumer 回帰テスト群が各入口を担保し、本ファイルでは新 facade
  の import smoke と monkeypatch lookup の所有位置を構造契約として固定する。

"""

from __future__ import annotations

import ast
import importlib
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SUNO_ROOT = "youtube_automation.domains.suno"
_DOWNLOADED_ROOT = f"{_SUNO_ROOT}.downloaded"
_METADATA_ROOT = "youtube_automation.domains.metadata"

_DOMAIN_MODULES = (
    f"{_DOWNLOADED_ROOT}.models",
    f"{_DOWNLOADED_ROOT}.workflow",
    f"{_DOWNLOADED_ROOT}.validation",
    f"{_DOWNLOADED_ROOT}.archive",
    f"{_DOWNLOADED_ROOT}.apply",
    f"{_SUNO_ROOT}.config",
    f"{_SUNO_ROOT}.lyrics",
    f"{_SUNO_ROOT}.prompts",
    f"{_SUNO_ROOT}.playlist",
    f"{_SUNO_ROOT}.selection",
    f"{_METADATA_ROOT}.service",
    f"{_METADATA_ROOT}.titles",
    f"{_METADATA_ROOT}.descriptions",
    f"{_METADATA_ROOT}.tags",
    f"{_METADATA_ROOT}.localizations",
)

_LEGACY_MODULES = (
    "suno_artifact_contracts.py",
    "suno_artifact_validation.py",
    "suno_downloaded_apply.py",
    "suno_downloaded_archive.py",
    "suno_downloaded_artifacts.py",
    "suno_downloaded_payload.py",
    "suno_downloaded_workflow_state.py",
    "suno_effective_config.py",
    "suno_lyrics.py",
    "suno_playlist_verification.py",
    "suno_prompts_json.py",
    "suno_track_selection.py",
    "suno_verify_artifacts.py",
    "suno_verify_readers.py",
    "metadata_generator.py",
)


def _module_path(module_name: str) -> Path:
    relative = module_name.replace(".", "/")
    return _ROOT / "src" / f"{relative}.py"


def _module_exists(module_name: str) -> bool:
    module_path = _ROOT / "src" / f"{module_name.replace('.', '/')}.py"
    package_path = _ROOT / "src" / module_name.replace(".", "/") / "__init__.py"
    return module_path.is_file() or package_path.is_file()


def test_domain_modules_are_importable() -> None:
    for module_name in _DOMAIN_MODULES:
        assert importlib.import_module(module_name).__name__ == module_name


def test_downloaded_facade_exposes_only_domain_operations() -> None:
    downloaded = importlib.import_module(f"{_DOWNLOADED_ROOT}")

    assert set(downloaded.__all__) == {
        "DownloadedArtifactError",
        "DownloadedPayload",
        "DownloadedPayloadError",
        "apply_downloaded_artifacts",
        "count_audio_files",
        "expected_download_count",
        "parse_downloaded_payload",
        "read_pattern_count",
    }


def test_metadata_facade_has_fixed_public_surface_and_class_identity() -> None:
    facade = importlib.import_module(_METADATA_ROOT)
    service = importlib.import_module(f"{_METADATA_ROOT}.service")

    assert facade.__all__ == [
        "BAHMetadataGenerator",
        "LOCALIZED_TITLE_PLACEHOLDERS",
        "SceneTitleViolation",
        "build_short_description",
        "build_short_localizations",
        "format_scene_title_violations",
        "format_title_template",
        "validate_localizations_title_templates",
        "validate_scene_phrases",
    ]
    assert facade.BAHMetadataGenerator is service.BAHMetadataGenerator
    assert "main" not in facade.__all__
    assert "_extract_pattern_key" not in facade.__all__
    assert "_localized_title_values" not in facade.__all__


def test_metadata_service_module_cli_does_not_emit_runtime_warning() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_ROOT / "src")

    result = subprocess.run(
        [sys.executable, "-m", f"{_METADATA_ROOT}.service"],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "RuntimeWarning" not in result.stderr
    assert "使用法: python -m youtube_automation.domains.metadata.service" in result.stdout


def _resolve_imported_modules(module_name: str, tree: ast.AST) -> set[str]:
    """Return import targets with relative imports resolved to absolute names."""
    module_parts = module_name.split(".")
    package_parts = module_parts[:-1]
    imported: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
            continue
        if not isinstance(node, ast.ImportFrom):
            continue

        if node.level == 0:
            if node.module is not None:
                for alias in node.names:
                    child_module = f"{node.module}.{alias.name}"
                    imported.add(
                        child_module if _module_exists(child_module) else node.module
                    )
            continue

        base_parts = package_parts[: len(package_parts) - node.level + 1]
        if node.module is not None:
            imported.add(".".join((*base_parts, node.module)))
        else:
            imported.update(".".join((*base_parts, alias.name)) for alias in node.names)

    return imported


def test_dependency_import_collection_covers_absolute_and_relative_imports() -> None:
    tree = ast.parse(
        """
import youtube_automation.domains.metadata.service
from youtube_automation.domains.metadata import titles
from youtube_automation.domains.metadata import BAHMetadataGenerator
from .descriptions import build_short_description
from . import titles
"""
    )

    assert _resolve_imported_modules("youtube_automation.domains.metadata.localizations", tree) == {
        "youtube_automation.domains.metadata.service",
        "youtube_automation.domains.metadata.titles",
        "youtube_automation.domains.metadata",
        "youtube_automation.domains.metadata.descriptions",
    }


def test_dependency_import_collection_rejects_unallowed_absolute_child_module() -> None:
    tree = ast.parse(
        "from youtube_automation.domains.metadata import localizations\n"
    )

    imported = _resolve_imported_modules(f"{_METADATA_ROOT}.service", tree)

    assert imported == {f"{_METADATA_ROOT}.localizations"}
    assert not imported <= {
        f"{_METADATA_ROOT}.titles",
        f"{_METADATA_ROOT}.descriptions",
        f"{_METADATA_ROOT}.tags",
    }


def test_domain_dependency_edges_are_one_way() -> None:
    allowed = {
        f"{_DOWNLOADED_ROOT}.workflow": {f"{_DOWNLOADED_ROOT}.models"},
        f"{_DOWNLOADED_ROOT}.validation": {
            f"{_DOWNLOADED_ROOT}.workflow",
            f"{_DOWNLOADED_ROOT}.models",
        },
        f"{_DOWNLOADED_ROOT}.archive": {f"{_DOWNLOADED_ROOT}.models"},
        f"{_DOWNLOADED_ROOT}.apply": {
            f"{_DOWNLOADED_ROOT}.archive",
            f"{_DOWNLOADED_ROOT}.workflow",
            f"{_DOWNLOADED_ROOT}.models",
        },
        f"{_METADATA_ROOT}.service": {
            f"{_METADATA_ROOT}.titles",
            f"{_METADATA_ROOT}.descriptions",
            f"{_METADATA_ROOT}.tags",
            f"{_METADATA_ROOT}.localizations",
        },
        f"{_METADATA_ROOT}.localizations": {
            f"{_METADATA_ROOT}.titles",
            f"{_METADATA_ROOT}.descriptions",
        },
    }

    for module_name in _DOMAIN_MODULES:
        tree = ast.parse(_module_path(module_name).read_text(encoding="utf-8"))
        imported = _resolve_imported_modules(module_name, tree)
        domain_prefix = _SUNO_ROOT if module_name.startswith(_DOWNLOADED_ROOT) else _METADATA_ROOT
        domain_imports = {name for name in imported if name.startswith(domain_prefix)}

        assert domain_imports <= allowed.get(module_name, set()), module_name


def test_legacy_modules_are_removed() -> None:
    utils_dir = _ROOT / "src" / "youtube_automation" / "utils"

    assert [name for name in _LEGACY_MODULES if (utils_dir / name).exists()] == []


def test_active_files_have_no_legacy_owner_references() -> None:
    roots = (
        _ROOT / "src",
        _ROOT / "tests",
        _ROOT / ".claude" / "skills",
        _ROOT / "docs",
        _ROOT / "examples",
    )
    legacy_names = tuple(f"youtube_automation.utils.{name[:-3]}" for name in _LEGACY_MODULES)

    offenders: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or "docs/audits" in path.as_posix():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if any(legacy in text for legacy in legacy_names):
                offenders.append(str(path.relative_to(_ROOT)))

    assert offenders == []


def test_payload_contract_and_route_live_in_models() -> None:
    models = importlib.import_module(f"{_DOWNLOADED_ROOT}.models")

    payload = models.parse_downloaded_payload(
        {
            "file_count": 2,
            "format": "mp3",
            "download_path": "/tmp/download.zip",
            "suno_playlist_url": "https://suno.ai/playlist/1",
        }
    )

    assert payload.file_count == 2
    assert payload.format == "mp3"
    assert models.collection_downloaded_route("jazz set") == "/collections/jazz%20set/downloaded"


@pytest.mark.parametrize(
    "value",
    [None, {"file_count": True, "format": "mp3"}, {"file_count": 1, "format": "flac", "download_path": "/x"}],
)
def test_payload_contract_rejects_invalid_root_values(value: object) -> None:
    models = importlib.import_module(f"{_DOWNLOADED_ROOT}.models")

    with pytest.raises(models.DownloadedPayloadError):
        models.parse_downloaded_payload(value)


def test_workflow_count_preserves_explicit_override() -> None:
    workflow = importlib.import_module(f"{_DOWNLOADED_ROOT}.workflow")

    result = workflow.expected_download_count(3, explicit_expected=5)

    assert result == 5


def test_suno_prompt_reader_rejects_missing_and_malformed_files(tmp_path: Path) -> None:
    prompts = importlib.import_module(f"{_SUNO_ROOT}.prompts")

    with pytest.raises(ValueError):
        prompts.read_suno_prompt_entries(tmp_path)

    prompt_path = tmp_path / "20-documentation" / "suno-prompts.json"
    prompt_path.parent.mkdir()
    prompt_path.write_text('{"entries": {}}', encoding="utf-8")

    with pytest.raises(ValueError):
        prompts.read_suno_prompt_entries(tmp_path)


def test_metadata_leaf_helpers_keep_short_description_edge_contract() -> None:
    descriptions = importlib.import_module(f"{_METADATA_ROOT}.descriptions")
    config = SimpleNamespace(
        audio=SimpleNamespace(target_duration_min=None),
        meta=SimpleNamespace(channel_name="Night BGM"),
    )

    result = descriptions.build_short_description(config, collection_name="Rain", cc_video_url="")

    assert "Rain (Full collection) | Night BGM" in result
    assert "♫ Full" not in result
    assert result.endswith("#Shorts")


def test_metadata_generation_families_are_owned_by_leaf_modules() -> None:
    descriptions = importlib.import_module(f"{_METADATA_ROOT}.descriptions")
    tags = importlib.import_module(f"{_METADATA_ROOT}.tags")
    titles = importlib.import_module(f"{_METADATA_ROOT}.titles")

    assert descriptions.build_complete_collection_description(
        title="Rain",
        timestamp_body="00:00 Intro",
        opening="Opening",
        sub_opening="Sub opening",
        usage_header="Usage",
        usage_lines=["Line"],
        perfect_for_header="Perfect for",
        perfect_for_lines="• Study",
        channel_link_header="Channel:",
        cta_subscribe="Subscribe",
        tagline="Tagline",
        hashtag_line="#BGM",
    ).startswith("🎵 Rain\n\n00:00 Intro")
    assert tags.build_collection_tags(["ambient"]) == ["ambient"]
    assert tags.build_short_tags(["ambient"], ["rain"]) == ["Shorts", "ambient", "rain"]
    assert titles.build_collection_title("{theme} BGM", {"theme": "Rain"}, context="test") == "Rain BGM"
    assert titles.build_short_title("Rain", "Night BGM") == "Rain ✦ Night BGM #Shorts"


def test_short_localizations_are_owned_by_localizations_leaf() -> None:
    descriptions = importlib.import_module(f"{_METADATA_ROOT}.descriptions")
    localizations = importlib.import_module(f"{_METADATA_ROOT}.localizations")

    assert localizations.build_short_localizations.__module__ == localizations.__name__
    assert not hasattr(descriptions, "build_short_localizations")


def test_metadata_private_helpers_are_owned_by_their_leaf_modules() -> None:
    titles = importlib.import_module(f"{_METADATA_ROOT}.titles")
    localizations = importlib.import_module(f"{_METADATA_ROOT}.localizations")

    assert titles._extract_pattern_key("01-pattern-b1-song") == "b1"
    assert localizations._localized_title_values.__module__ == localizations.__name__
    assert localizations._localized_title_values(scene_phrase="Rain", activities="Study", scene_emoji="☔") == {
        "scene_phrase": "Rain",
        "activities": "Study",
        "scene_emoji": "☔",
    }
