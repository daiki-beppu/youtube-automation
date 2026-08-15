"""開発専用 skill が Python 配布物へ混入しないことの契約テスト。"""

from __future__ import annotations

import subprocess
import tarfile
import tomllib
import zipfile
from pathlib import Path

from tests.helpers.paths import REPO_ROOT
from youtube_automation.commands.system.skills_sync import _DEV_ONLY_SKILL_NAMES


def _build(tmp_path: Path, distribution: str) -> Path:
    output = tmp_path / distribution
    result = subprocess.run(
        ["uv", "build", f"--{distribution}", "--out-dir", str(output)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    artifacts = list(output.glob("*.whl" if distribution == "wheel" else "*.tar.gz"))
    assert len(artifacts) == 1, artifacts
    return artifacts[0]


def test_build_exclusion_matches_runtime_dev_only_skills() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    configured = pyproject["tool"]["hatch"]["build"]["hooks"]["custom"]["dev-only-skills"]

    assert frozenset(configured) == _DEV_ONLY_SKILL_NAMES


def test_dev_only_skills_are_absent_from_wheel(tmp_path: Path) -> None:
    wheel = _build(tmp_path, "wheel")

    with zipfile.ZipFile(wheel) as archive:
        members = archive.namelist()

    for skill_name in _DEV_ONLY_SKILL_NAMES:
        assert not any(f"youtube_automation/_skills/{skill_name}/" in member for member in members)
    assert any("youtube_automation/_skills/setup/SKILL.md" in member for member in members)


def test_dev_only_skills_are_absent_from_sdist(tmp_path: Path) -> None:
    sdist = _build(tmp_path, "sdist")

    with tarfile.open(sdist) as archive:
        members = archive.getnames()

    for skill_name in _DEV_ONLY_SKILL_NAMES:
        assert not any(f"/.claude/skills/{skill_name}/" in member for member in members)
    assert any("/.claude/skills/setup/SKILL.md" in member for member in members)
