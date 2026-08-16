from __future__ import annotations

import pytest

from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.media_store import MediaKey


def test_media_key_builds_the_canonical_handoff_path() -> None:
    key = MediaKey(
        channel="ambient-lab",
        collection="rain-night",
        handoff="video-upload",
        name="media/Master.mp4",
    )

    assert key.as_posix() == "ambient-lab/rain-night/video-upload/media/Master.mp4"


def test_media_key_preserves_safe_suno_filenames_with_spaces_and_unicode() -> None:
    key = MediaKey(
        channel="002ch",
        collection="rain-night",
        handoff="suno-download",
        name="02-Individual-music/01a-Rainy Jazz 夜.mp3",
    )

    assert key.as_posix() == "002ch/rain-night/suno-download/02-Individual-music/01a-Rainy Jazz 夜.mp3"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("channel", "../other-channel"),
        ("collection", "/absolute"),
        ("handoff", "video/upload"),
        ("name", "nested/../Master.mp4"),
        ("name", "nested\\Master.mp4"),
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
