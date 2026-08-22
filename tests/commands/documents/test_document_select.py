from __future__ import annotations

from dataclasses import dataclass

import pytest

from youtube_automation.commands.documents import select
from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.documents.review import ReviewOutcome


@dataclass
class _Args:
    automatic: bool
    transport: str
    candidate_id: str | None


@pytest.mark.parametrize(
    ("automatic", "transport", "candidate_id", "valid"),
    [
        (False, "web", None, True),
        (False, "terminal", None, True),
        (False, "terminal", "candidate-a", True),
        (True, "web", None, True),
        (True, "terminal", None, False),
        (True, "web", "candidate-a", False),
        (False, "web", "candidate-a", False),
    ],
)
def test_document_select_option_matrix_is_shared(monkeypatch, automatic, transport, candidate_id, valid) -> None:
    args = _Args(automatic, transport, candidate_id)
    monkeypatch.setattr(
        select,
        "review",
        lambda *_args, **_kwargs: ReviewOutcome("selected", "a" * 64, ("candidate-a",), "candidate-a"),
    )

    def invoke():
        return select.run_document_select(
            args,
            lambda _source: object(),
            success_payload=lambda candidate, source: {"candidate": candidate, "source": source},
            terminal_hint="hint",
        )

    if valid:
        assert invoke() == 0
    else:
        with pytest.raises(ValidationError):
            invoke()
