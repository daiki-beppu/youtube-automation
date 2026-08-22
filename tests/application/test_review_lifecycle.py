from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from youtube_automation.application import review_lifecycle
from youtube_automation.core.errors import ReviewError
from youtube_automation.domains.documents.review import ReviewCandidate
from youtube_automation.infrastructure.browser.selection_broker import BrokerSelection


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass
class _Source:
    html_path: Path
    artifact: str = "thumbnail"
    version: int = 0
    reads: int = 0
    commits: list[str] = field(default_factory=list)

    def candidates(self) -> tuple[ReviewCandidate, ...]:
        self.reads += 1
        digest = _digest(f"candidate:{self.version}")
        return (ReviewCandidate("candidate-1", "Candidate", digest),)

    def media(self) -> tuple[tuple[str, Path], ...]:
        return ()

    def digest(self, candidates: tuple[ReviewCandidate, ...]) -> str:
        return _digest(f"artifact:{self.version}:{candidates[0].digest}")

    def commit(self, candidate: ReviewCandidate) -> None:
        self.commits.append(candidate.id)


class _Broker:
    def __init__(self, manifest, source: _Source) -> None:
        self.manifest = manifest
        self.source = source
        self.endpoint = "http://127.0.0.1/select"

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def wait(self, *, timeout: float) -> BrokerSelection:
        assert timeout == 1
        self.source.version += 1
        return BrokerSelection("candidate-1", self.manifest.artifact_digest)


def test_terminal_transport_returns_exit_code_two_and_json_contract(tmp_path: Path) -> None:
    source = _Source(tmp_path / "review.html")

    outcome = review_lifecycle.review(source, "terminal", False, 1)

    assert outcome.exit_code == 2
    assert outcome.json_payload() == {
        "status": "terminal_required",
        "artifact_digest": _digest(f"artifact:0:{_digest('candidate:0')}"),
        "candidates": ["candidate-1"],
    }
    assert source.commits == []


@pytest.mark.parametrize("initial_version", range(5))
def test_review_rejects_every_candidate_mutation_before_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, initial_version: int
) -> None:
    """Property: any selected candidate byte version change prevents commit."""
    source = _Source(tmp_path / "review.html", version=initial_version)
    monkeypatch.setattr(review_lifecycle, "SelectionBroker", lambda manifest: _Broker(manifest, source))
    monkeypatch.setattr(review_lifecycle, "_display", lambda *_args: source.html_path)

    with pytest.raises(ReviewError, match="候補実体が変わりました"):
        review_lifecycle.review(source, "web", False, 1)

    assert source.commits == []


def test_automatic_selection_revalidates_then_commits(tmp_path: Path) -> None:
    source = _Source(tmp_path / "review.html")

    outcome = review_lifecycle.review(source, "web", True, 1)

    assert outcome.status == "selected"
    assert outcome.exit_code == 0
    assert source.reads == 2
    assert source.commits == ["candidate-1"]
