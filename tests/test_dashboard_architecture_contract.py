"""Dashboard 限定 TypeScript 例外の文書契約。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_dashboard_architecture_is_consistent_across_governing_docs() -> None:
    adr = _read("docs/adr/0013-multi-channel-dashboard.md")
    separation = _read("docs/adr/0021-separate-repo-restart.md")
    claude = _read("CLAUDE.md")
    context = _read("CONTEXT.md")

    for document in (adr, separation, claude, context):
        assert "dashboard/" in document
        assert "React" in document
        assert "shadcn/ui" in document

    assert "Python HTTP" in adr
    assert "127.0.0.1" in adr
    assert "読み取り専用" in adr
    assert "dashboard 限定" in separation
    assert "dashboard 限定" in claude
    assert "他の TypeScript" in claude


def test_dashboard_docs_define_quality_and_distribution_boundaries() -> None:
    adr = _read("docs/adr/0013-multi-channel-dashboard.md")
    development = _read("docs/development.md")

    for command in ("lint", "typecheck", "test", "test:e2e", "build"):
        assert command in development

    assert "Base UI" in adr
    assert "Tailwind CSS v4" in adr
    assert "semantic token" in adr
    assert "extensions/shared-ui" in adr
    assert "直接 import しない" in adr
    assert "wheel" in adr and "sdist" in adr


def test_spell_ui_is_not_a_current_dashboard_decision() -> None:
    for path in (
        "docs/adr/0013-multi-channel-dashboard.md",
        "docs/adr/0021-separate-repo-restart.md",
        "CLAUDE.md",
        "CONTEXT.md",
        "docs/development.md",
    ):
        document = _read(path)
        assert "Spell UI" not in document
