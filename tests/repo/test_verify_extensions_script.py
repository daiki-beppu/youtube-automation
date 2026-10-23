from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.helpers.paths import REPO_ROOT

_REPO_ROOT = REPO_ROOT
_VERIFY_SCRIPT = _REPO_ROOT / ".claude/skills/automation-release/references/verify-extensions.sh"
_EXTENSIONS = ("suno-helper", "distrokid-helper", "community-helper")


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
    log_path = tmp_path / "toolchain.log"
    # vp の shim の代わりに、cwd と引数を記録する偽の node / pnpm を PATH 先頭へ置く。
    fake_node = bin_dir / "node"
    fake_node.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf 'node %s\\n' "$*" >> "${FAKE_TOOLCHAIN_LOG}"
if [[ $* == --version ]]; then
  printf '%s\\n' "${FAKE_NODE_VERSION:-v24.22.1}"
  exit 0
fi
if [[ ${1:-} == -p ]]; then
  printf '1.2.3\\n'
  exit 0
fi
printf 'unexpected node arguments: %s\\n' "$*" >&2
exit 64
""",
        encoding="utf-8",
    )
    fake_pnpm = bin_dir / "pnpm"
    fake_pnpm.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
extension_dir=${PWD#"${FAKE_REPOSITORY}/"}
printf '%s: pnpm %s\\n' "${extension_dir}" "$*" >> "${FAKE_TOOLCHAIN_LOG}"
name=${extension_dir##*/}
command=${1:-}
if [[ ${command} == --version ]]; then
  printf '%s\\n' "${FAKE_PNPM_VERSION:-11.15.1}"
  exit 0
fi
if [[ ${command} == install && ${FAKE_MUTATE_LOCK:-} == "${name}" ]]; then
  printf 'mutated\\n' >> pnpm-lock.yaml
fi
if [[ ${command} == zip && ${FAKE_SKIP_ZIP:-} != "${name}" ]]; then
  mkdir -p .output
  : > ".output/${name}-1.2.3-chrome.zip"
  if [[ ${FAKE_EXTRA_ZIP:-} == "${name}" ]]; then
    : > ".output/${name}-sources.zip"
  fi
fi
exit 0
""",
        encoding="utf-8",
    )
    for fake in (fake_node, fake_pnpm):
        fake.chmod(0o755)

    environment = os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_TOOLCHAIN_LOG": str(log_path),
        "FAKE_REPOSITORY": str(tmp_path.resolve()),
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


def test_default_verification_runs_all_extensions_in_order(
    verify_environment: tuple[Path, dict[str, str], Path],
) -> None:
    result = _run_verify(verify_environment)
    log = verify_environment[2].read_text(encoding="utf-8")

    assert result.returncode == 0, result.stderr
    expected_commands = ["node --version"]
    expected_commands.extend(f"extensions/{name}: pnpm --version" for name in _EXTENSIONS)
    for name in _EXTENSIONS:
        expected_commands.extend(
            [
                f"extensions/{name}: pnpm install --frozen-lockfile",
                f"extensions/{name}: pnpm build",
                f"extensions/{name}: pnpm zip",
                f"node -p require('./extensions/{name}/package.json').version",
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
    assert "extensions/community-helper" not in log


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
        ({"FAKE_PNPM_VERSION": "11.11.0"}, "expected pnpm 11.15.1"),
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
    # release-extensions.yml は .output/*.zip を glob で Release asset へ上げるため、
    # zip コマンドが期待名以外の成果物を生んだ場合は公開前に停止する必要がある。
    result = _run_verify(
        verify_environment,
        "suno-helper",
        environment_overrides={"FAKE_EXTRA_ZIP": "suno-helper"},
    )

    assert result.returncode != 0
    assert "found 2" in result.stderr


def test_verification_cleans_stale_zip_before_zipping(
    verify_environment: tuple[Path, dict[str, str], Path],
) -> None:
    # 過去 run のビルド残骸（gitignore 済みで pnpm zip が再生成する）は
    # 唯一性判定の対象外。掃除した上で今回の生成物だけを検証する。
    repository = verify_environment[0]
    output_dir = repository / "extensions/suno-helper/.output"
    output_dir.mkdir(parents=True)
    (output_dir / "stale.zip").touch()
    (output_dir / "suno-helper-0.0.1-chrome.zip").touch()

    result = _run_verify(verify_environment, "suno-helper")

    assert result.returncode == 0, result.stderr
    assert sorted(path.name for path in output_dir.glob("*.zip")) == ["suno-helper-1.2.3-chrome.zip"]


def test_verification_rejects_lockfile_diff(
    verify_environment: tuple[Path, dict[str, str], Path],
) -> None:
    result = _run_verify(verify_environment, environment_overrides={"FAKE_MUTATE_LOCK": "suno-helper"})

    assert result.returncode != 0
    assert "mutated" in result.stdout
