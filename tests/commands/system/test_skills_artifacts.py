from __future__ import annotations

from pathlib import Path

import pytest

from youtube_automation.commands.system import skills_sync
from youtube_automation.commands.system.skills_sync import build_parser, main


def _write_skill(root: Path, name: str, writes: str, reads: str = "`なし`") -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f'''---
name: {name}
description: "{name} skill"
purpose: 作る
---

## 前後工程

- `前工程`: `なし`
- `後工程`: `なし`
- `委譲先`: `なし`

## 成果物

- `書き込む`: {writes}
- `読み込む`: {reads}
''',
        encoding="utf-8",
    )


@pytest.fixture
def artifacts_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    skills = tmp_path / ".claude" / "skills"
    _write_skill(skills, "alpha", "`shared.json`, `alpha.json`", "`common.md`")
    _write_skill(skills, "beta", "`shared.json`", "`common.md`")
    _write_skill(skills, "reader", "`なし`", "`shared.json`, `common.md`")
    monkeypatch.setattr(skills_sync, "_editable_root", lambda: tmp_path)
    return tmp_path


def test_artifacts_parser_registers_duplicates_only() -> None:
    args = build_parser().parse_args(["artifacts", "--duplicates-only"])

    assert args.duplicates_only is True
    assert args.asset == "skills"


def test_lint_rejects_missing_artifacts_block(artifacts_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    skill = artifacts_repo / ".claude" / "skills" / "missing"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        '---\nname: missing\ndescription: "missing skill"\npurpose: 作る\n---\n\n- `委譲先`: `なし`\n',
        encoding="utf-8",
    )

    assert main(["lint", "missing"]) == 1
    assert "missing: `## 成果物` ブロックがありません" in capsys.readouterr().out


def test_lint_rejects_missing_artifact_writes(artifacts_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    skill = artifacts_repo / ".claude" / "skills" / "missing-writes"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        '---\nname: missing-writes\ndescription: "missing writes"\npurpose: 作る\n---\n\n'
        "## 成果物\n\n- `読み込む`: `input.json`\n\n- `委譲先`: `なし`\n",
        encoding="utf-8",
    )

    assert main(["lint", "missing-writes"]) == 1
    assert "missing-writes: `## 成果物` に `書き込む` 行がありません" in capsys.readouterr().out


def test_lint_does_not_reject_duplicate_writers(artifacts_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["lint", "alpha", "beta"]) == 0
    assert "lint 合格: 2 skill" in capsys.readouterr().out


def test_artifacts_lists_writers_and_summary(artifacts_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["artifacts"]) == 0
    output = capsys.readouterr().out

    assert "alpha.json" in output
    assert "alpha" in output
    assert "shared.json" in output
    assert "alpha, beta" in output
    assert "重複 writer: 1 件 / 宣言された成果物: 2 件" in output


def test_artifacts_duplicates_only_excludes_single_writers_and_readers(
    artifacts_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["artifacts", "--duplicates-only"]) == 0
    output = capsys.readouterr().out

    assert "shared.json" in output
    assert "alpha, beta" in output
    assert "alpha.json" not in output
    assert "reader" not in output
    assert "common.md" not in output


def test_artifacts_does_not_require_reads_line(artifacts_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    skill_md = artifacts_repo / ".claude" / "skills" / "alpha" / "SKILL.md"
    skill_md.write_text(
        skill_md.read_text(encoding="utf-8").replace("- `読み込む`: `common.md`\n", ""), encoding="utf-8"
    )

    assert main(["artifacts"]) == 0
    assert "alpha.json" in capsys.readouterr().out
