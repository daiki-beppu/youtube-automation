from __future__ import annotations

import json
import re
from pathlib import Path


def _result(output: str) -> dict[str, object]:
    parsed = json.loads(output)
    if not isinstance(parsed, dict):
        raise ValueError("wf-status eval output は JSON object でなければなりません")
    return parsed


def _grading_result(passed: bool, success: str, failure: str) -> dict[str, object]:
    return {"pass": passed, "score": 1 if passed else 0, "reason": success if passed else failure}


def collections_reported(output: str, _context: dict[str, object]) -> dict[str, object]:
    response = _result(output).get("response")
    if not isinstance(response, str):
        raise ValueError("wf-status eval output に response 文字列がありません")
    fixture_root = Path(__file__).resolve().parents[1] / "fixtures" / "channel" / "collections" / "planning"
    missing = []
    for collection_id in ("v1-legacy", "v2-prepared"):
        state = json.loads((fixture_root / collection_id / "workflow-state.json").read_text(encoding="utf-8"))
        name = state["collection_name"]
        identifier = re.compile(rf"(?<![\w-]){re.escape(collection_id)}(?![\w-])")
        if not any(identifier.search(line) and name in line for line in response.splitlines()):
            missing.append(collection_id)
    reported = not missing and "Unknown command: /wf-status" not in response
    return _grading_result(
        reported,
        "v1 / v2 コレクションの ID と名称を表示",
        f"コレクションの一覧結果が不足または skill 未解決: {missing}",
    )


def no_execution_tool_attempts(output: str, _context: dict[str, object]) -> dict[str, object]:
    calls = _result(output).get("tool_calls")
    if not isinstance(calls, list):
        raise ValueError("wf-status eval output の tool_calls が配列ではありません")
    return _grading_result(not calls, "実行系 tool の拒否試行なし", f"許可外 tool 呼び出し: {calls}")


def workflow_state_immutable(output: str, _context: dict[str, object]) -> dict[str, object]:
    result = _result(output)
    unchanged = result.get("workflow_state_unchanged")
    changed = result.get("changed_workflow_state_files")
    if not isinstance(unchanged, bool) or not isinstance(changed, list):
        raise ValueError("wf-status eval output の state 変更情報が不正です")
    return _grading_result(unchanged, "workflow-state.json は不変", f"変更を検出: {changed}")


def fixture_clean(output: str, _context: dict[str, object]) -> dict[str, object]:
    result = _result(output)
    unchanged = result.get("fixture_unchanged")
    changed = result.get("changed_fixture_files")
    if not isinstance(unchanged, bool) or not isinstance(changed, list):
        raise ValueError("wf-status eval output の fixture 変更情報が不正です")
    return _grading_result(unchanged, "fixture 全体が不変", f"変更を検出して復元: {changed}")
