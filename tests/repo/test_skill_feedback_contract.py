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


def _invalid_line_rows() -> dict[str, tuple[str, str, str]]:
    skill = _SKILL_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"^## Schema-invalid line contract\n\n"
        r"\| line classification \| filing candidate \| mutable \| required action \|\n"
        r"\|[-| ]+\|\n"
        r"(?P<rows>(?:\|[^\n]+\|\n)+)",
        skill,
        flags=re.MULTILINE,
    )
    assert match is not None
    rows: dict[str, tuple[str, str, str]] = {}
    for row in match.group("rows").splitlines():
        classification, candidate, mutable, action = [cell.strip() for cell in row.strip("|").split("|")]
        rows[classification] = (candidate, mutable, action)
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


def test_skill_continues_with_valid_recorded_entries_after_invalid_line_warning() -> None:
    assert _invalid_line_rows() == {
        "schema-invalid": ("no", "no", "warn with line number and reason; continue"),
        "valid recorded": ("yes", "after approval only", "continue filing flow"),
        "valid terminal": ("no", "no", "leave unchanged"),
    }


def test_skill_preserves_non_target_lines_as_original_bytes() -> None:
    skill = _SKILL_PATH.read_text(encoding="utf-8")

    assert "各 physical line の元の bytes と line terminator" in skill
    assert "invalid 行、terminal entry、未選択行を元の bytes のまま複写" in skill
    assert "行数、行順、対象外行の byte-for-byte 同一性" in skill


def test_skill_fails_closed_before_side_effects_when_partial_processing_is_unsafe() -> None:
    skill = _SKILL_PATH.read_text(encoding="utf-8")

    assert "全 physical line を分類できない" in skill
    assert "atomic rewrite の事前検証を完了できない" in skill
    assert "issue 起票や disposition 更新を開始せず fail-closed" in skill


def test_skill_stops_following_entries_after_filing_or_rewrite_failure() -> None:
    skill = _SKILL_PATH.read_text(encoding="utf-8")

    assert "1 件の起票またはログ更新が失敗したら後続 entry を起票せず停止する" in skill
    assert "invalid 行と terminal entry は変更しない" in skill


def test_skill_advances_snapshot_after_disposition_then_filing_rewrite() -> None:
    skill = _SKILL_PATH.read_text(encoding="utf-8")

    assert "disposition rewrite の成功後も filing flow の前に最新状態へ進める" in skill
    assert "最新 snapshot、全行の bytes、未処理 entry の保持値" in skill
    assert "atomic rewrite が成功するたびに更新する" in skill


def test_skill_advances_snapshot_between_multiple_filing_candidates() -> None:
    skill = _SKILL_PATH.read_text(encoding="utf-8")

    assert "各 filing candidate の atomic rewrite 成功後" in skill
    assert "次の candidate は更新済みの最新 snapshot を基準に処理する" in skill


def test_skill_checks_latest_snapshot_immediately_before_each_issue_creation() -> None:
    skill = _SKILL_PATH.read_text(encoding="utf-8")

    assert "各 `gh issue create` の直前" in skill
    assert "current bytes が最新 snapshot と完全一致" in skill
    assert "コマンドを実行せず fail-closed" in skill


def test_skill_blocks_automatic_retry_after_created_issue_rewrite_failure() -> None:
    skill = _SKILL_PATH.read_text(encoding="utf-8")

    assert "created-unrecorded" in skill
    assert "同じ entry で `gh issue create` を再実行してはならない" in skill
    assert "既存 issue URL を使う recovery rewrite" in skill


def test_schema_invalid_warning_excludes_secret_like_instance_data() -> None:
    skill = _SKILL_PATH.read_text(encoding="utf-8")
    secret_like_invalid_value = "sk-live-contract-secret-value"
    invalid_entry_fixture = json.dumps(
        {
            "date": "2026-08-12T00:00:00Z",
            "skill": "thumbnail",
            "category": "bug",
            "summary": "",
            "context": secret_like_invalid_value,
            "status": "recorded",
        }
    )
    expected_warning = "line 7: schema keyword=minLength pointer=/summary"

    assert secret_like_invalid_value in invalid_entry_fixture
    assert json.loads(invalid_entry_fixture)["summary"] == ""
    assert secret_like_invalid_value not in expected_warning
    assert expected_warning in skill
    assert "error class、schema keyword、JSON pointer、line、column" in skill
    assert "invalid raw bytes、instance value、validator の raw message" in skill
