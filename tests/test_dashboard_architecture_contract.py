"""Dashboard 限定 TypeScript 例外の文書契約。

正本は移設で `CONTEXT.md` から `docs/architecture.md` へ移った。存在確認だけでは
`--skip-refresh` や部分エラーのような内容契約が失われるため、移設先に対して
削除前と同等の assertion を維持する。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_dashboard_governing_documents_are_migrated_and_present() -> None:
    for relative_path in (
        "docs/adr/0013-multi-channel-dashboard.md",
        "docs/adr/0021-separate-repo-restart.md",
        "docs/architecture.md",
        "docs/development.md",
        "docs/dashboard.md",
        "CLAUDE.md",
    ):
        assert (ROOT / relative_path).is_file(), relative_path
    assert not (ROOT / "CONTEXT.md").exists()


def test_dashboard_architecture_is_consistent_across_governing_docs() -> None:
    adr = _read("docs/adr/0013-multi-channel-dashboard.md")
    separation = _read("docs/adr/0021-separate-repo-restart.md")
    claude = _read("CLAUDE.md")
    architecture = _read("docs/architecture.md")

    for document in (adr, separation, claude, architecture):
        assert "dashboard/" in document
        assert "React" in document
        assert "shadcn/ui" in document

    assert "Python HTTP" in adr
    assert "127.0.0.1" in adr
    assert "起動時" in adr
    assert "全チャンネル" in adr
    assert "部分エラー" in adr
    assert "公開予約" in adr
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


def test_dashboard_docs_disclose_startup_api_usage_and_offline_escape_hatch() -> None:
    dashboard = _read("docs/dashboard.md")
    development = _read("docs/development.md")

    for document in (dashboard, development):
        assert "YouTube Data API" in document
        assert "YouTube Analytics API" in document
        assert "--skip-refresh" in document


def test_analytics_skills_disclose_dashboard_collection_cost() -> None:
    collect = _read(".claude/skills/analytics-collect/SKILL.md")
    run = _read(".claude/skills/analytics-run/SKILL.md")

    for document in (collect, run):
        assert "yt-dashboard" in document
        assert "チャンネル数" in document
    assert "--skip-refresh" in collect


def test_spell_ui_is_not_a_current_dashboard_decision() -> None:
    for path in (
        "docs/adr/0013-multi-channel-dashboard.md",
        "docs/adr/0021-separate-repo-restart.md",
        "CLAUDE.md",
        "docs/architecture.md",
        "docs/development.md",
    ):
        assert "Spell UI" not in _read(path)


def test_dashboard_source_and_extension_boundaries_are_separate() -> None:
    architecture = _read("docs/architecture.md")
    assert "dashboard/" in architecture
    assert "extensions/shared-ui" in architecture
    assert not (ROOT / "packages").exists()
