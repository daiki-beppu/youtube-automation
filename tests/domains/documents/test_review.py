from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from youtube_automation.core.errors import ReviewSelectionError
from youtube_automation.domains.documents.review import ReviewCandidate, SelectionManifest

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


def _manifest() -> SelectionManifest:
    return SelectionManifest.create(
        artifact="thumbnail",
        artifact_digest="a" * 64,
        candidates=(ReviewCandidate("candidate-a", "候補 A", "b" * 64),),
        now=NOW,
        lifetime=timedelta(minutes=5),
    )


def test_manifest_accepts_only_allowlisted_candidate_and_matching_digest() -> None:
    manifest = _manifest()

    selected = manifest.validate_selection(
        token=manifest.token, candidate_id="candidate-a", artifact_digest="a" * 64, now=NOW
    )

    assert selected.id == "candidate-a"


@pytest.mark.parametrize(
    ("token", "candidate_id", "digest", "now", "message"),
    [
        ("wrong", "candidate-a", "a" * 64, NOW, "token"),
        (None, "unknown", "a" * 64, NOW, "候補"),
        (None, "candidate-a", "c" * 64, NOW, "digest"),
        (None, "candidate-a", "a" * 64, NOW + timedelta(minutes=5), "期限"),
    ],
)
def test_manifest_rejects_token_candidate_digest_and_expiry(
    token: str | None, candidate_id: str, digest: str, now: datetime, message: str
) -> None:
    manifest = _manifest()
    with pytest.raises(ReviewSelectionError, match=message):
        manifest.validate_selection(
            token=token or manifest.token,
            candidate_id=candidate_id,
            artifact_digest=digest,
            now=now,
        )
