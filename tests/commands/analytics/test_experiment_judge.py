from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from youtube_automation.commands.analytics import experiment as cli
from youtube_automation.core.errors import ValidationError

NOW = datetime(2026, 8, 13, 12, tzinfo=timezone.utc)


def _experiment(
    experiment_id: str = "20260801-thumbnail-next",
    *,
    target: str = "VIDEO_A",
    baseline: float = 100,
    judge_after_days: int = 14,
    status: str = "pending",
    **extra: object,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "id": experiment_id,
        "registered_date": "2026-08-01",
        "lever": "thumbnail",
        "change": "text-heavy -> textless",
        "hypothesis_source": "20260731-analysis-thumbnail",
        "target": target,
        "baseline_vpd": baseline,
        "baseline_basis": "source=yt-vpd-rank; scope=all; n=4; median=100.0; min_age_days=7",
        "judge_after_days": judge_after_days,
        "status": status,
        **extra,
    }


def _detail(
    *,
    views: object,
    published_at: str = "2026-07-24T00:00:00Z",
    privacy_status: str = "public",
    publish_at: str | None = None,
) -> dict[str, object]:
    return {
        "view_count": views,
        "published_at": published_at,
        "privacy_status": privacy_status,
        "publish_at": publish_at,
    }


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record, separators=(",", ":")) + "\n" for record in records), encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _judge(
    root: Path,
    snapshot_loader,
    *,
    min_age_days: int = 7,
    threshold_percent: object = 20,
) -> dict[str, object]:
    return cli.judge_experiments(
        experiments_path=root / "data" / "experiments.jsonl",
        insights_path=root / "data" / "insights.jsonl",
        channel_root=root,
        now=NOW,
        min_age_days=min_age_days,
        threshold_percent=threshold_percent,
        snapshot_loader=snapshot_loader,
    )


@pytest.mark.parametrize(
    "views, expected_verdict, expected_percent",
    [(2400, "improved", 20.0), (1600, "worse", -20.0), (1620, "no_change", -19.0)],
)
def test_due_threshold_is_decimal_and_inclusive_and_commits_insight_once(
    tmp_path, views: int, expected_verdict: str, expected_percent: float
) -> None:
    experiments = tmp_path / "data" / "experiments.jsonl"
    _write_jsonl(experiments, [_experiment()])

    result = _judge(tmp_path, lambda ids: {ids[0]: _detail(views=views)})

    judged = _read_jsonl(experiments)[0]
    insight = _read_jsonl(tmp_path / "data" / "insights.jsonl")[0]
    assert result["judged"][0]["verdict"] == expected_verdict
    assert judged["status"] == "judged"
    assert judged["judged_date"] == "2026-08-13"
    assert judged["result_vpd"] == views / 20
    assert judged["verdict"] == expected_verdict
    assert insight["id"] == "experiment-20260801-thumbnail-next"
    assert insight["source"] == "experiment"
    assert insight["lever"] == "thumbnail"
    assert insight["status"] == "open"
    evidence = json.loads(insight["evidence"])
    assert evidence["percent_change"] == expected_percent
    assert evidence["threshold_percent"] == 20.0

    rerun = _judge(tmp_path, lambda _ids: pytest.fail("already judged must not fetch"))
    assert rerun["skipped"] == [
        {
            "experiment_id": "20260801-thumbnail-next",
            "target": "VIDEO_A",
            "reason": "already_judged",
        }
    ]
    assert len(_read_jsonl(tmp_path / "data" / "insights.jsonl")) == 1


@pytest.mark.parametrize("views, verdict", [(0, "no_change"), (1, "improved")])
def test_zero_baseline_has_defined_verdict_and_null_percent(tmp_path, views: int, verdict: str) -> None:
    experiments = tmp_path / "data" / "experiments.jsonl"
    _write_jsonl(experiments, [_experiment(baseline=0)])

    _judge(tmp_path, lambda ids: {ids[0]: _detail(views=views)})

    insight = _read_jsonl(tmp_path / "data" / "insights.jsonl")[0]
    assert _read_jsonl(experiments)[0]["verdict"] == verdict
    assert json.loads(insight["evidence"])["percent_change"] is None


