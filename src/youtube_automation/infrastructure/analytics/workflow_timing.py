"""Dashboard 向け workflow timing read adapter。"""

from __future__ import annotations

import importlib.util
import sys
from functools import cache
from importlib.resources import as_file, files
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast


class _TimingRunner(Protocol):
    NoActiveCollectionError: type[ValueError]

    def read_history(self, root: Path) -> dict[str, object]: ...

    def select_collection(self, root: Path, requested: str | None = None) -> Path: ...

    def _collection_sort_key(self, collection: Path) -> tuple[str, str]: ...

    def summarize_time_savings(
        self,
        history: dict[str, object],
        manual_baseline_minutes: dict[str, float] | None,
    ) -> dict[str, object]: ...


def _load_module(path: Path) -> _TimingRunner:
    module_name = "youtube_automation._wf_auto_state_dashboard"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"wf-auto timing module をロードできません: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return cast(_TimingRunner, cast(ModuleType, module))


@cache
def _runner() -> _TimingRunner:
    resource = files("youtube_automation").joinpath("_skills", "wf-auto", "references", "wf-auto-state.py")
    with as_file(resource) as resource_path:
        if resource_path.is_file():
            return _load_module(resource_path)
    source_path = (
        Path(__file__).resolve().parents[4] / ".claude" / "skills" / "wf-auto" / "references" / "wf-auto-state.py"
    )
    if not source_path.is_file():
        raise RuntimeError("wf-auto-state.py が package resource と source checkout のどちらにもありません")
    return _load_module(source_path)


def _selected_collections(channel: Path, runner: _TimingRunner) -> list[tuple[str, Path]]:
    selected: list[tuple[str, Path]] = []
    try:
        active = runner.select_collection(channel)
    except runner.NoActiveCollectionError:
        active = None
    if active is not None:
        selected.append(("planning", active))

    live_states = list((channel / "collections" / "live").glob("*/workflow-state.json"))
    if live_states:
        latest_path = max((state.parent for state in live_states), key=runner._collection_sort_key)
        latest = runner.select_collection(channel, str(latest_path.resolve()))
        if active is None or latest != active:
            selected.append(("live", latest))
    return selected


def _collection_history(history: dict[str, object], channel: Path, collection: Path) -> dict[str, object]:
    attempts = history.get("attempts")
    if not isinstance(attempts, list):
        raise ValueError("workflow history は attempts array を持つ必要があります")
    relative = collection.relative_to(channel).as_posix()
    filtered = [attempt for attempt in attempts if isinstance(attempt, dict) and attempt.get("collection") == relative]
    return {**history, "attempts": filtered}


def _latest_statuses(history: dict[str, object]) -> dict[str, str]:
    attempts = history.get("attempts")
    if not isinstance(attempts, list):
        raise ValueError("workflow history は attempts array を持つ必要があります")
    statuses: dict[str, str] = {}
    for attempt in attempts:
        if not isinstance(attempt, dict):
            raise ValueError("workflow history attempt は object でなければなりません")
        action = attempt.get("action")
        status = attempt.get("status")
        if not isinstance(action, str) or status not in {"success", "blocked", "failed"}:
            raise ValueError("workflow history attempt の action/status が不正です")
        statuses[action] = cast(str, status)
    return statuses


def _six_metrics(values: dict[str, object]) -> dict[str, object]:
    ai_seconds = values["ai_seconds"]
    human_seconds = values["human_seconds"]
    if not isinstance(ai_seconds, (int, float)) or not isinstance(human_seconds, (int, float)):
        raise ValueError("workflow timing の AI / human 秒が number ではありません")
    return {
        "manual_baseline_seconds": values["manual_baseline_seconds"],
        "ai_seconds": ai_seconds,
        "human_seconds": human_seconds,
        "work_seconds": ai_seconds + human_seconds,
        "ai_inclusive_saved_seconds": values["ai_inclusive_saved_seconds"],
        "human_freed_seconds": values["human_freed_seconds"],
    }


def _collection_summary(
    channel: Path,
    collection: Path,
    stage: str,
    history: dict[str, object],
    manual_baseline_minutes: dict[str, float] | None,
    runner: _TimingRunner,
) -> dict[str, object]:
    scoped_history = _collection_history(history, channel, collection)
    summary = runner.summarize_time_savings(scoped_history, manual_baseline_minutes)
    if summary.get("available") is not True:
        raise ValueError(f"workflow timing を集計できません: {summary.get('reason')}")
    actions = summary.get("actions")
    totals = summary.get("totals")
    if not isinstance(actions, dict) or not isinstance(totals, dict):
        raise ValueError("available workflow timing に actions/totals がありません")
    statuses = _latest_statuses(scoped_history)
    steps = []
    for action, raw_metrics in actions.items():
        if not isinstance(action, str) or not isinstance(raw_metrics, dict):
            raise ValueError("workflow timing action summary が不正です")
        steps.append({"action": action, "status": statuses[action], **_six_metrics(raw_metrics)})
    return {
        "collection_id": collection.name,
        "stage": stage,
        "steps": steps,
        "totals": _six_metrics(totals),
    }


def build_workflow_timing(
    channel: Path,
    manual_baseline_minutes: dict[str, float] | None,
) -> dict[str, object]:
    """active planning と latest live の timing summary を返す。"""
    channel = channel.resolve()
    runner = _runner()
    history = runner.read_history(channel)
    collections = [
        _collection_summary(channel, collection, stage, history, manual_baseline_minutes, runner)
        for stage, collection in _selected_collections(channel, runner)
    ]
    return {"collections": collections}
