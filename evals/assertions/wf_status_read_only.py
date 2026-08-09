from __future__ import annotations

import json


def _result(output: str) -> dict[str, object]:
    parsed = json.loads(output)
    if not isinstance(parsed, dict):
        raise ValueError("wf-status eval output は JSON object でなければなりません")
    return parsed


def _grading_result(passed: bool, success: str, failure: str) -> dict[str, object]:
    return {"pass": passed, "score": 1 if passed else 0, "reason": success if passed else failure}


def skill_invoked(output: str, _context: dict[str, object]) -> dict[str, object]:
    response = _result(output).get("response")
    if not isinstance(response, str):
        raise ValueError("wf-status eval output に response 文字列がありません")
    invoked = "Unknown command: /wf-status" not in response
    return _grading_result(invoked, "wf-status skill を実行", "wf-status skill が解決されていません")


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
