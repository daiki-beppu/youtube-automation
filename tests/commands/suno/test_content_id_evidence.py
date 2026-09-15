from pathlib import Path

import pytest

from youtube_automation.commands.suno.content_id_evidence import record, render_draft
from youtube_automation.core.errors import ValidationError


def test_record_and_render_dispute_draft(tmp_path: Path) -> None:
    record(
        tmp_path,
        track="Quiet Rain",
        url="https://suno.com/song/clip-1",
        generated_at="2026-09-15T12:00:00Z",
        model="v5",
        plan="Premier",
    )

    draft = render_draft(tmp_path, "Quiet Rain")

    assert "https://suno.com/song/clip-1" in draft
    assert "2026-09-15T12:00:00Z" in draft
    assert "Premier" in draft
    assert "再審査請求" in draft


@pytest.mark.parametrize(
    "url",
    ["http://suno.com/song/clip-1", "https://example.com/song/clip-1", "https://suno.com/clip-1"],
)
def test_record_rejects_invalid_clip_url(tmp_path: Path, url: str) -> None:
    with pytest.raises(ValidationError, match="clip URL"):
        record(tmp_path, track="track", url=url, generated_at="2026-09-15T12:00:00Z", model="v5", plan="Premier")


def test_record_rejects_invalid_generated_at(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="ISO 8601"):
        record(
            tmp_path,
            track="track",
            url="https://suno.com/song/clip-1",
            generated_at="not-a-date",
            model="v5",
            plan="Premier",
        )


def test_render_draft_rejects_unknown_track(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="生成記録がありません"):
        render_draft(tmp_path, "unknown")
