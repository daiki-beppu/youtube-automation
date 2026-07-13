"""Chrome 拡張のローカル検証と CI の pnpm 版数契約を検証する。"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_EXTENSION_NAMES = ("suno-helper", "distrokid-helper")
_NIX_PNPM = "11.12.0"
_LEGACY_PNPM = "11.11.0"
_LEGACY_NPX_COMMAND = f"npx -y pnpm@{_LEGACY_PNPM}"
_NIX_COMMAND = "nix develop .#extensions --command pnpm"
_VERIFY_SCRIPT_PATH = ".claude/skills/automation-release/references/verify-extensions.sh"
_CURRENT_CONTRACT_DOCS = (
    "extensions/README.md",
    "extensions/suno-helper/README.md",
    "extensions/distrokid-helper/README.md",
    "docs/development.md",
    ".claude/skills/suno/SKILL.md",
    ".claude/skills/automation-release/SKILL.md",
    ".claude/skills/automation-release/references/extension-release-checklist.md",
)


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


def test_release_workflow_uses_the_nix_pnpm_instead_of_a_setup_action() -> None:
    assert _pnpm_setup_versions(".github/workflows/release-extensions.yml") == []


def test_shared_docs_precede_commands_with_the_pinned_contract() -> None:
    extensions_readme = _read("extensions/README.md")
    development_doc = _read("docs/development.md")

    assert "## pnpm バージョン契約" in extensions_readme
    for name in _EXTENSION_NAMES:
        assert name in extensions_readme
    assert "Node 24 / pnpm 11.12.0" in extensions_readme
    assert f"bash {_VERIFY_SCRIPT_PATH} [<name>]" in extensions_readme
    assert "期待名 zip が唯一の1件" in extensions_readme
    assert "Node 24 / pnpm 11.12.0" in development_doc
    assert "nix develop .#extensions --command pnpm" in development_doc
    assert "`--ignore-workspace`" in extensions_readme
    assert "`--ignore-workspace`" in development_doc
    assert _LEGACY_PNPM not in extensions_readme
    assert _LEGACY_PNPM not in development_doc
    assert _LEGACY_NPX_COMMAND not in extensions_readme
    assert _LEGACY_NPX_COMMAND not in development_doc
    assert "extensions/README.md::pnpm バージョン契約" in development_doc


def test_each_extension_readme_uses_the_nix_extensions_shell() -> None:
    for name in _EXTENSION_NAMES:
        readme = _read(f"extensions/{name}/README.md")

        assert "Node 24 / pnpm 11.12.0" in readme
        assert "extensions/README.md::pnpm バージョン契約" in readme
        for command in ("install --frozen-lockfile", "build", "zip"):
            assert f"{_NIX_COMMAND} -C extensions/{name} {command}" in readme
        assert _LEGACY_PNPM not in readme
        assert _LEGACY_NPX_COMMAND not in readme


def test_suno_skill_uses_the_nix_extensions_shell() -> None:
    suno_skill = _read(".claude/skills/suno/SKILL.md")

    assert "Nix extensions shell（Node 24 / pnpm 11.12.0）" in suno_skill
    assert f"{_NIX_COMMAND} -C extensions/suno-helper install --frozen-lockfile" in suno_skill
    assert f"{_NIX_COMMAND} -C extensions/suno-helper build" in suno_skill
    assert "extensions/README.md::pnpm バージョン契約" in suno_skill
    assert _LEGACY_PNPM not in suno_skill
    assert _LEGACY_NPX_COMMAND not in suno_skill


def test_current_extension_contract_docs_have_no_legacy_pnpm_command() -> None:
    for path in _CURRENT_CONTRACT_DOCS:
        text = _read(path)

        assert _LEGACY_PNPM not in text, path
        assert "npx -y pnpm@" not in text, path


def test_release_skill_delegates_extension_verification_to_single_source() -> None:
    release_skill = _read(".claude/skills/automation-release/SKILL.md")
    release_checklist = _read(".claude/skills/automation-release/references/extension-release-checklist.md")
    verify_script = _read(_VERIFY_SCRIPT_PATH)
    changelog = _read("CHANGELOG.md")

    invocation = f"bash {_VERIFY_SCRIPT_PATH}"
    assert invocation in release_skill
    assert invocation in release_checklist
    assert "nix develop .#extensions --command pnpm -C" not in release_skill
    assert "nix develop .#extensions --command pnpm -C" not in release_checklist
    assert "extension_names=(suno-helper distrokid-helper)" in verify_script
    for command in ("install --frozen-lockfile", "build", "zip"):
        assert f'nix develop .#extensions --command pnpm -C "${{extension_dir}}" {command}' in verify_script
    assert "node_version} != v24.*" in verify_script
    assert "pnpm_version} != 11.12.0" in verify_script
    assert "zip_path=" in verify_script
    assert 'git diff --exit-code -- "${lockfiles[@]}"' in verify_script
    assert "--ignore-workspace" not in verify_script
    for document in (release_skill, release_checklist):
        assert "Node 24 / pnpm 11.12.0" in document
        assert "ambient `node` / `pnpm`" in document
        assert "`--ignore-workspace`" in document
        assert "`pnpm install --frozen-lockfile` → `pnpm build` → `pnpm zip`" in document
        assert "期待名 zip が唯一の1件" in document
        assert "lockfile に差分がない" in document
    assert "`pnpm -v` が 9 系" not in release_skill
    unreleased = changelog.split("## [Unreleased]", maxsplit=1)[1].split("\n## [", maxsplit=1)[0]
    issue_entry = next(line for line in unreleased.splitlines() if "#1956" in line)
    assert "Nix extensions shell 契約（Node 24 / pnpm 11.12.0" in issue_entry
    assert "frozen install → build → zip" in issue_entry
    assert "期待名 zip" in issue_entry
    assert "lockfile 無差分" in issue_entry


def test_release_skill_places_hard_gates_and_completion_criteria_in_first_60_lines() -> None:
    first_60_lines = "\n".join(_read(".claude/skills/automation-release/SKILL.md").splitlines()[:60])

    assert "## Hard Gates / 完了条件" in first_60_lines
    assert "non-zeroならreleaseを停止" in first_60_lines
    assert "承認前にpushしない" in first_60_lines
    assert "extension prepare完了" in first_60_lines
    assert "extension publish完了" in first_60_lines


def test_release_skill_requires_exactly_two_named_zip_assets() -> None:
    release_skill = _read(".claude/skills/automation-release/SKILL.md")

    assert 'test "${zip_count}" -eq 2' in release_skill
    assert "^suno-helper-[0-9]+\\.[0-9]+\\.[0-9]+-chrome\\.zip$" in release_skill
    assert "^distrokid-helper-[0-9]+\\.[0-9]+\\.[0-9]+-chrome\\.zip$" in release_skill
    assert "件数過不足・重複・別名zipがあれば停止" in release_skill
