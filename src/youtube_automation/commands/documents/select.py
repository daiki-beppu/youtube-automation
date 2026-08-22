"""Shared command harness for document review selection."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable

from youtube_automation.application.review_lifecycle import ReviewSource, review
from youtube_automation.core.errors import ValidationError


def run_document_select(
    args: argparse.Namespace,
    source_factory: Callable[[str], ReviewSource],
    *,
    success_payload: Callable[[str, str], dict[str, object]],
    terminal_hint: str,
) -> int:
    """Apply the common option matrix and lifecycle/JSON contract."""
    if args.automatic and (args.transport != "web" or args.candidate_id is not None):
        raise ValidationError("--automaticは--transport terminal / --candidate-idと併用できません")
    if args.transport == "web" and args.candidate_id is not None:
        raise ValidationError("--candidate-idは--transport terminal専用です")

    selection_source = "automatic" if args.automatic else args.transport
    outcome = review(
        source_factory(selection_source),
        args.transport,
        args.automatic,
        300,
        candidate_id=args.candidate_id,
    )
    if outcome.status == "terminal_required":
        print(json.dumps(outcome.json_payload(), ensure_ascii=False, sort_keys=True))
        print(terminal_hint, file=sys.stderr)
        return outcome.exit_code
    if outcome.candidate_id is None:
        raise ValidationError("review lifecycleから候補IDを取得できません")
    print(json.dumps(success_payload(outcome.candidate_id, selection_source), ensure_ascii=False, sort_keys=True))
    return outcome.exit_code


__all__ = ["run_document_select"]
