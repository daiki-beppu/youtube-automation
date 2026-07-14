from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_VERIFY_SCRIPT = _REPO_ROOT / ".claude/skills/automation-release/references/verify-extensions.sh"
_EXTENSIONS = ("suno-helper", "distrokid-helper")


@pytest.fixture
def verify_environment(tmp_path: Path) -> tuple[Path, dict[str, str], Path]:
    for name in _EXTENSIONS:
        extension_dir = tmp_path / "extensions" / name
        extension_dir.mkdir(parents=True)
        (extension_dir / "package.json").write_text('{"version":"1.2.3"}\n', encoding="utf-8")
        (extension_dir / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "extensions"], cwd=tmp_path, check=True)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "nix.log"
    fake_nix = bin_dir / "nix"
    fake_nix.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "${FAKE_NIX_LOG}"

if [[ $* == 'develop .#extensions --command node --version' ]]; then
  printf '%s\\n' "${FAKE_NODE_VERSION:-v24.1.0}"
  exit 0
fi
if [[ $* == 'develop .#extensions --command pnpm --version' ]]; then
  printf '%s\\n' "${FAKE_PNPM_VERSION:-11.12.0}"
  exit 0
fi
if [[ ${4:-} == node && ${5:-} == -p ]]; then
  printf '1.2.3\\n'
  exit 0
fi
if [[ ${4:-} == pnpm ]]; then
  extension_dir=${6}
  command=${7}
  name=${extension_dir##*/}
  if [[ ${command} == install && ${FAKE_MUTATE_LOCK:-} == "${name}" ]]; then
    printf 'mutated\\n' >> "${extension_dir}/pnpm-lock.yaml"
  fi
  if [[ ${command} == zip && ${FAKE_SKIP_ZIP:-} != "${name}" ]]; then
    mkdir -p "${extension_dir}/.output"
    : > "${extension_dir}/.output/${name}-1.2.3-chrome.zip"
  fi
  exit 0
fi

printf 'unexpected nix arguments: %s\\n' "$*" >&2
exit 64
""",
        encoding="utf-8",
    )
    fake_nix.chmod(0o755)

    environment = os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_NIX_LOG": str(log_path),
    }
    return tmp_path, environment, log_path


def _run_verify(
    verify_environment: tuple[Path, dict[str, str], Path],
    *names: str,
    environment_overrides: dict[str, str] | None = None,
    working_directory: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    repository, environment, _ = verify_environment
    if environment_overrides:
        environment = environment | environment_overrides
    return subprocess.run(
        ["bash", str(_VERIFY_SCRIPT), *names],
        cwd=working_directory or repository,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_default_verification_runs_both_extensions_in_order(
    verify_environment: tuple[Path, dict[str, str], Path],
) -> None:
    result = _run_verify(verify_environment)
    log = verify_environment[2].read_text(encoding="utf-8")

    assert result.returncode == 0, result.stderr
    expected_commands = [
        "develop .#extensions --command node --version",
        "develop .#extensions --command pnpm --version",
    ]
    for name in _EXTENSIONS:
        expected_commands.extend(
            [
                f"develop .#extensions --command pnpm -C extensions/{name} install --frozen-lockfile",
                f"develop .#extensions --command pnpm -C extensions/{name} build",
                f"develop .#extensions --command pnpm -C extensions/{name} zip",
                f"develop .#extensions --command node -p require('./extensions/{name}/package.json').version",
            ]
        )
    assert log.splitlines() == expected_commands


def test_single_extension_verification_does_not_run_sibling(
    verify_environment: tuple[Path, dict[str, str], Path],
) -> None:
    result = _run_verify(verify_environment, "suno-helper")
    log = verify_environment[2].read_text(encoding="utf-8")

    assert result.returncode == 0, result.stderr
    assert "extensions/suno-helper" in log
    assert "extensions/distrokid-helper" not in log


def test_verification_rejects_non_root_working_directory(
    verify_environment: tuple[Path, dict[str, str], Path],
) -> None:
    repository = verify_environment[0]
    result = _run_verify(verify_environment, working_directory=repository / "extensions")

    assert result.returncode != 0
    assert "repository root で実行してください" in result.stderr


def test_verification_rejects_unsupported_extension(
    verify_environment: tuple[Path, dict[str, str], Path],
) -> None:
    result = _run_verify(verify_environment, "unknown-helper")

    assert result.returncode != 0
    assert "unsupported extension: unknown-helper" in result.stderr


@pytest.mark.parametrize(
    ("environment_overrides", "message"),
    [
        ({"FAKE_NODE_VERSION": "v22.0.0"}, "expected Node 24"),
        ({"FAKE_PNPM_VERSION": "11.11.0"}, "expected pnpm 11.12.0"),
    ],
)
def test_verification_rejects_wrong_toolchain_version(
    verify_environment: tuple[Path, dict[str, str], Path],
    environment_overrides: dict[str, str],
    message: str,
) -> None:
    result = _run_verify(verify_environment, environment_overrides=environment_overrides)

    assert result.returncode != 0
    assert message in result.stderr


def test_verification_rejects_missing_zip(
    verify_environment: tuple[Path, dict[str, str], Path],
) -> None:
    result = _run_verify(verify_environment, environment_overrides={"FAKE_SKIP_ZIP": "suno-helper"})

    assert result.returncode != 0
    assert "expected exactly one zip (extensions/suno-helper/.output/suno-helper-1.2.3-chrome.zip)" in result.stderr


def test_verification_rejects_extra_zip(
    verify_environment: tuple[Path, dict[str, str], Path],
) -> None:
    repository = verify_environment[0]
    output_dir = repository / "extensions/suno-helper/.output"
    output_dir.mkdir(parents=True)
    (output_dir / "stale.zip").touch()

    result = _run_verify(verify_environment, "suno-helper")

    assert result.returncode != 0
    assert "found 2" in result.stderr


def test_verification_rejects_lockfile_diff(
    verify_environment: tuple[Path, dict[str, str], Path],
) -> None:
    result = _run_verify(verify_environment, environment_overrides={"FAKE_MUTATE_LOCK": "suno-helper"})

    assert result.returncode != 0
    assert "mutated" in result.stdout
