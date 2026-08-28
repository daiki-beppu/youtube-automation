"""運用者向け公開ドキュメントサイトの CI・配布・文書境界を検証する。"""

from __future__ import annotations

import re
import subprocess
import tarfile
import tomllib
import zipfile
from pathlib import Path

import yaml

from tests.helpers.paths import REPO_ROOT

ROOT = REPO_ROOT
WORKFLOW_PATH = ROOT / ".github/workflows/site.yml"
OPERATOR_DOC_SOURCES = (
    "ONBOARDING.md",
    "docs/tool-setup.md",
    "docs/oauth-setup.md",
    "docs/features.md",
    "docs/workflow-cheatsheet.md",
    "docs/chrome-extension-install-guide.md",
    "docs/dashboard.md",
    "docs/channel-workspace-migration.md",
    "docs/cloud-execution.md",
    "docs/live-streaming.md",
    "docs/live-chat-reply.md",
    "docs/ambient-layers.md",
)
NONPUBLIC_DOC_PREFIXES = (
    "docs/adr/",
    "docs/audits/",
    "docs/investigations/",
    "docs/research/",
    "docs/strategy/",
    "docs/benchmarks/",
)


def _workflow() -> dict[str, object]:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _triggers(workflow: dict[str, object]) -> dict[str, object]:
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict)
    return triggers


def _operator_doc_sources() -> tuple[str, ...]:
    source = (ROOT / "site/operator-doc-source.ts").read_text(encoding="utf-8")
    map_block = source.split("export const operatorDocMap = [", maxsplit=1)[1].split("] as const", maxsplit=1)[0]
    return tuple(re.findall(r'source:\s*"([^"]+)"', map_block))


def test_site_workflow_checks_every_stacked_pull_request_and_main_push() -> None:
    workflow = _workflow()
    triggers = _triggers(workflow)
    expected_paths = [
        "site/**",
        ".claude/skills/**",
        "docs/release-notes/**",
        *OPERATOR_DOC_SOURCES,
        ".github/workflows/site.yml",
        "flake.nix",
        "flake.lock",
    ]

    pull_request = triggers["pull_request"]
    assert isinstance(pull_request, dict)
    assert "branches" not in pull_request
    assert pull_request["paths"] == expected_paths
    assert triggers["push"] == {"branches": ["main"], "paths": expected_paths}


def test_site_content_map_is_an_existing_exact_allowlist() -> None:
    sources = _operator_doc_sources()

    assert sources == OPERATOR_DOC_SOURCES
    assert all((ROOT / source).is_file() for source in sources)
    assert not any(source.startswith(prefix) for source in sources for prefix in NONPUBLIC_DOC_PREFIXES)


def test_site_workflow_uses_frozen_dependencies_and_all_quality_gates() -> None:
    workflow = _workflow()
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    site = jobs["site"]
    assert isinstance(site, dict)
    steps = site["steps"]
    assert isinstance(steps, list)

    assert steps[0]["uses"] == "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
    assert steps[1]["uses"] == "cachix/install-nix-action@630ae543ea3a38a9a4166f03376c02c50f408342"
    commands = [step.get("run") for step in steps]
    assert commands == [
        None,
        None,
        "nix develop .#extensions --command pnpm -C site install --frozen-lockfile",
        "nix develop .#extensions --command pnpm -C site check",
        "nix develop .#extensions --command pnpm -C site build",
        "nix develop .#extensions --command pnpm -C site test",
    ]
    assert not any("deploy" in str(step).lower() for step in steps)


def test_site_generated_files_are_explicitly_ignored() -> None:
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert {"site/node_modules/", "site/.blume/", "site/dist/"} <= set(ignored)


def test_python_build_configuration_excludes_site_workspace() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    wheel = project["tool"]["hatch"]["build"]["targets"]["wheel"]
    sdist = project["tool"]["hatch"]["build"]["targets"]["sdist"]

    assert wheel["packages"] == ["src/youtube_automation"]
    assert all(not str(source).startswith("site") for source in wheel.get("force-include", {}))
    assert all(not str(source).startswith("site") for source in sdist["only-include"])
    assert all(not str(source).startswith("site") for source in sdist.get("force-include", {}))

    wheel_operator_sources = set(wheel.get("force-include", {})) & set(OPERATOR_DOC_SOURCES)
    sdist_operator_sources = set(sdist["only-include"]) & set(OPERATOR_DOC_SOURCES)
    assert wheel_operator_sources == {
        "docs/features.md",
        "docs/workflow-cheatsheet.md",
    }
    assert sdist_operator_sources == {
        "ONBOARDING.md",
        "docs/tool-setup.md",
        "docs/oauth-setup.md",
        "docs/features.md",
        "docs/workflow-cheatsheet.md",
    }


def test_built_python_archives_do_not_contain_site_workspace(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    result = subprocess.run(
        ["uv", "build", "--out-dir", str(dist)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    wheel = next(dist.glob("*.whl"))
    sdist = next(dist.glob("*.tar.gz"))
    with zipfile.ZipFile(wheel) as archive:
        wheel_members = archive.namelist()
    with tarfile.open(sdist) as archive:
        sdist_members = [Path(member.name).parts[1:] for member in archive.getmembers()]

    assert not [member for member in wheel_members if member == "site" or member.startswith("site/")]
    assert not [parts for parts in sdist_members if parts and parts[0] == "site"]


def test_repository_docs_define_the_site_as_a_typescript_exception_and_separate_distribution() -> None:
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    development = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    architecture = (ROOT / "docs/architecture.md").read_text(encoding="utf-8")
    adr = (ROOT / "docs/adr/0023-release-notes-site.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "`site/`" in claude and "TypeScript" in claude
    assert "## リリースノートサイト開発" in development
    assert "Python wheel / sdist には同梱しない" in development
    assert "**operator documentation site**" in architecture
    assert "site/operator-doc-source.ts" in architecture
    assert "read-in-place" in architecture
    assert "allowlist" in architecture
    assert all(source in architecture for source in OPERATOR_DOC_SOURCES)
    assert all(prefix in architecture for prefix in NONPUBLIC_DOC_PREFIXES)
    assert "Python wheel / sdist" in architecture
    assert "Blume" in adr and "Cloudflare Pages" in adr
    assert "公開リリースノート" in readme
