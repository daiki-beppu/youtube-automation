from __future__ import annotations

from pathlib import Path

from tests.helpers.paths import REPO_ROOT

_CONSUMERS = (
    (".claude/skills/wf-new/references/collection-plan-documents.md", "yt-collection-plan-select"),
    (".claude/skills/music/references/music-prompt-documents.md", "yt-document-review"),
    (".claude/skills/thumbnail/references/operator-guide.md", "yt-thumbnail-review"),
    (".claude/skills/video/references/generate.md", "yt-document-review"),
)


def test_review_consumers_share_product_neutral_cli_and_fail_closed_contract() -> None:
    for relative, cli in _CONSUMERS:
        text = (REPO_ROOT / Path(relative)).read_text(encoding="utf-8")
        assert cli in text
        assert "--transport terminal" in text
        assert "黙って" in text
        assert "任意path" in text
        assert "command" in text
        assert "state patch" in text
        assert "Codex / Claude" in text
        assert "session" in text


def test_automatic_review_paths_explicitly_skip_html() -> None:
    texts = [(REPO_ROOT / path).read_text(encoding="utf-8") for path, _cli in _CONSUMERS]
    assert all("HTML" in text and ("CLIを呼ばず" in text or "--automatic" in text) for text in texts)
