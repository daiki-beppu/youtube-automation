"""Dashboard の正本文書と配布境界が存在する契約。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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


def test_dashboard_source_and_extension_boundaries_are_separate() -> None:
    architecture = (ROOT / "docs/architecture.md").read_text(encoding="utf-8")
    assert "dashboard/" in architecture
    assert "extensions/shared-ui" in architecture
    assert not (ROOT / "packages").exists()