def test_all_pending_use_one_snapshot_and_expected_skips_do_not_block_due(tmp_path) -> None:
    experiments_path = tmp_path / "data" / "experiments.jsonl"
    _write_jsonl(
        experiments_path,
        [
            _experiment("due-a", target="VIDEO_A"),
            _experiment("due-b", target="VIDEO_B", baseline=50),
            _experiment("not-due", target="VIDEO_C", judge_after_days=30),
            _experiment("not-found", target="VIDEO_MISSING"),
        ],
    )
    calls: list[list[str]] = []

    def snapshot(ids: list[str]) -> dict[str, dict[str, object]]:
        calls.append(ids)
        return {
            "VIDEO_A": _detail(views=2000),
            "VIDEO_B": _detail(views=1200),
            "VIDEO_C": _detail(views=100, published_at="2026-08-03T00:00:00Z"),
        }

    result = _judge(tmp_path, snapshot)

    assert calls == [["VIDEO_A", "VIDEO_B", "VIDEO_C", "VIDEO_MISSING"]]
    assert [item["experiment_id"] for item in result["judged"]] == ["due-a", "due-b"]
    assert result["skipped"] == [
        {"experiment_id": "not-due", "target": "VIDEO_C", "reason": "not_due", "remaining_days": 20},
        {"experiment_id": "not-found", "target": "VIDEO_MISSING", "reason": "target_not_found"},
    ]
    assert len(_read_jsonl(tmp_path / "data" / "insights.jsonl")) == 2


@pytest.mark.parametrize(
    "detail, min_age_days, reason, remaining",
    [
        (_detail(views=10, privacy_status="private"), 7, "unpublished", None),
        (_detail(views=10, publish_at="2026-08-14T00:00:00Z"), 7, "unpublished", None),
        (_detail(views=10, published_at="2026-08-08T00:00:00Z"), 7, "min_age", 2),
    ],
)
def test_unpublished_and_min_age_are_structured_skips_with_byte_identity(
    tmp_path, detail: dict[str, object], min_age_days: int, reason: str, remaining: int | None
) -> None:
    path = tmp_path / "data" / "experiments.jsonl"
    _write_jsonl(path, [_experiment(judge_after_days=2)])
    before = path.read_bytes()

    result = _judge(tmp_path, lambda ids: {ids[0]: detail}, min_age_days=min_age_days)

    expected = {"experiment_id": "20260801-thumbnail-next", "target": "VIDEO_A", "reason": reason}
    if remaining is not None:
        expected["remaining_days"] = remaining
    assert result["skipped"] == [expected]
    assert path.read_bytes() == before
    assert not (tmp_path / "data" / "insights.jsonl").exists()


def test_planning_collection_is_unpublished_without_snapshot_and_bytes_stay_same(tmp_path) -> None:
    (tmp_path / "collections" / "planning" / "next").mkdir(parents=True)
    path = tmp_path / "data" / "experiments.jsonl"
    _write_jsonl(path, [_experiment(target="next")])
    before = path.read_bytes()

    result = _judge(tmp_path, lambda _ids: pytest.fail("planning target must not fetch"))

    assert result["skipped"][0]["reason"] == "unpublished"
    assert path.read_bytes() == before


@pytest.mark.parametrize("source", ["tracking", "workflow_upload"])
def test_live_collection_resolves_video_id_in_contract_order(tmp_path, source: str) -> None:
    collection = tmp_path / "collections" / "live" / "next"
    collection.mkdir(parents=True)
    tracking = collection / "20-documentation" / "upload_tracking.json"
    workflow = collection / "workflow-state.json"
    if source == "tracking":
        _write_object(tracking, {"complete_collection": {"video_id": "FROM_TRACKING"}})
        _write_object(workflow, {"upload": {"video_id": "FROM_UPLOAD"}, "video_id": "FROM_TOP"})
        expected_id = "FROM_TRACKING"
    elif source == "workflow_upload":
        _write_object(tracking, {"complete_collection": {}})
        _write_object(workflow, {"upload": {"video_id": "FROM_UPLOAD"}, "video_id": "FROM_TOP"})
        expected_id = "FROM_UPLOAD"
    _write_jsonl(tmp_path / "data" / "experiments.jsonl", [_experiment(target="next")])
    captured: list[str] = []

    def snapshot(ids: list[str]) -> dict[str, dict[str, object]]:
        captured.extend(ids)
        return {expected_id: _detail(views=2000)}

    _judge(tmp_path, snapshot)
    assert captured == [expected_id]


