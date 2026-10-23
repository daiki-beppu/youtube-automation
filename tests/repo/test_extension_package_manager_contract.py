"""Chrome 拡張のローカル検証と CI の pnpm 版数契約を検証する。"""

from __future__ import annotations

import json
import re

import yaml

from tests.helpers.paths import REPO_ROOT

_REPO_ROOT = REPO_ROOT
_EXTENSION_NAMES = ("suno-helper", "distrokid-helper", "community-helper")
_EXTENSION_README_NAMES = ("suno-helper", "distrokid-helper")
_PINNED_PNPM = "11.15.1"
_LEGACY_PNPM = "11.11.0"
_LEGACY_NPX_COMMAND = f"npx -y pnpm@{_LEGACY_PNPM}"
_SETUP_VP_ACTION = "voidzero-dev/setup-vp@68f39c78aaf39be468cabd2afb09c162574c84af"
_NODE_PACKAGE_DIRS = (
    "extensions",
    "extensions/suno-helper",
    "extensions/distrokid-helper",
    "extensions/community-helper",
    "extensions/shared-ui",
    "site",
    "audio-studio",
    "dashboard",
)
_NODE_WORKFLOWS = (
    ".github/workflows/extensions.yml",
    ".github/workflows/release-extensions.yml",
    ".github/workflows/site.yml",
    ".github/workflows/audio-studio.yml",
    ".github/workflows/dashboard.yml",
)
_VERIFY_SCRIPT_PATH = ".claude/skills/automation-release/references/verify-extensions.sh"
_CURRENT_CONTRACT_DOCS = (
    "extensions/README.md",
    "extensions/suno-helper/README.md",
    "extensions/distrokid-helper/README.md",
    "docs/development.md",
    ".claude/skills/music/references/prompt.md",
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


def _cd_pnpm(directory: str, command: str) -> str:
    return f"(cd {directory} && pnpm {command})"


def test_flake_no_longer_supplies_node_or_pnpm() -> None:
    """Node.js / pnpm は vp が供給し、Nix の devShell は Python 側だけを持つ。"""
    flake = _read("flake.nix")

    assert "devShells.extensions" not in flake
    assert "pnpmLatest" not in flake
    assert not re.search(r"\bnodejs(_\d+)?\b", flake)
    assert "devShells.default" in flake


def test_default_shell_sets_only_a_default_pnpm_worker_limit() -> None:
    """REQ-3078-01: macOS の libuv abort 回避として Worker 既定値 1 を devShell が持つ。"""
    flake = _read("flake.nix")
    default_shell = flake[flake.index("devShells.default") :]

    assert "if [ -z \"''${PNPM_MAX_WORKERS:-}\" ]; then" in default_shell
    assert "export PNPM_MAX_WORKERS=1" in default_shell
    assert flake.count("PNPM_MAX_WORKERS=1") == 1


def test_node_version_is_declared_once_at_the_repository_root() -> None:
    """vp と CI の setup-vp が読む Node の版は root の .node-version を正とする。"""
    assert _read(".node-version") == "24\n"


def test_every_node_package_pins_the_pnpm_version() -> None:
    """vp の pnpm shim は cwd の packageManager から版を解決する。"""
    for directory in _NODE_PACKAGE_DIRS:
        package = json.loads(_read(f"{directory}/package.json"))

        assert package["packageManager"] == f"pnpm@{_PINNED_PNPM}", directory


def test_node_workflows_set_up_node_with_vp_from_the_node_version_file() -> None:
    for path in _NODE_WORKFLOWS:
        jobs = _workflow(path)["jobs"]
        assert isinstance(jobs, dict)
        for job_name, job in jobs.items():
            assert isinstance(job, dict)
            steps = job.get("steps", [])
            assert isinstance(steps, list)
            runs = " ".join(str(step.get("run", "")) for step in steps if isinstance(step, dict))
            if "pnpm" not in runs and "verify-extensions.sh" not in runs:
                continue
            setup = [step for step in steps if str(step.get("uses", "")).startswith("voidzero-dev/setup-vp@")]
            assert len(setup) == 1, f"{path}::{job_name}"
            assert setup[0]["uses"] == _SETUP_VP_ACTION
            assert setup[0]["with"] == {"node-version-file": ".node-version", "run-install": False}
            assert ".#extensions" not in _read(path)


def test_all_extensions_pin_the_pnpm_version() -> None:
    for name in _EXTENSION_NAMES:
        package = json.loads(_read(f"extensions/{name}/package.json"))

        assert package["packageManager"] == f"pnpm@{_PINNED_PNPM}"


def test_all_extensions_preserve_build_approval() -> None:
    for name in _EXTENSION_NAMES:
        assert _workspace_settings(name)["allowBuilds"] == {"esbuild": True, "spawn-sync": False}


def test_extensions_ci_uses_vp_instead_of_a_pnpm_setup_action() -> None:
    assert _pnpm_setup_versions(".github/workflows/extensions.yml") == []


def test_local_pnpm_store_is_ignored_and_has_no_tracked_project_metadata() -> None:
    assert ".pnpm-store/" in _read(".gitignore").splitlines()
    assert not list((_REPO_ROOT / ".pnpm-store" / "v10" / "projects").glob("*"))


def test_release_workflow_uses_vp_instead_of_a_pnpm_setup_action() -> None:
    assert _pnpm_setup_versions(".github/workflows/release-extensions.yml") == []


def test_shared_docs_precede_commands_with_the_pinned_contract() -> None:
    extensions_readme = _read("extensions/README.md")
    development_doc = _read("docs/development.md")

    assert "## pnpm バージョン契約" in extensions_readme
    for name in _EXTENSION_NAMES:
        assert name in extensions_readme
    assert "Node 24 / pnpm 11.15.1" in extensions_readme
    assert f"bash {_VERIFY_SCRIPT_PATH} [<name>]" in extensions_readme
    assert "期待名 zip が唯一の1件" in extensions_readme
    assert "Node 24 / pnpm 11.15.1" in development_doc
    assert "vite-plus（`vp`）管理の Node 24 / pnpm 11.15.1" in development_doc
    assert "`.node-version`" in development_doc
    assert "`--ignore-workspace`" in extensions_readme
    assert "`--ignore-workspace`" in development_doc
    assert _LEGACY_PNPM not in extensions_readme
    assert _LEGACY_PNPM not in development_doc
    assert _LEGACY_NPX_COMMAND not in extensions_readme
    assert _LEGACY_NPX_COMMAND not in development_doc
    assert "extensions/README.md::pnpm バージョン契約" in development_doc


def test_each_extension_readme_uses_the_vp_toolchain() -> None:
    for name in _EXTENSION_README_NAMES:
        readme = _read(f"extensions/{name}/README.md")

        assert "Node 24 / pnpm 11.15.1" in readme
        assert "extensions/README.md::pnpm バージョン契約" in readme
        for command in (
            "install --frozen-lockfile",
            "build",
            "zip",
            "test",
            "exec playwright install --with-deps chromium",
            "test:e2e",
        ):
            assert _cd_pnpm(f"extensions/{name}", command) in readme
        assert ".output/chrome-mv3/manifest.json" in readme
        assert f".output/{name}-<package.json の version>-chrome.zip" in readme
        assert f"bash {_VERIFY_SCRIPT_PATH} {name}" in readme
        assert _LEGACY_PNPM not in readme
        assert _LEGACY_NPX_COMMAND not in readme


def test_shared_extension_readme_spells_out_the_command_flow() -> None:
    readme = _read("extensions/README.md")

    for command in (
        "install --frozen-lockfile",
        "build",
        "zip",
        "test",
        "exec playwright install --with-deps chromium",
        "test:e2e",
    ):
        assert _cd_pnpm("extensions/suno-helper", command) in readme
    assert "extensions/suno-helper/.output/chrome-mv3/manifest.json" in readme
    assert "extensions/suno-helper/.output/suno-helper-<package.json の version>-chrome.zip" in readme


def test_suno_skill_uses_the_vp_toolchain() -> None:
    suno_skill = _read(".claude/skills/music/references/prompt.md")

    assert "vite-plus（`vp`）管理の Node 24 / pnpm 11.15.1" in suno_skill
    assert _cd_pnpm("extensions/suno-helper", "install --frozen-lockfile") in suno_skill
    assert _cd_pnpm("extensions/suno-helper", "build") in suno_skill
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
    assert ".#extensions" not in release_skill
    assert ".#extensions" not in release_checklist
    assert "extension_names=(suno-helper distrokid-helper community-helper)" in verify_script
    for command in ("install --frozen-lockfile", "build", "zip"):
        assert f'(cd "${{extension_dir}}" && pnpm {command})' in verify_script
    assert "nix" not in verify_script
    assert "node_version} != v24.*" in verify_script
    assert "pnpm_version} != 11.15.1" in verify_script
    assert "zip_path=" in verify_script
    assert 'git diff --exit-code -- "${lockfiles[@]}"' in verify_script
    assert "--ignore-workspace" not in verify_script
    for document in (release_skill, release_checklist):
        assert "Node 24 / pnpm 11.15.1" in document
        assert "ambient `node` / `pnpm`" in document
        assert "`--ignore-workspace`" in document
        assert "`pnpm install --frozen-lockfile` → `pnpm build` → `pnpm zip`" in document
        assert "期待名 zip が唯一の1件" in document
        assert "lockfile に差分がない" in document
    assert "`pnpm -v` が 9 系" not in release_skill
    # エントリはリリース昇格で [Unreleased] から該当バージョンのセクションへ移るため、
    # 探索範囲を [Unreleased] に限定すると昇格のたびに StopIteration で落ちる。
    issue_entry = next(line for line in changelog.splitlines() if "#1956" in line)
    # #1956 は当時の再現環境を記録する履歴なので、現行 pin 更新では書き換えない。
    assert "Nix extensions shell 契約（Node 24 / pnpm 11.12.0" in issue_entry
    assert "frozen install → build → zip" in issue_entry
    assert "期待名 zip" in issue_entry
    assert "lockfile 無差分" in issue_entry


def test_release_skill_declares_executable_hard_gates_and_completion_criteria() -> None:
    release_skill = _read(".claude/skills/automation-release/SKILL.md")

    assert "## Hard Gates / 完了条件" in release_skill
    assert "non-zeroならreleaseを停止" in release_skill
    assert "承認前にpushしない" in release_skill
    assert "extension prepare完了" in release_skill
    assert "extension publish完了" in release_skill


def test_release_skill_requires_exactly_three_named_zip_assets() -> None:
    release_skill = _read(".claude/skills/automation-release/SKILL.md")

    assert 'test "${zip_count}" -eq 3' in release_skill
    assert "^suno-helper-[0-9]+\\.[0-9]+\\.[0-9]+-chrome\\.zip$" in release_skill
    assert "^distrokid-helper-[0-9]+\\.[0-9]+\\.[0-9]+-chrome\\.zip$" in release_skill
    assert "^community-helper-[0-9]+\\.[0-9]+\\.[0-9]+-chrome\\.zip$" in release_skill
    assert "件数過不足・重複・別名zipがあれば停止" in release_skill
