"""Dashboard の実ソース・依存・runtime 境界を直接検証する。"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from urllib.request import urlopen

from youtube_automation.commands.analytics.dashboard import create_server

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
STATIC_IMPORT = re.compile(r"""(?:from\s+|import\s*)["']([^"']+)["']""")


def _dashboard_imports() -> list[tuple[Path, str]]:
    imports: list[tuple[Path, str]] = []
    for path in sorted((DASHBOARD / "src").rglob("*")):
        if path.suffix not in {".ts", ".tsx"}:
            continue
        for specifier in STATIC_IMPORT.findall(path.read_text(encoding="utf-8")):
            imports.append((path.relative_to(ROOT), specifier))
    return imports


def test_dashboard_source_does_not_cross_extension_or_removed_package_boundaries() -> None:
    forbidden = ("extensions/shared-ui", "packages/")

    violations = [
        f"{path}: {specifier}"
        for path, specifier in _dashboard_imports()
        if any(boundary in specifier for boundary in forbidden)
    ]

    assert violations == []


def test_dashboard_dependency_graph_has_no_legacy_ui_or_workspace_package() -> None:
    package = json.loads((DASHBOARD / "package.json").read_text(encoding="utf-8"))
    dependencies = {
        **package.get("dependencies", {}),
        **package.get("devDependencies", {}),
    }

    assert not any(name.lower().replace("-", " ") == "spell ui" for name in dependencies)
    assert not any(str(version).startswith("workspace:") for version in dependencies.values())
    assert not (ROOT / "packages").exists()


def test_python_dashboard_runtime_serves_the_bundled_distribution() -> None:
    server = create_server(port=0, channel_paths=[])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"http://127.0.0.1:{server.server_port}/", timeout=5) as response:
            status = response.status
            content_type = response.headers.get_content_type()
            body = response.read().decode("utf-8")
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert status == 200
    assert content_type == "text/html"
    assert "YouTube Analytics Dashboard" in body
