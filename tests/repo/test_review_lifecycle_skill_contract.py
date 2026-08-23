from __future__ import annotations

from pathlib import Path

from tests.helpers.paths import REPO_ROOT

_CONSUMERS = (
    (".claude/skills/wf-new/references/collection-plan-documents.md", "yt-collection-plan-select"),
    (".claude/skills/music/references/music-prompt-documents.md", "yt-music-prompt-select"),
    (".claude/skills/thumbnail/references/operator-guide.md", "yt-thumbnail-review"),
    (".claude/skills/video/references/master-video-review.md", "yt-master-video-review"),
    (".claude/skills/music/references/master-audio-review.md", "yt-master-audio-review"),
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


def test_review_documents_require_link_and_summary_in_parent_report() -> None:
    for relative in (
        ".claude/skills/music/references/music-prompt-documents.md",
        ".claude/skills/video/references/master-video-review.md",
        ".claude/skills/wf-new/references/collection-plan-documents.md",
        ".claude/skills/wf-next/SKILL.md",
    ):
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert "HTML生成直後" in text
        assert "絶対path" in text
        assert "Markdown link" in text
        assert "要約" in text
        assert "完了報告" in text


def test_wf_next_description_review_uses_defined_upload_approval_flag() -> None:
    text = (REPO_ROOT / ".claude/skills/wf-next/SKILL.md").read_text(encoding="utf-8")

    assert "手動確認を要求する設定" not in text
    assert "skip_upload_approval = false" in text
    assert "確認完了まで `assets.description` と phase を更新しない" in text
    assert "アップロード承認ゲート 3-B を先に実行" in text
    assert "絶対path" in text
    assert "Markdown link" in text
    assert "要約" in text
    assert "完了報告" in text

    full_review = text.index("full reviewへ渡す")
    approval_gate = text.index("ここでアップロード承認ゲート 3-B を先に実行")
    state_update = text.index("set-description-generated true", approval_gate)
    assert full_review < approval_gate < state_update
    assert "full review PASS 後、ユーザーに公開方法を提示する前" in text
    assert "並列 A 完了直後、ユーザーに公開方法を提示する前" not in text
