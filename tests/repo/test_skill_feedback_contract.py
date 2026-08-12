from __future__ import annotations

import json
import re

import pytest

from tests.helpers.paths import REPO_ROOT

_SKILL_PATH = REPO_ROOT / ".claude/skills/skill-feedback/SKILL.md"
_SCHEMA_PATH = REPO_ROOT / ".claude/skills/skill-feedback/references/feedback-entry.schema.json"


def _schema() -> dict[str, object]:
    loaded = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _status_rule(status: str) -> dict[str, object]:
    rules = _schema()["allOf"]
    assert isinstance(rules, list)
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        condition = rule.get("if")
        if not isinstance(condition, dict):
            continue
        properties = condition.get("properties")
        if isinstance(properties, dict) and properties.get("status") == {"const": status}:
            then = rule.get("then")
            assert isinstance(then, dict)
            return then
    raise AssertionError(f"status={status!r} の schema rule が存在しない")


def _prohibited_fields(rule: dict[str, object]) -> set[str]:
    prohibited: set[str] = set()
    not_clause = rule.get("not")
    assert isinstance(not_clause, dict)
    required = not_clause.get("required")
    if isinstance(required, list):
        prohibited.update(required)
    any_of = not_clause.get("anyOf", [])
    assert isinstance(any_of, list)
    for branch in any_of:
        assert isinstance(branch, dict)
        branch_required = branch.get("required")
        assert isinstance(branch_required, list)
        prohibited.update(branch_required)
    return prohibited


def _lifecycle_rows() -> dict[str, tuple[str, str, str]]:
    skill = _SKILL_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"^## Entry lifecycle contract\n\n"
        r"\| status \| filing candidate \| terminal \| required metadata \|\n"
        r"\|[-| ]+\|\n"
        r"(?P<rows>(?:\|[^\n]+\|\n)+)",
        skill,
        flags=re.MULTILINE,
    )
    assert match is not None
    rows: dict[str, tuple[str, str, str]] = {}
    for row in match.group("rows").splitlines():
        status, candidate, terminal, metadata = [cell.strip() for cell in row.strip("|").split("|")]
        rows[status] = (candidate, terminal, metadata)
    return rows


def test_feedback_schema_declares_all_lifecycle_statuses() -> None:
    properties = _schema()["properties"]
    assert isinstance(properties, dict)

    assert properties["status"]["enum"] == ["recorded", "filed", "resolved", "wontfix"]


@pytest.mark.parametrize(
    ("status", "required", "prohibited"),
    (
        ("recorded", set(), {"issue_url", "disposition_reason", "disposition_at"}),
        ("filed", {"issue_url"}, {"disposition_reason", "disposition_at"}),
        ("resolved", {"disposition_reason", "disposition_at"}, {"issue_url"}),
        ("wontfix", {"disposition_reason", "disposition_at"}, {"issue_url"}),
    ),
)
def test_feedback_schema_enforces_metadata_for_each_status(
    status: str,
    required: set[str],
    prohibited: set[str],
) -> None:
    rule = _status_rule(status)

    assert set(rule.get("required", [])) == required
    assert _prohibited_fields(rule) == prohibited


def test_terminal_disposition_metadata_has_nonempty_reason_and_timestamp_contract() -> None:
    properties = _schema()["properties"]
    assert isinstance(properties, dict)

    assert properties["disposition_reason"]["type"] == "string"
    assert properties["disposition_reason"]["minLength"] == 1
    assert properties["disposition_at"] == {"type": "string", "format": "date-time"}


def test_skill_lifecycle_only_exposes_recorded_entries_as_filing_candidates() -> None:
    assert _lifecycle_rows() == {
        "recorded": ("yes", "no", "none"),
        "filed": ("no", "yes", "issue_url"),
        "resolved": ("no", "yes", "disposition_reason, disposition_at"),
        "wontfix": ("no", "yes", "disposition_reason, disposition_at"),
    }


def test_skill_keeps_schema_invalid_jsonl_fail_closed() -> None:
    skill = _SKILL_PATH.read_text(encoding="utf-8")
    fail_closed_contract = (
        "schema に準拠しない\n行が 1 行でもあれば、行番号だけを示して停止する。壊れた行を飛ばして続行しない。"
    )

    assert fail_closed_contract in skill
