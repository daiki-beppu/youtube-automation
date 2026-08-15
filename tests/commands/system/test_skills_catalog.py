from __future__ import annotations

from pathlib import Path

import pytest

from youtube_automation.commands.system import skills_sync
from youtube_automation.commands.system.skills_sync import build_parser, main

_PURPOSES = ("準備する", "調べる", "決める", "進める", "作る", "公開する", "振り返る")


def _write_skill(skills_dir: Path, name: str, purpose: str, description: str) -> None:
    skill_dir = skills_dir / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f'---\nname: {name}\ndescription: "{description}"\npurpose: {purpose}\n---\n',
        encoding="utf-8",
    )


@pytest.fixture
def catalog_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    skills_dir = tmp_path / ".claude" / "skills"
    for index, purpose in enumerate(_PURPOSES):
        _write_skill(skills_dir, f"skill-{index}", purpose, f"{purpose}の説明。二文目は載せない。")
    _write_skill(skills_dir, "alpha", "作る", "先頭の説明。続き。")
    monkeypatch.setattr(skills_sync, "_editable_root", lambda: tmp_path)
    return tmp_path


def test_catalog_parser_registers_check_flag() -> None:
    args = build_parser().parse_args(["catalog", "--check"])

    assert args.check is True
    assert args.asset == "skills"


def test_catalog_generates_all_purpose_sections_in_pdca_order(catalog_repo: Path) -> None:
    assert main(["catalog"]) == 0

    catalog = (catalog_repo / "docs" / "skill-catalog.md").read_text(encoding="utf-8")
    positions = [catalog.index(f"## {purpose}") for purpose in _PURPOSES]
    assert positions == sorted(positions)
    assert "PDCA 対応" in catalog
    assert "準備 = 準備する" in catalog
    assert "Plan = 調べる → 決める" in catalog
    assert "Do = 進める → 作る → 公開する" in catalog
    assert "Check / Act = 振り返る" in catalog


def test_catalog_sorts_skills_by_name_and_summarizes_first_sentence(catalog_repo: Path) -> None:
    assert main(["catalog"]) == 0

    catalog = (catalog_repo / "docs" / "skill-catalog.md").read_text(encoding="utf-8")
    create_section = catalog.split("## 作る\n", maxsplit=1)[1].split("\n## 公開する", maxsplit=1)[0]
    assert create_section.index("`/alpha`") < create_section.index("`/skill-4`")
    assert "- `/alpha` — 先頭の説明。" in create_section
    assert "続き。" not in create_section


def test_catalog_check_succeeds_immediately_after_generation(catalog_repo: Path) -> None:
    assert main(["catalog"]) == 0

    assert main(["catalog", "--check"]) == 0


def test_catalog_check_displays_diff_and_fails_for_stale_output(
    catalog_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["catalog"]) == 0
    catalog_path = catalog_repo / "docs" / "skill-catalog.md"
    catalog_path.write_text(catalog_path.read_text(encoding="utf-8") + "手書き変更\n", encoding="utf-8")
    capsys.readouterr()

    assert main(["catalog", "--check"]) == 1
    output = capsys.readouterr().out
    assert "--- docs/skill-catalog.md" in output
    assert "+++ generated:docs/skill-catalog.md" in output
    assert "-手書き変更" in output
