from tests.helpers.paths import REPO_ROOT


def test_upload_requires_content_id_preflight_before_publication() -> None:
    upload = (REPO_ROOT / ".claude/skills/publish/references/upload.md").read_text(encoding="utf-8")
    checklist = (REPO_ROOT / ".claude/skills/publish/references/posting-checklist.md").read_text(encoding="utf-8")

    for text in (upload, checklist):
        assert "公開前リスクチェック" in text
        assert "Content ID" in text
        assert "制限" in text
    assert "そのまま公開 / 異議申し立て / 動画を差し替える" in upload
    assert "https://studio.youtube.com/video/<VIDEO_ID>/edit" in upload
