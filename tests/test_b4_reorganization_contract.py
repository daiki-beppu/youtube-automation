"""Issue #2307 の新 owner と依存方向を固定する契約テスト。

対応表:

* R1-R3, R10-R15: 新しい domain/infrastructure owner の import smoke と
  source の依存方向。
* R4-R9: ``YouTubeClients`` の instance scope、cache 分離、reset。
* R16-R18: 旧 auth/root template/embedded renderer を新しい実行経路で
  置き換えるための物理契約は ``test_b4_auth_resource_contract.py`` で検証する。

旧実装の不在だけでは新仕様を証明できないため、主要テストは新 owner の
import、実行結果、依存 edge を観測する。
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "youtube_automation"

DOMAIN_MODULES = (
    "youtube_automation.domains.uploads.youtube",
    "youtube_automation.domains.uploads.policy",
    "youtube_automation.domains.uploads.preflight",
    "youtube_automation.domains.uploads.collection",
    "youtube_automation.domains.uploads.shorts",
    "youtube_automation.domains.youtube.channel_seed",
    "youtube_automation.domains.youtube.channel_settings",
    "youtube_automation.domains.youtube.video_listing",
)

LEGACY_AGENT_OWNERS = {
    "_collection_uploader_constants": (
        "youtube_automation.domains.uploads._collection_uploader_constants",
        "ACTION_COMPLETE_COLLECTION_UPLOADED",
    ),
    "_complete_collection_executor": (
        "youtube_automation.domains.uploads._complete_collection_executor",
        "CompleteCollectionExecutorMixin",
    ),
    "_complete_collection_strategy": (
        "youtube_automation.domains.uploads._complete_collection_strategy",
        "CompleteCollectionMixin",
    ),
    "_dedup_search": ("youtube_automation.domains.uploads._dedup_search", "DedupSearchMixin"),
    "_descriptions_md": ("youtube_automation.domains.uploads._descriptions_md", "DescriptionsMdMixin"),
    "_playlist_assignment": ("youtube_automation.domains.uploads._playlist_assignment", "PlaylistAssignmentMixin"),
    "_preflight": ("youtube_automation.domains.uploads._preflight", "PreflightMixin"),
    "_published_dates": ("youtube_automation.domains.uploads._published_dates", "PublishedDatesMixin"),
    "_tracking_io": ("youtube_automation.domains.uploads._tracking_io", "TrackingIOMixin"),
    "_uploader_constants": (
        "youtube_automation.domains.uploads._uploader_constants",
        "UPLOAD_SOURCE_EXISTING",
    ),
}

LEGACY_UTILS_TO_DOMAIN = {
    "upload_core": "youtube_automation.domains.uploads.youtube",
    "upload_policy": "youtube_automation.domains.uploads.policy",
    "preflight_checks": "youtube_automation.domains.uploads.preflight",
    "channel_seed": "youtube_automation.domains.youtube.channel_seed",
    "channel_settings": "youtube_automation.domains.youtube.channel_settings",
    "video_listing": "youtube_automation.domains.youtube.video_listing",
    "youtube_service": "youtube_automation.infrastructure.google.youtube",
    "exceptions": "youtube_automation.infrastructure.errors",
    "retry": "youtube_automation.infrastructure.retry",
    "secrets": "youtube_automation.infrastructure.secrets",
}

UPLOADER_ENTRYPOINTS = (
    "youtube_auto_uploader.py",
    "collection_uploader.py",
    "short_uploader.py",
)

CANONICAL_UPLOAD_OWNERS = {
    "CollectionUploader": "youtube_automation.domains.uploads.collection",
    "ShortUploader": "youtube_automation.domains.uploads.shorts",
    "YouTubeAutoUploader": "youtube_automation.domains.uploads.youtube",
}

INFRASTRUCTURE_MODULES = (
    "youtube_automation.infrastructure.google.youtube",
    "youtube_automation.infrastructure.auth.youtube",
    "youtube_automation.infrastructure.auth.client_secrets",
    "youtube_automation.infrastructure.auth.tokens",
    "youtube_automation.infrastructure.auth.redaction",
    "youtube_automation.infrastructure.browser",
    "youtube_automation.infrastructure.filesystem",
    "youtube_automation.infrastructure.media",
    "youtube_automation.infrastructure.process",
    "youtube_automation.infrastructure.errors",
    "youtube_automation.infrastructure.retry",
    "youtube_automation.infrastructure.secrets",
    "youtube_automation.infrastructure.cost_tracker",
)

UPLOAD_DOMAIN_PATHS = tuple(sorted((SRC / "domains" / "uploads").glob("*.py")))


def _module_path(module_name: str) -> Path:
    relative = module_name.removeprefix("youtube_automation.").replace(".", "/")
    return SRC / f"{relative}.py"


def _import_targets(module_name: str) -> set[str]:
    tree = ast.parse(_module_path(module_name).read_text(encoding="utf-8"))
    targets: set[str] = set()
    package = module_name.split(".")[:-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                targets.add(node.module)
            elif node.level:
                base = package[: len(package) - node.level + 1]
                if node.module:
                    targets.add(".".join((*base, node.module)))
                else:
                    targets.update(".".join((*base, alias.name)) for alias in node.names)
    return targets


def _source_calls(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            calls.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            calls.add(node.func.attr)
    return calls


def test_new_domain_and_infrastructure_modules_are_importable() -> None:
    expected = (*DOMAIN_MODULES, *INFRASTRUCTURE_MODULES)

    imported = [importlib.import_module(name).__name__ for name in expected]

    assert imported == list(expected)


@pytest.mark.parametrize("module_name", DOMAIN_MODULES)
def test_domain_modules_do_not_import_adapters_or_auth(module_name: str) -> None:
    imports = _import_targets(module_name)

    forbidden = (
        "youtube_automation.agents",
        "youtube_automation.scripts",
        "youtube_automation.cli",
        "youtube_automation.auth",
        "youtube_automation.infrastructure.auth",
        "googleapiclient",
    )
    assert not [target for target in imports if target.startswith(forbidden)]


def test_agents_do_not_import_scripts() -> None:
    offenders: list[str] = []

    for path in (SRC / "agents").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            if any(
                name == "youtube_automation.scripts" or name.startswith("youtube_automation.scripts.") for name in names
            ):
                offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_production_has_no_legacy_auth_or_global_client_consumers() -> None:
    forbidden_modules = {"youtube_automation.auth"}
    forbidden_names = {
        "ServiceRegistry",
        "_default_registry",
        "_get_handler",
        "get_youtube",
        "get_analytics",
        "get_reporting",
    }
    offenders: list[str] = []

    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = {alias.name for alias in node.names}
                if imported & forbidden_modules:
                    offenders.append(f"{path}:{sorted(imported & forbidden_modules)}")
            elif isinstance(node, ast.ImportFrom) and node.module in forbidden_modules:
                offenders.append(f"{path}:{node.module}")
            elif isinstance(node, ast.Name) and node.id in forbidden_names and isinstance(node.ctx, ast.Load):
                offenders.append(f"{path}:{node.id}")

    assert offenders == []


def test_legacy_agent_owners_have_canonical_domain_implementations() -> None:
    for legacy_name, (owner_name, symbol_name) in LEGACY_AGENT_OWNERS.items():
        legacy_path = SRC / "agents" / f"{legacy_name}.py"
        owner = importlib.import_module(owner_name)

        assert not legacy_path.exists(), legacy_path
        assert hasattr(owner, symbol_name), f"{owner_name}.{symbol_name}"


@pytest.mark.parametrize("filename", UPLOADER_ENTRYPOINTS)
def test_uploader_agents_are_thin_main_adapters(filename: str) -> None:
    path = SRC / "agents" / filename
    tree = ast.parse(path.read_text(encoding="utf-8"))

    classes = [node.name for node in tree.body if isinstance(node, ast.ClassDef)]

    assert classes == []
    assert any(isinstance(node, ast.FunctionDef) and node.name == "main" for node in tree.body)


@pytest.mark.parametrize(
    ("filename", "owner_module", "owner_name"),
    [
        ("youtube_auto_uploader.py", "youtube_automation.domains.uploads.youtube", "YouTubeAutoUploader"),
        ("collection_uploader.py", "youtube_automation.domains.uploads.collection", "CollectionUploader"),
        ("short_uploader.py", "youtube_automation.domains.uploads.shorts", "ShortUploader"),
    ],
)
def test_uploader_adapters_wire_canonical_owner_and_instance_clients(
    filename: str, owner_module: str, owner_name: str
) -> None:
    """各 command 入口は domain owner と instance client factory を配線する。"""
    path = SRC / "agents" / filename
    tree = ast.parse(path.read_text(encoding="utf-8"))

    imports = {
        (node.module, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    }

    assert (owner_module, owner_name) in imports
    assert (
        "youtube_automation.infrastructure.google.youtube",
        "create_authenticated_youtube_clients",
    ) in imports


def test_upload_application_classes_are_owned_by_canonical_domain_modules() -> None:
    owners = {
        name: getattr(importlib.import_module(module_name), name)
        for name, module_name in CANONICAL_UPLOAD_OWNERS.items()
    }

    assert {name: cls.__module__ for name, cls in owners.items()} == CANONICAL_UPLOAD_OWNERS
    assert not (SRC / "application" / "uploads").exists()


def test_canonical_upload_owner_contains_implementation() -> None:
    module = importlib.import_module("youtube_automation.domains.uploads.youtube")
    uploader = module.ResumableUploader

    assert uploader.__module__ == "youtube_automation.domains.uploads.youtube"
    assert {"upload_video", "set_thumbnail", "_resumable_upload"}.issubset(vars(uploader))
    assert all(
        getattr(uploader, name).__module__ == module.__name__
        for name in ("upload_video", "set_thumbnail", "_resumable_upload")
    )


@pytest.mark.parametrize("path", UPLOAD_DOMAIN_PATHS)
def test_upload_domain_modules_do_not_perform_external_io(path: Path) -> None:
    calls = _source_calls(path)

    forbidden_calls = {
        "open",
        "read_text",
        "write_text",
        "read_bytes",
        "write_bytes",
        "exists",
        "mkdir",
        "rename",
        "is_file",
        "glob",
    }
    assert calls.isdisjoint(forbidden_calls)

    module_name = "youtube_automation." + ".".join(path.relative_to(SRC).with_suffix("").parts)
    imports = _import_targets(module_name)
    assert not [target for target in imports if target == "urllib" or target.startswith("urllib.")]
    assert not [target for target in imports if target == "subprocess" or target.startswith("subprocess.")]
    assert not [target for target in imports if target == "tempfile" or target.startswith("tempfile.")]
    assert not [target for target in imports if target == "googleapiclient" or target.startswith("googleapiclient.")]


def test_upload_domain_routes_youtube_requests_through_google_boundary() -> None:
    for path in UPLOAD_DOMAIN_PATHS:
        module_name = "youtube_automation." + ".".join(path.relative_to(SRC).with_suffix("").parts)
        assert "youtube_automation.infrastructure.retry" not in _import_targets(module_name)


def test_upload_domain_does_not_execute_google_requests_directly() -> None:
    offenders: list[str] = []
    for path in UPLOAD_DOMAIN_PATHS:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "execute":
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")

    assert offenders == []


def test_upload_and_infrastructure_owners_are_canonical() -> None:
    """移行後の公開 owner と infrastructure 実装の二重所有を防ぐ。"""
    uploader = importlib.import_module("youtube_automation.domains.uploads.youtube").ResumableUploader
    assert uploader.__module__ == "youtube_automation.domains.uploads.youtube"
    assert not any((SRC / "utils" / f"{name}.py").exists() for name in LEGACY_UTILS_TO_DOMAIN)
    assert (SRC / "infrastructure" / "cost_tracker.py").exists()
    assert not (SRC / "utils" / "cost_tracker.py").exists()


def test_oauth_cli_propagates_unexpected_exception(monkeypatch) -> None:
    from youtube_automation.infrastructure.auth import youtube as oauth_handler

    sentinel = "access-token-secret-value"
    handler = MagicMock()
    handler.authenticate.side_effect = RuntimeError(sentinel)
    monkeypatch.setattr(oauth_handler, "YouTubeOAuthHandler", lambda: handler)
    with pytest.raises(RuntimeError, match=sentinel):
        oauth_handler.main([])


def test_benchmark_script_uses_instance_scoped_youtube_clients(monkeypatch) -> None:
    benchmark = importlib.import_module("bench.bench_benchmark_collector")
    clients = SimpleNamespace(youtube=object())
    handler = object()

    monkeypatch.setattr(
        "youtube_automation.infrastructure.auth.youtube.YouTubeOAuthHandler",
        lambda: handler,
    )
    monkeypatch.setattr(
        "youtube_automation.infrastructure.google.youtube.YouTubeClients",
        lambda *, full_handler: clients,
    )

    assert benchmark._youtube_client() is clients.youtube


def _handler(*, youtube: object = None, readonly: object = None) -> MagicMock:
    handler = MagicMock()
    handler.get_youtube_service.return_value = youtube
    handler.authenticate.return_value = SimpleNamespace(kind="credentials")
    return handler


def test_youtube_clients_caches_full_and_readonly_services_per_instance() -> None:
    full_handler = _handler(youtube="full-service")
    readonly_handler = _handler(youtube="readonly-service")
    module = importlib.import_module("youtube_automation.infrastructure.google.youtube")
    clients = module.YouTubeClients(full_handler=full_handler, readonly_handler=readonly_handler)

    full_first = clients.youtube
    readonly_first = clients.youtube_readonly
    full_second = clients.youtube
    readonly_second = clients.youtube_readonly

    assert full_first is full_second
    assert readonly_first is readonly_second
    assert full_first == "full-service"
    assert readonly_first == "readonly-service"
    full_handler.get_youtube_service.assert_called_once_with()
    readonly_handler.get_youtube_service.assert_called_once_with()


def test_youtube_clients_reset_rebuilds_only_its_own_scope() -> None:
    first_handler = _handler(youtube="first")
    second_handler = _handler(youtube="second")
    module = importlib.import_module("youtube_automation.infrastructure.google.youtube")
    first = module.YouTubeClients(full_handler=first_handler)
    second = module.YouTubeClients(full_handler=second_handler)

    assert first.youtube == "first"
    assert second.youtube == "second"
    first.reset()
    rebuilt = first.youtube

    assert rebuilt == "first"
    assert first_handler.get_youtube_service.call_count == 2
    second_handler.get_youtube_service.assert_called_once_with()


def test_youtube_clients_reset_invalidates_every_cached_api_family() -> None:
    full_handler = _handler(youtube="full-1")
    readonly_handler = _handler(youtube="readonly-1")
    full_credentials = SimpleNamespace(kind="full-credentials")
    readonly_credentials = SimpleNamespace(kind="readonly-credentials")
    full_handler.authenticate.return_value = full_credentials
    readonly_handler.authenticate.return_value = readonly_credentials
    module = importlib.import_module("youtube_automation.infrastructure.google.youtube")
    builder = MagicMock(side_effect=["analytics-1", "reporting-1", "analytics-2", "reporting-2"])

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(module, "build", builder)
        clients = module.YouTubeClients(full_handler=full_handler, readonly_handler=readonly_handler)
        first = (clients.youtube, clients.youtube_readonly, clients.analytics, clients.reporting)
        clients.reset()
        second = (clients.youtube, clients.youtube_readonly, clients.analytics, clients.reporting)

    assert first == ("full-1", "readonly-1", "analytics-1", "reporting-1")
    assert second == ("full-1", "readonly-1", "analytics-2", "reporting-2")
    assert full_handler.get_youtube_service.call_count == 2
    assert readonly_handler.get_youtube_service.call_count == 2
    full_handler.authenticate.assert_not_called()
    assert readonly_handler.authenticate.call_count == 4


def test_youtube_clients_uses_full_handler_for_readonly_scope_when_not_provided() -> None:
    full_handler = _handler(youtube="shared-readonly-service")
    module = importlib.import_module("youtube_automation.infrastructure.google.youtube")
    clients = module.YouTubeClients(full_handler=full_handler)

    readonly_service = clients.youtube_readonly

    assert readonly_service == "shared-readonly-service"
    full_handler.get_youtube_service.assert_called_once_with()


def test_youtube_clients_keeps_analytics_and_reporting_caches_separate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    full_handler = _handler(youtube="youtube")
    readonly_handler = _handler(youtube="readonly")
    full_credentials = SimpleNamespace(kind="full-credentials")
    readonly_credentials = SimpleNamespace(kind="readonly-credentials")
    full_handler.authenticate.return_value = full_credentials
    readonly_handler.authenticate.return_value = readonly_credentials
    module = importlib.import_module("youtube_automation.infrastructure.google.youtube")
    builder = MagicMock(side_effect=["analytics-service", "reporting-service"])
    monkeypatch.setattr(module, "build", builder)
    clients = module.YouTubeClients(full_handler=full_handler, readonly_handler=readonly_handler)

    analytics_first = clients.analytics
    reporting_first = clients.reporting
    analytics_second = clients.analytics
    reporting_second = clients.reporting

    assert analytics_first is analytics_second
    assert reporting_first is reporting_second
    assert analytics_first == "analytics-service"
    assert reporting_first == "reporting-service"
    assert builder.call_count == 2
    assert {call.args[:2] for call in builder.call_args_list} == {
        ("youtubeAnalytics", "v2"),
        ("youtubereporting", "v1"),
    }
    assert all(call.kwargs["credentials"] is readonly_credentials for call in builder.call_args_list)
    full_handler.authenticate.assert_not_called()
    assert readonly_handler.authenticate.call_count == 2
