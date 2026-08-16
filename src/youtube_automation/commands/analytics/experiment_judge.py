"""experiment 判定と insights 還流を recoverable な一体更新として扱う。"""

from __future__ import annotations

import json
import math
import stat
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from youtube_automation.commands.analytics import experiment_transaction as transaction
from youtube_automation.commands.analytics.analytics_system import AnalyticsSystem
from youtube_automation.core.errors import AuthError, ValidationError, WorkflowStateError
from youtube_automation.domains.collections.workflow_state import read as read_workflow_state
from youtube_automation.infrastructure.analytics.vpd_metrics import _parse_view_count, _published_utc

_VERDICTS = frozenset({"improved", "no_change", "worse"})


@dataclass(frozen=True)
class TargetResolution:
    video_id: str | None
    skip_reason: str | None


@dataclass
class JudgePlan:
    replacements: dict[str, dict[str, object]] = field(default_factory=dict)
    insights: list[dict[str, object]] = field(default_factory=list)
    judged: list[dict[str, object]] = field(default_factory=list)
    skipped: list[dict[str, object]] = field(default_factory=list)
    snapshot_candidates: list[tuple[dict[str, object], str]] = field(default_factory=list)


def _experiment_module():
    from youtube_automation.commands.analytics import experiment

    return experiment


def _bytes(path: Path) -> bytes:
    if not path.exists():
        return b""
    try:
        mode = path.lstat().st_mode
    except OSError as error:
        raise ValidationError(f"JSONL を確認できません: {path}") from error
    if not stat.S_ISREG(mode):
        raise ValidationError(f"JSONL は regular file である必要があります: {path}")
    try:
        return path.read_bytes()
    except OSError as error:
        raise ValidationError(f"JSONL を読めません: {path}") from error


def _decode_json_lines(
    path: Path,
    content: bytes,
    schema: dict[str, object],
    insights_schema: dict[str, object],
) -> list[dict[str, object]]:
    experiment = _experiment_module()
    try:
        text = content.decode("utf-8")
    except UnicodeError as error:
        raise ValidationError(f"JSONL が UTF-8 ではありません: {path}") from error
    entries: list[dict[str, object]] = []
    failures: list[str] = []
    seen: dict[str, int] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            entry = json.loads(raw_line)
        except json.JSONDecodeError as error:
            failures.append(f"line {line_number}: JSON として不正です: {error.msg}")
            continue
        failures.extend(
            f"line {line_number}: schema 違反: {message}"
            for message in experiment.validate_entry(entry, schema, insights_schema)
        )
        if not isinstance(entry, dict):
            continue
        entry_id = entry.get("id")
        if isinstance(entry_id, str) and entry_id:
            if entry_id in seen:
                failures.append(f"line {line_number}: id {entry_id!r} が line {seen[entry_id]} と重複しています")
            else:
                seen[entry_id] = line_number
        entries.append(entry)
    if failures:
        raise ValidationError(f"{path} の検証に失敗しました: " + "; ".join(failures))
    return entries


def _read_insights(path: Path) -> tuple[bytes, list[dict[str, object]]]:
    content = _bytes(path)
    _, insights_schema = _experiment_module().load_schema()
    return content, _decode_json_lines(path, content, insights_schema, insights_schema)


def _json_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValidationError(f"collection state JSON を読めません: {path}") from error
    if not isinstance(value, dict):
        raise ValidationError(f"collection state JSON は object である必要があります: {path}")
    return value


def _nested_video_id(value: object, *keys: str) -> str | None:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    if current is None:
        return None
    if not isinstance(current, str) or not current.strip():
        raise ValidationError(f"{'.'.join(keys)} は空でない video_id にしてください")
    return current.strip()


def _workflow_video_id(path: Path) -> str | None:
    try:
        state = read_workflow_state(path)
        upload = state.upload
        value = upload.video_id if upload is not None else None
        if value is None and "video_id" in state:
            raise ValidationError(
                "workflow-state.json の top-level video_id はサポートされていません。"
                "正準キー upload.video_id へ修復してください:\n"
                f'uv run yt-workflow-state --collection "{path.parent}" '
                "set-upload --video-id <video-id>"
            )
    except WorkflowStateError as error:
        raise ValidationError(f"collection state JSON を読めません: {path}") from error
    if value is None:
        return None
    if not value.strip():
        raise ValidationError("upload.video_id は空でない video_id にしてください")
    return value.strip()


