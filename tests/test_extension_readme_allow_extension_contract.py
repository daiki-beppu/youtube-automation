"""Chrome helper README allow-extension contract tests."""

from __future__ import annotations

from pathlib import Path
from typing import Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent


def _read_readme(extension_name: str) -> str:
    return (_REPO_ROOT / "extensions" / extension_name / "README.md").read_text(encoding="utf-8")


def test_suno_helper_readme_documents_allow_extension_contract() -> None:
    text = _read_readme("suno-helper")

    assert 'uv run yt-collection-serve "$CHANNEL_DIR/collections/planning" \\' in text
    assert "--allow-extension suno-helper" in text
    assert '--allow-origin "chrome-extension://<EXTENSION_ID>"' in text
    assert "Secure Preferences" in text
    assert "Preferences" in text
    assert "basename is `suno-helper`" in text
    assert "検出 0 件、複数 ID、Preferences read failure、JSON parse failure" in text


def test_distrokid_helper_readme_documents_allow_extension_contract() -> None:
    text = _read_readme("distrokid-helper")

    assert (
        "uv run yt-collection-serve <collections_root> --distrokid-capture-root <channel_root> "
        "--allow-extension distrokid-helper"
    ) in text
    assert "--allow-origin chrome-extension://<EXTENSION_ID>" in text
    assert "Secure Preferences" in text
    assert "Preferences" in text
    assert "basename is `distrokid-helper`" in text
    assert "検出 0 件、複数 ID、Preferences read failure、JSON parse failure" in text
