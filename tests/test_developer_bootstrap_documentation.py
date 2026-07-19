"""Developer bootstrap の単一正規入口と skill lint docs の drift 契約。"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
CANONICAL_COMMAND = "bash .lefthook/setup-worktree.sh"
CANONICAL_LINK = "docs/development.md#開発者-bootstrap正規入口"


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _section(path: str, heading: str) -> str:
    text = _read(path)
    match = re.search(rf"^{re.escape(heading)}\n.*?(?=^## |\Z)", text, flags=re.DOTALL | re.MULTILINE)
    assert match is not None, f"{path}: missing section {heading}"
    return match.group(0)


def test_development_owns_complete_bootstrap_contract() -> None:
    development = _read("docs/development.md")
    section = _section("docs/development.md", "## 開発者 bootstrap（正規入口）")

    assert development.count("## 開発者 bootstrap（正規入口）") == 1
    for phrase in (
        CANONICAL_COMMAND,
        "linked worktree",
        "対話 shell",
        "非対話 shell / agent",
        "fail-closed",
        ".envrc",
        "nix develop",
    ):
        assert phrase in section


def test_reader_specific_docs_point_to_canonical_bootstrap() -> None:
    sections = {
        "README.md": _section("README.md", "## Development"),
        "ONBOARDING.md": _section("ONBOARDING.md", "## 6. 付録: 開発者向け（本リポジトリ側を編集する人）"),
        "CLAUDE.md": _read("CLAUDE.md"),
    }
    for path, text in sections.items():
        assert CANONICAL_LINK in text, f"{path}: canonical bootstrap link is missing"
        assert CANONICAL_COMMAND in text, f"{path}: canonical bootstrap command is missing"
        assert "worktree" in text, f"{path}: worktree-only development is missing"

    readme_bootstrap = re.search(r"### Developer bootstrap.*?```bash\n(.*?)```", sections["README.md"], re.DOTALL)
    onboarding_setup = re.search(r"### 6\.1 セットアップ.*?```bash\n(.*?)```", sections["ONBOARDING.md"], re.DOTALL)
    assert readme_bootstrap is not None and onboarding_setup is not None
    for block in (readme_bootstrap.group(1), onboarding_setup.group(1)):
        assert "git clone git@github.com:daiki-beppu/youtube-automation.git" in block
        assert "cd youtube-automation" in block
        assert CANONICAL_COMMAND in block
        assert "uv sync" not in block
        assert "nix develop" not in block


def test_skill_lint_docs_reject_stale_unimplemented_guidance() -> None:
    development = _read("docs/development.md")
    stale_patterns = ("skill 単体の軽量 lint コマンドはまだ無い", "yt-skills lint` は #2096 で計画中")

    assert "uv run yt-skills lint [<skill>...]" in development
    assert "strict YAML" in development
    assert "features catalog" in development
    for stale in stale_patterns:
        assert stale not in development