def resolve_target(channel_root: Path, target: str) -> TargetResolution:
    if Path(target).name != target or target in {".", ".."}:
        return TargetResolution(target, None)
    live = channel_root / "collections" / "live" / target
    planning = channel_root / "collections" / "planning" / target
    if live.is_dir():
        tracking_path = live / "20-documentation" / "upload_tracking.json"
        workflow_path = live / "workflow-state.json"
        tracking = _json_object(tracking_path) if tracking_path.exists() else {}
        video_id = (
            _nested_video_id(tracking, "complete_collection", "video_id")
            or (_workflow_video_id(workflow_path) if workflow_path.exists() else None)
            or _nested_video_id(tracking, "video_id")
        )
        return TargetResolution(video_id, None if video_id is not None else "unpublished")
    if planning.is_dir():
        return TargetResolution(None, "unpublished")
    return TargetResolution(target, None)


def load_judge_snapshot(video_ids: list[str]) -> dict[str, dict[str, object]]:
    system = AnalyticsSystem()
    if not system.authenticate() or system.collector is None:
        raise AuthError("YouTube read-only 認証に失敗しました")
    return system.collector.get_video_details(video_ids)


def _threshold(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError("judge threshold は 0 以上 100 以下の finite number にしてください")
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as error:
        raise ValidationError("judge threshold は 0 以上 100 以下の finite number にしてください") from error
    if not parsed.is_finite() or parsed < 0 or parsed > 100:
        raise ValidationError("judge threshold は 0 以上 100 以下の finite number にしてください")
    return parsed


def _nonnegative_integer(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValidationError(f"{name} は 0 以上の integer にしてください")
    return value


def _iso_datetime(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValidationError(f"{name} が不正です")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValidationError(f"{name} が不正です") from error
    if parsed.tzinfo is None:
        raise ValidationError(f"{name} に timezone がありません")
    return parsed.astimezone(timezone.utc)


def _published_state(detail: object, video_id: str, now: datetime) -> tuple[str | None, int | None]:
    if not isinstance(detail, dict):
        raise ValidationError(f"videos.list detail が object ではありません: {video_id}")
    privacy = detail.get("privacy_status")
    if not isinstance(privacy, str) or not privacy:
        raise ValidationError(f"videos.list status.privacyStatus がありません: {video_id}")
    publish_at = detail.get("publish_at")
    if publish_at is not None and _iso_datetime(publish_at, "videos.list status.publishAt") > now:
        return "unpublished", None
    if privacy != "public":
        return "unpublished", None
    published = _published_utc(detail.get("published_at"), video_id)
    age_days = max(0, (now.astimezone(timezone.utc).date() - published.date()).days)
    return None, age_days


def _result(detail: dict[str, object], video_id: str, age_days: int) -> tuple[Decimal, float]:
    views = _parse_view_count(detail.get("view_count"), video_id)
    exact = Decimal(views) / Decimal(max(1, age_days))
    return exact, round(float(exact), 6)


def _verdict(baseline_value: object, result: Decimal, threshold: Decimal) -> tuple[str, float | None]:
    if isinstance(baseline_value, bool) or not isinstance(baseline_value, (int, float)):
        raise ValidationError("baseline_vpd が不正です")
    baseline = Decimal(str(baseline_value))
    if not baseline.is_finite() or baseline < 0:
        raise ValidationError("baseline_vpd が不正です")
    if baseline == 0:
        return ("no_change" if result == 0 else "improved"), None
    ratio = threshold / Decimal(100)
    if result >= baseline * (Decimal(1) + ratio):
        verdict = "improved"
    elif result <= baseline * (Decimal(1) - ratio):
        verdict = "worse"
    else:
        verdict = "no_change"
    percent = ((result - baseline) / baseline) * Decimal(100)
    return verdict, round(float(percent), 6)


def _evidence(
    experiment: dict[str, object], result_vpd: float, percent: float | None, threshold: Decimal, verdict: str
) -> str:
    return json.dumps(
        {
            "experiment_id": experiment["id"],
            "baseline_vpd": experiment["baseline_vpd"],
            "result_vpd": result_vpd,
            "percent_change": percent,
            "threshold_percent": float(threshold),
            "verdict": verdict,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def _insight(
    experiment: dict[str, object],
    judged_date: str,
    result_vpd: float,
    percent: float | None,
    threshold: Decimal,
    verdict: str,
) -> dict[str, object]:
    recommendation = (
        f"次サイクルで {experiment['change']} を採用候補にする"
        if verdict == "improved"
        else f"次サイクルでは {experiment['change']} を再採用せず再検討する"
    )
    return {
        "schema_version": 1,
        "id": f"experiment-{experiment['id']}",
        "date": judged_date,
        "source": "experiment",
        "source_path": "data/experiments.jsonl",
        "lever": experiment["lever"],
        "finding": f"{experiment['change']} で VPD が {experiment['baseline_vpd']} から {result_vpd} へ変化した",
        "recommended_action": recommendation,
        "evidence": _evidence(experiment, result_vpd, percent, threshold, verdict),
        "status": "open",
    }


def _matching_evidence(insight: dict[str, object], experiment: dict[str, object]) -> dict[str, object]:
    expected_id = f"experiment-{experiment['id']}"
    if insight.get("id") != expected_id or insight.get("source") != "experiment":
        raise ValidationError(f"experiment insight conflict: {expected_id}")
    if insight.get("lever") != experiment.get("lever"):
        raise ValidationError(f"experiment insight conflict: lever mismatch: {expected_id}")
    evidence_text = insight.get("evidence")
    try:
        evidence = json.loads(evidence_text) if isinstance(evidence_text, str) else None
    except json.JSONDecodeError as error:
        raise ValidationError(f"experiment insight conflict: evidence JSON: {expected_id}") from error
    if not isinstance(evidence, dict) or evidence.get("experiment_id") != experiment.get("id"):
        raise ValidationError(f"experiment insight conflict: experiment_id mismatch: {expected_id}")
    result = evidence.get("result_vpd")
    verdict = evidence.get("verdict")
    baseline = evidence.get("baseline_vpd")
    percent = evidence.get("percent_change")
    evidence_threshold = evidence.get("threshold_percent")
    if (
        isinstance(result, bool)
        or not isinstance(result, (int, float))
        or not math.isfinite(result)
        or result < 0
        or verdict not in _VERDICTS
        or baseline != experiment.get("baseline_vpd")
    ):
        raise ValidationError(f"experiment insight conflict: result contract: {expected_id}")
    try:
        threshold = _threshold(evidence_threshold)
        expected_verdict, expected_percent = _verdict(baseline, Decimal(str(result)), threshold)
    except ValidationError as error:
        raise ValidationError(f"experiment insight conflict: evidence contract: {expected_id}") from error
    if verdict != expected_verdict or percent != expected_percent:
        raise ValidationError(f"experiment insight conflict: verdict mismatch: {expected_id}")
    return evidence


def _judged_record(
    experiment: dict[str, object], judged_date: str, result_vpd: float, verdict: str
) -> dict[str, object]:
    return {
        **experiment,
        "status": "judged",
        "judged_date": judged_date,
        "result_vpd": result_vpd,
        "verdict": verdict,
    }


def _skip(experiment: dict[str, object], reason: str, remaining_days: int | None = None) -> dict[str, object]:
    result: dict[str, object] = {
        "experiment_id": experiment["id"],
        "target": experiment["target"],
        "reason": reason,
    }
    if remaining_days is not None:
        result["remaining_days"] = remaining_days
    return result


def _judged_output(
    experiment: dict[str, object], video_id: str | None, result_vpd: float, verdict: str, recovery: str | None = None
) -> dict[str, object]:
    output: dict[str, object] = {
        "experiment_id": experiment["id"],
        "target": experiment["target"],
        "video_id": video_id,
        "result_vpd": result_vpd,
        "verdict": verdict,
    }
    if recovery is not None:
        output["recovery"] = recovery
    return output


def _validate_matching_judged(
    experiment: dict[str, object], insight: dict[str, object], evidence: dict[str, object]
) -> None:
    if (
        experiment.get("judged_date") != insight.get("date")
        or experiment.get("result_vpd") != evidence.get("result_vpd")
        or experiment.get("verdict") != evidence.get("verdict")
    ):
        raise ValidationError(f"experiment insight conflict: judged mismatch: {experiment['id']}")


def _plan_existing(
    experiments: list[dict[str, object]],
    insights: list[dict[str, object]],
    channel_root: Path,
    threshold: Decimal,
) -> JudgePlan:
    plan = JudgePlan()
    insight_by_id = {str(entry["id"]): entry for entry in insights}
    for entry in experiments:
        entry_id = str(entry["id"])
        matching = insight_by_id.get(f"experiment-{entry_id}")
        if matching is not None:
            evidence = _matching_evidence(matching, entry)
            if entry.get("status") == "judged":
                _validate_matching_judged(entry, matching, evidence)
                plan.skipped.append(_skip(entry, "already_judged"))
            else:
                plan.replacements[entry_id] = _judged_record(
                    entry, str(matching["date"]), float(evidence["result_vpd"]), str(evidence["verdict"])
                )
                plan.judged.append(
                    _judged_output(
                        entry,
                        None,
                        float(evidence["result_vpd"]),
                        str(evidence["verdict"]),
                        "pending_with_insight",
                    )
                )
            continue
        if entry.get("status") == "judged":
            result_vpd = float(entry["result_vpd"])
            verdict = str(entry["verdict"])
            _, percent = _verdict(entry["baseline_vpd"], Decimal(str(result_vpd)), threshold)
            plan.insights.append(_insight(entry, str(entry["judged_date"]), result_vpd, percent, threshold, verdict))
            plan.judged.append(_judged_output(entry, None, result_vpd, verdict, "insight_missing"))
            continue
        resolution = resolve_target(channel_root, str(entry["target"]))
        if resolution.skip_reason is not None:
            plan.skipped.append(_skip(entry, resolution.skip_reason))
            continue
        assert resolution.video_id is not None
        plan.snapshot_candidates.append((entry, resolution.video_id))
    return plan


def _load_snapshot(
    candidates: list[tuple[dict[str, object], str]],
    loader: Callable[[list[str]], dict[str, dict[str, object]]],
) -> dict[str, dict[str, object]]:
    if not candidates:
        return {}
    video_ids = list(dict.fromkeys(video_id for _, video_id in candidates))
    snapshot = loader(video_ids)
    if not isinstance(snapshot, dict):
        raise ValidationError("judge snapshot は video_id keyed object にしてください")
    return snapshot


def _apply_snapshot(
    plan: JudgePlan,
    snapshot: dict[str, dict[str, object]],
    now: datetime,
    min_age: int,
    threshold: Decimal,
) -> None:
    judged_date = now.astimezone(timezone.utc).date().isoformat()
    for entry, video_id in plan.snapshot_candidates:
        detail = snapshot.get(video_id)
        if detail is None:
            plan.skipped.append(_skip(entry, "target_not_found"))
            continue
        skip_reason, age_days = _published_state(detail, video_id, now.astimezone(timezone.utc))
        if skip_reason is not None:
            plan.skipped.append(_skip(entry, skip_reason))
            continue
        assert age_days is not None and isinstance(detail, dict)
        judge_after_days = int(entry["judge_after_days"])
        if age_days < judge_after_days:
            plan.skipped.append(_skip(entry, "not_due", judge_after_days - age_days))
            continue
        if age_days < min_age:
            plan.skipped.append(_skip(entry, "min_age", min_age - age_days))
            continue
        exact_result, result_vpd = _result(detail, video_id, age_days)
        verdict, percent = _verdict(entry["baseline_vpd"], exact_result, threshold)
        plan.replacements[str(entry["id"])] = _judged_record(entry, judged_date, result_vpd, verdict)
        plan.insights.append(_insight(entry, judged_date, result_vpd, percent, threshold, verdict))
        plan.judged.append(_judged_output(entry, video_id, result_vpd, verdict))


def _commit_plan(
    plan: JudgePlan,
    experiments_path: Path,
    insights_path: Path,
    experiments_before: bytes,
    insights_before: bytes,
) -> None:
    if not plan.replacements and not plan.insights:
        return
    experiments_after = transaction.rewrite_jsonl(experiments_before, plan.replacements)
    insights_after = transaction.append_jsonl(insights_before, plan.insights)
    experiment = _experiment_module()
    experiment_schema, insights_schema = experiment.load_schema()
    _decode_json_lines(experiments_path, experiments_after, experiment_schema, insights_schema)
    _decode_json_lines(insights_path, insights_after, insights_schema, insights_schema)
    transaction.commit_pair(
        (experiments_path, insights_path),
        (experiments_before, insights_before),
        (experiments_after, insights_after),
    )


def judge_experiments(
    *,
    experiments_path: Path,
    insights_path: Path,
    channel_root: Path,
    now: datetime,
    min_age_days: int,
    threshold_percent: object,
    snapshot_loader: Callable[[list[str]], dict[str, dict[str, object]]],
) -> dict[str, object]:
    if now.tzinfo is None:
        raise ValidationError("judge now は timezone-aware datetime にしてください")
    min_age = _nonnegative_integer("min_age_days", min_age_days)
    threshold = _threshold(threshold_percent)
    journal = experiments_path.parent / transaction.JOURNAL_NAME
    transaction.recover(journal, (experiments_path, insights_path))
    experiment = _experiment_module()
    experiments_before, experiments = experiment._read_entries(experiments_path)
    insights_before, insights = _read_insights(insights_path)
    plan = _plan_existing(experiments, insights, channel_root, threshold)
    snapshot = _load_snapshot(plan.snapshot_candidates, snapshot_loader)
    _apply_snapshot(plan, snapshot, now, min_age, threshold)
    _commit_plan(plan, experiments_path, insights_path, experiments_before, insights_before)
    return {"status": "ok", "judged": plan.judged, "skipped": plan.skipped}