def test_live_collection_rejects_toplevel_only_video_id_with_canonical_repair_guidance(tmp_path) -> None:
    collection = tmp_path / "collections" / "live" / "next"
    collection.mkdir(parents=True)
    _write_object(collection / "workflow-state.json", {"video_id": "FROM_TOP"})
    _write_jsonl(tmp_path / "data" / "experiments.jsonl", [_experiment(target="next")])

    with pytest.raises(ValidationError) as exc_info:
        _judge(tmp_path, lambda _ids: pytest.fail("legacy top-level video_id must not be fetched"))

    message = str(exc_info.value)
    assert "top-level video_id" in message
    assert "upload.video_id" in message
    assert "yt-workflow-state" in message
    assert "set-upload --video-id <video-id>" in message


def test_non_collection_target_is_exact_video_id_and_missing_is_structured_skip(tmp_path) -> None:
    path = tmp_path / "data" / "experiments.jsonl"
    _write_jsonl(path, [_experiment(target="Exact_ID-9")])
    before = path.read_bytes()
    captured: list[str] = []

    result = _judge(tmp_path, lambda ids: captured.extend(ids) or {})

    assert captured == ["Exact_ID-9"]
    assert result["skipped"][0]["reason"] == "target_not_found"
    assert path.read_bytes() == before


def test_judged_without_insight_and_pending_with_matching_insight_recover_without_snapshot(tmp_path) -> None:
    experiments_path = tmp_path / "data" / "experiments.jsonl"
    insights_path = tmp_path / "data" / "insights.jsonl"
    judged = _experiment(
        "judged-missing",
        target="VIDEO_A",
        status="judged",
        judged_date="2026-08-12",
        result_vpd=120.0,
        verdict="improved",
    )
    pending = _experiment("pending-existing", target="VIDEO_B")
    matching = _insight_for(pending, result_vpd=80.0, verdict="worse", percent_change=-20.0)
    _write_jsonl(experiments_path, [judged, pending])
    _write_jsonl(insights_path, [matching])

    result = _judge(tmp_path, lambda _ids: pytest.fail("recovery must not fetch"))

    records = {entry["id"]: entry for entry in _read_jsonl(experiments_path)}
    assert records["pending-existing"]["status"] == "judged"
    assert records["pending-existing"]["result_vpd"] == 80.0
    assert len(_read_jsonl(insights_path)) == 2
    assert {item["recovery"] for item in result["judged"]} == {"insight_missing", "pending_with_insight"}


def test_conflicting_deterministic_insight_aborts_before_snapshot_and_preserves_both_files(tmp_path) -> None:
    experiments_path = tmp_path / "data" / "experiments.jsonl"
    insights_path = tmp_path / "data" / "insights.jsonl"
    experiment = _experiment()
    _write_jsonl(experiments_path, [experiment])
    conflict = _insight_for(experiment, result_vpd=120, verdict="improved", percent_change=20)
    conflict["source"] = "analysis"
    _write_jsonl(insights_path, [conflict])
    before = (experiments_path.read_bytes(), insights_path.read_bytes())

    with pytest.raises(ValidationError, match="conflict"):
        _judge(tmp_path, lambda _ids: pytest.fail("conflict must fail before snapshot"))

    assert (experiments_path.read_bytes(), insights_path.read_bytes()) == before


