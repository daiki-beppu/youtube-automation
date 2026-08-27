from __future__ import annotations

import pytest

from tests.helpers.paths import REPO_ROOT
from youtube_automation.commands.system.skills_sync import build_parser


def test_generated_skill_catalog_and_implementation_are_removed() -> None:
    assert not (REPO_ROOT / "docs" / "skill-catalog.md").exists()
    assert not (REPO_ROOT / "src/youtube_automation/commands/system/skills_sync/_catalog.py").exists()


@pytest.mark.parametrize("arguments", [["catalog"], ["catalog", "--check"]])
def test_catalog_is_not_a_registered_subcommand(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(arguments)

    assert exc_info.value.code != 0


def test_catalog_is_absent_from_cli_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["--help"])

    assert exc_info.value.code == 0
    assert "catalog" not in capsys.readouterr().out


def test_ci_does_not_run_skill_catalog_check() -> None:
    workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "yt-skills catalog" not in workflow
