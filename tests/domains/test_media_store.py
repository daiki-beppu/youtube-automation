from __future__ import annotations

import pytest

from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.media_store import MediaKey


def test_media_key_builds_the_canonical_handoff_path() -> None:
    key = MediaKey(channel="ambient-lab", collection="rain-night", handoff="video-upload", name="Master.mp4")

    assert key.as_posix() == "ambient-lab/rain-night/video-upload/Master.mp4"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("channel", "../other-channel"),
        ("collection", "/absolute"),
        ("handoff", "video/upload"),
        ("name", "nested/Master.mp4"),
        ("name", ".."),
    ],
)
def test_media_key_rejects_paths_outside_the_canonical_boundary(field: str, value: str) -> None:
    values = {
        "channel": "ambient-lab",
        "collection": "rain-night",
        "handoff": "video-upload",
        "name": "Master.mp4",
    }
    values[field] = value

    with pytest.raises(ValidationError, match=field):
        MediaKey(**values)