def test_interrupted_second_replace_recovers_on_rerun_exactly_once(tmp_path, monkeypatch) -> None:
    experiments_path = tmp_path / "data" / "experiments.jsonl"
    insights_path = tmp_path / "data" / "insights.jsonl"
    _write_jsonl(experiments_path, [_experiment()])
    real_replace = cli.experiment_judge.transaction._replace_file
    replacements = 0

    def fail_second(source: Path, destination: Path) -> None:
        nonlocal replacements
        replacements += 1
        if replacements == 2:
            raise OSError("simulated process interruption")
        real_replace(source, destination)

    monkeypatch.setattr(cli.experiment_judge.transaction, "_replace_file", fail_second)
    with pytest.raises(OSError, match="simulated process interruption"):
        _judge(tmp_path, lambda ids: {ids[0]: _detail(views=2400)})

    monkeypatch.setattr(cli.experiment_judge.transaction, "_replace_file", real_replace)
    result = _judge(tmp_path, lambda _ids: pytest.fail("journal recovery must avoid refetch"))

    assert result["skipped"][0]["reason"] == "already_judged"
    assert _read_jsonl(experiments_path)[0]["status"] == "judged"
    assert len(_read_jsonl(insights_path)) == 1
    assert not (tmp_path / "data" / ".experiment-judge-transaction.json").exists()


@pytest.mark.parametrize("invalid_threshold", [True, "20", float("nan"), -1, 101])
def test_invalid_threshold_or_jsonl_is_hard_error_and_changes_nothing(tmp_path, invalid_threshold: object) -> None:
    experiments_path = tmp_path / "data" / "experiments.jsonl"
    insights_path = tmp_path / "data" / "insights.jsonl"
    experiments_path.parent.mkdir(parents=True)
    experiments_path.write_text("not json\n", encoding="utf-8")
    insights_path.write_text("sentinel\n", encoding="utf-8")
    before = (experiments_path.read_bytes(), insights_path.read_bytes())

    with pytest.raises(ValidationError):
        _judge(tmp_path, lambda _ids: pytest.fail("invalid input must not fetch"))
    assert (experiments_path.read_bytes(), insights_path.read_bytes()) == before

    _write_jsonl(experiments_path, [_experiment()])
    before = (experiments_path.read_bytes(), insights_path.read_bytes())
    with pytest.raises(ValidationError, match="threshold"):
        _judge(
            tmp_path,
            lambda _ids: pytest.fail("invalid config must not fetch"),
            threshold_percent=invalid_threshold,
        )
    assert (experiments_path.read_bytes(), insights_path.read_bytes()) == before


def test_judge_cli_wires_configured_threshold_and_outputs_structured_result(tmp_path, monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    def fake_judge(**kwargs):
        captured.update(kwargs)
        return {"status": "ok", "judged": [], "skipped": []}

    monkeypatch.setattr(cli, "channel_dir", lambda: tmp_path)
    monkeypatch.setattr(
        cli,
        "load_skill_config",
        lambda _name: {"experiment": {"judge_after_days": 14, "judge_threshold_percent": 20}},
    )
    monkeypatch.setattr(cli, "judge_experiments", fake_judge)

    assert cli.main(["judge", "--min-age-days", "9"]) == 0
    assert json.loads(capsys.readouterr().out) == {"status": "ok", "judged": [], "skipped": []}
    assert captured["experiments_path"] == tmp_path / "data" / "experiments.jsonl"
    assert captured["insights_path"] == tmp_path / "data" / "insights.jsonl"
    assert captured["min_age_days"] == 9
    assert captured["threshold_percent"] == 20


def _write_object(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _insight_for(
    experiment: dict[str, object], *, result_vpd: float, verdict: str, percent_change: float | None
) -> dict[str, object]:
    experiment_id = str(experiment["id"])
    evidence = {
        "experiment_id": experiment_id,
        "baseline_vpd": experiment["baseline_vpd"],
        "result_vpd": result_vpd,
        "percent_change": percent_change,
        "threshold_percent": 20.0,
        "verdict": verdict,
    }
    return {
        "schema_version": 1,
        "id": f"experiment-{experiment_id}",
        "date": "2026-08-13",
        "source": "experiment",
        "source_path": "data/experiments.jsonl",
        "lever": experiment["lever"],
        "finding": "experiment result",
        "recommended_action": "use result",
        "evidence": json.dumps(evidence, separators=(",", ":")),
        "status": "open",
    }
