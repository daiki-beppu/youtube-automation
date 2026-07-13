"""Chrome 拡張のローカル検証と CI の pnpm 版数契約を検証する。"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_EXTENSION_NAMES = ("suno-helper", "distrokid-helper")
_NIX_PNPM = "11.12.0"
_WORKFLOW_PNPM = "11.12.0"
_DOCUMENTED_PNPM = "11.11.0"
_PINNED_COMMAND = f"npx -y pnpm@{_DOCUMENTED_PNPM}"


def _read(path: str) -> str:
    return (_REPO_ROOT / path).read_text(encoding="utf-8")


def _workflow(path: str) -> dict[str, object]:
    loaded = yaml.safe_load(_read(path))
    assert isinstance(loaded, dict)
    return loaded


def _workspace_settings(name: str) -> dict[str, object]:
    loaded = yaml.safe_load(_read(f"extensions/{name}/pnpm-workspace.yaml"))
    assert isinstance(loaded, dict)
    return loaded


def _pnpm_setup_versions(path: str) -> list[object]:
    jobs = _workflow(path)["jobs"]
    assert isinstance(jobs, dict)
    versions: list[object] = []
    for job in jobs.values():
        assert isinstance(job, dict)
        steps = job.get("steps", [])
        assert isinstance(steps, list)
        for step in steps:
            assert isinstance(step, dict)
            if step.get("uses") == "pnpm/action-setup@v4":
                with_section = step.get("with")
                assert isinstance(with_section, dict)
                versions.append(with_section.get("version"))
    return versions


def test_extensions_shell_contains_only_the_node_toolchain() -> None:
    flake = _read("flake.nix")
    extensions_shell = re.search(
        r"(?ms)^(?P<indent>[ \t]*)devShells\.extensions\s*="
        r"\s*pkgs\.mkShell\s*\{"
        r"\s*packages\s*=\s*with pkgs;\s*\[(?P<packages>.*?)\];"
        r"\s*\};",
        flake,
    )

    assert extensions_shell is not None
    packages = extensions_shell.group("packages").split()
    assert packages == ["nodejs_24", "pnpmLatest"]

    default_shell = re.search(r"(?m)^(?P<indent>[ \t]*)devShells\.default\s*=", flake)
    assert default_shell is not None
    assert extensions_shell.group("indent") == default_shell.group("indent")

    block = extensions_shell.group(0)
    for excluded in ("python311", "uv", "ffmpeg", "lefthook", "shellHook"):
        assert excluded not in block


def test_both_extensions_pin_the_nix_pnpm() -> None:
    for name in _EXTENSION_NAMES:
        package = json.loads(_read(f"extensions/{name}/package.json"))

        assert package["packageManager"] == f"pnpm@{_NIX_PNPM}"


def test_both_extensions_preserve_build_approval() -> None:
    for name in _EXTENSION_NAMES:
        assert _workspace_settings(name)["allowBuilds"] == {"esbuild": True, "spawn-sync": False}


def test_extensions_ci_uses_the_nix_pnpm_instead_of_a_setup_action() -> None:
    assert _pnpm_setup_versions(".github/workflows/extensions.yml") == []


def test_local_pnpm_store_is_ignored_and_has_no_tracked_project_metadata() -> None:
    assert ".pnpm-store/" in _read(".gitignore").splitlines()
    assert not list((_REPO_ROOT / ".pnpm-store" / "v10" / "projects").glob("*"))


def test_release_workflow_uses_the_pinned_pnpm_setup_action() -> None:
    versions = _pnpm_setup_versions(".github/workflows/release-extensions.yml")

    assert versions
    assert versions == [_WORKFLOW_PNPM] * len(versions)


def test_shared_docs_precede_commands_with_the_pinned_contract() -> None:
    extensions_readme = _read("extensions/README.md")
    development_doc = _read("docs/development.md")

    assert "## pnpm バージョン契約" in extensions_readme
    for name in _EXTENSION_NAMES:
        package = json.loads(_read(f"extensions/{name}/package.json"))

        assert name in extensions_readme
        assert f"{name}-{package['version']}-chrome.zip" in extensions_readme
    for command in ("install --frozen-lockfile", "build", "zip"):
        assert f"{_PINNED_COMMAND} -C extensions/<name> {command}" in extensions_readme
    assert _PINNED_COMMAND in development_doc
    assert "extensions/README.md::pnpm バージョン契約" in development_doc


def test_each_extension_readme_uses_the_pinned_contract() -> None:
    unpinned_command = re.compile(
        rf"(?<!@{re.escape(_DOCUMENTED_PNPM)} )\bpnpm (?:install|dev|build|zip|compile|test|exec)"
    )
    for name in _EXTENSION_NAMES:
        readme = _read(f"extensions/{name}/README.md")

        assert _PINNED_COMMAND in readme
        assert "extensions/README.md::pnpm バージョン契約" in readme
        assert f"{_PINNED_COMMAND} install --frozen-lockfile" in readme
        assert f"{_PINNED_COMMAND} build" in readme
        assert f"{_PINNED_COMMAND} zip" in readme
        assert unpinned_command.search(readme) is None


def test_suno_skill_uses_the_pinned_extension_build_path() -> None:
    suno_skill = _read(".claude/skills/suno/SKILL.md")

    assert f"{_PINNED_COMMAND} -C extensions/suno-helper install --frozen-lockfile" in suno_skill
    assert f"{_PINNED_COMMAND} -C extensions/suno-helper build" in suno_skill
    assert "extensions/README.md::pnpm バージョン契約" in suno_skill
    assert "`pnpm install && pnpm build`" not in suno_skill


def test_release_skill_verifies_both_zips_and_unchanged_lockfiles() -> None:
    release_skill = _read(".claude/skills/automation-release/SKILL.md")

    assert "for name in suno-helper distrokid-helper" in release_skill
    for command in ("install --frozen-lockfile", "build", "zip"):
        assert f'{_PINNED_COMMAND} -C "extensions/${{name}}" {command}' in release_skill
    assert ".output/${name}-${version}-chrome.zip" in release_skill
    assert (
        "git diff --exit-code -- extensions/suno-helper/pnpm-lock.yaml extensions/distrokid-helper/pnpm-lock.yaml"
    ) in release_skill
