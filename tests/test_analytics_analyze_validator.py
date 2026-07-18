"""analytics-analyze の analysis JSON / Markdown validator 契約テスト。"""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / ".claude/skills/analytics-analyze/references/analysis-json-validator.md"


def _validator_script() -> str:
    text = VALIDATOR.read_text(encoding="utf-8")
    execution = text.split("## 実行", 1)[1]
    return execution.split("```bash\n", 1)[1].split("\n```", 1)[0].replace("analysis_YYYYMMDD", "analysis_20260717")


def _write_fixture(
    tmp_path: Path,
    *,
    depth: str,
    extra_citations: tuple[str, ...] = (),
    retention_override: list[dict] | None = None,
) -> None:
    analytics_path = tmp_path / "data/analytics_data_20260717_120000.json"
    daily_path = tmp_path / "data/analytics/daily_per_video/2026-06-17_to_2026-07-17.json"
    content_path = tmp_path / "config/channel/content.json"
    report_path = tmp_path / "reports/analysis_20260717.json"
    markdown_path = tmp_path / "reports/analysis_20260717.md"
    for path in (analytics_path, daily_path, content_path, report_path, markdown_path):
        path.parent.mkdir(parents=True, exist_ok=True)

    retention = retention_override or [
        {
            "video_id": "VID_1",
            "average_retention": 0.62,
            "midpoint_retention": 0.55,
            "data_points": 2,
            "retention_curve": [
                {"elapsed_ratio": 0.0, "watch_ratio": 0.9, "relative_performance": 0.1},
                {"elapsed_ratio": 0.5, "watch_ratio": 0.55, "relative_performance": -0.1},
            ],
        }
    ]
    analytics = {
        "collection_depth": depth,
        "retention": retention,
    }
    analytics_path.write_text(json.dumps(analytics), encoding="utf-8")
    daily_path.write_text("{}", encoding="utf-8")
    content_path.write_text("{}", encoding="utf-8")

    report = {
        "schema_version": 2,
        "generated_at": "2026-07-17T03:00:00Z",
        "inputs": {
            "analysis_target": str(analytics_path.relative_to(tmp_path)),
            "cli_selected": [
                str(analytics_path.relative_to(tmp_path)),
                str(daily_path.relative_to(tmp_path)),
                str(content_path.relative_to(tmp_path)),
            ],
            "supplemental": [],
        },
        "commands": {
            "launch_curve": "uv run yt-launch-curve --latest",
            "channel_trend": "uv run yt-channel-trend",
            "theme_compare": "uv run yt-theme-compare",
            "traffic_trend": "uv run yt-traffic-trend",
        },
        "cli_outputs": {
            "launch_curve": {"target": {"ratio_vs_median": 1.42}},
            "channel_trend": {"summary": {"wow_growth_rate": 8.5}},
            "theme_compare": {"themes": [{"day7_mean": 1234.0}]},
            "traffic_trend": {"summary": {"top_source_share_percent": 45.2}},
        },
        "ttp_health": {
            "status": "ok",
            "source": "benchmark_20260715.json",
            "reference_date": "2026-07-15",
            "thresholds": {"stale_days": 60, "decline_ratio": 0.5, "window_days": 90},
            "channels": [
                {
                    "slug": "rival",
                    "name": "Rival",
                    "channel_id": "UC_RIVAL",
                    "status": "healthy",
                    "last_upload_at": "2026-07-01",
                    "days_since_last_upload": 14,
                    "recent_window": {
                        "start": "2026-04-16",
                        "end": "2026-07-15",
                        "video_count": 2,
                        "avg_views": 20000,
                    },
                    "prior_window": {
                        "start": "2026-01-16",
                        "end": "2026-04-15",
                        "video_count": 2,
                        "avg_views": 18000,
                    },
                    "alerts": [],
                    "insufficiencies": [],
                }
            ],
        },
        "ctr_strategy": [],
        "channel_performance": [],
        "strategic_improvements": [
            {
                "statement": "改善",
                "evidence": [
                    {
                        "source": "launch_curve",
                        "json_path": "$.cli_outputs.launch_curve.target.ratio_vs_median",
                        "value": 1.42,
                    }
                ],
                "confidence": "high",
            },
            {
                "statement": "流入源改善",
                "evidence": [
                    {
                        "source": "traffic_trend",
                        "json_path": "$.cli_outputs.traffic_trend.summary.top_source_share_percent",
                        "value": 45.2,
                    }
                ],
                "confidence": "medium",
            },
        ],
        "next_collection_candidates": [
            {
                "statement": "候補",
                "evidence": [
                    {
                        "source": "theme_compare",
                        "json_path": "$.cli_outputs.theme_compare.themes[0].day7_mean",
                        "value": 1234.0,
                    }
                ],
                "confidence": "medium",
            }
        ],
        "action_plan": [],
        "strategic_discussion": [
            {
                "statement": "示唆",
                "evidence": [
                    {
                        "source": "channel_trend",
                        "json_path": "$.cli_outputs.channel_trend.summary.wow_growth_rate",
                        "value": 8.5,
                    }
                ],
                "confidence": "low",
            }
        ],
    }
    if depth == "full":
        report["retention_analysis"] = {
            "source": str(analytics_path.relative_to(tmp_path)),
            "unit": "ratio",
            "hypothesis_evaluation": "supported",
            "summary": "中盤の低下が中身の弱さ仮説を支持する。",
            "videos": [
                {
                    "retention_index": 0,
                    "video_id": "VID_1",
                    "average_retention": 0.62,
                    "midpoint_retention": 0.55,
                    "drop_point_index": 1,
                    "drop_point": {"elapsed_ratio": 0.5, "watch_ratio": 0.55},
                }
            ],
        }
    report_path.write_text(json.dumps(report), encoding="utf-8")

    citations = [
        "analysis_20260717.json#$.cli_outputs.launch_curve.target.ratio_vs_median = 1.42",
        "analysis_20260717.json#$.cli_outputs.channel_trend.summary.wow_growth_rate = 8.5",
        "analysis_20260717.json#$.cli_outputs.theme_compare.themes[0].day7_mean = 1234.0",
        "analysis_20260717.json#$.cli_outputs.traffic_trend.summary.top_source_share_percent = 45.2",
    ]
    citations.extend(extra_citations)
    markdown_path.write_text("\n".join(citations) + "\n", encoding="utf-8")


def _append_retention_section(tmp_path: Path) -> None:
    markdown_path = tmp_path / "reports/analysis_20260717.md"
    section = (
        "## 視聴維持率分析",
        "入力: data/analytics_data_20260717_120000.json",
        "単位: ratio",
        "仮説評価: supported",
        "対象動画: VID_1",
        "動画間比較: 有効な維持率データが1本のため動画間比較は不可。",
    )
    with markdown_path.open("a", encoding="utf-8") as markdown:
        markdown.write("\n".join(section) + "\n")


def _append_standard_retention_section(tmp_path: Path) -> None:
    markdown_path = tmp_path / "reports/analysis_20260717.md"
    section = (
        "## 視聴維持率分析",
        "状態: full 収集が必要",
    )
    with markdown_path.open("a", encoding="utf-8") as markdown:
        markdown.write("\n".join(section) + "\n")


def _remove_retention_analysis(tmp_path: Path) -> None:
    report_path = tmp_path / "reports/analysis_20260717.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    del report["retention_analysis"]
    report_path.write_text(json.dumps(report), encoding="utf-8")


def _run_validator(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", _validator_script()],
        cwd=tmp_path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_full_report_without_numeric_retention_citation_fails(tmp_path: Path) -> None:
    _write_fixture(tmp_path, depth="full")

    assert _run_validator(tmp_path).returncode != 0


def test_full_report_with_numeric_retention_citation_passes(tmp_path: Path) -> None:
    _write_fixture(
        tmp_path,
        depth="full",
        extra_citations=(
            "analytics_data_20260717_120000.json#$.retention[0].average_retention = 0.62",
            "analytics_data_20260717_120000.json#$.retention[0].midpoint_retention = 0.55",
            "analytics_data_20260717_120000.json#$.retention[0].retention_curve[1].elapsed_ratio = 0.5",
            "analytics_data_20260717_120000.json#$.retention[0].retention_curve[1].watch_ratio = 0.55",
        ),
    )
    _append_retention_section(tmp_path)

    result = _run_validator(tmp_path)

    assert result.returncode == 0, result.stderr


def test_full_report_with_citation_but_without_retention_analysis_section_fails(tmp_path: Path) -> None:
    _write_fixture(
        tmp_path,
        depth="full",
        extra_citations=("analytics_data_20260717_120000.json#$.retention[0].average_retention = 0.62",),
    )

    assert _run_validator(tmp_path).returncode != 0


def test_full_report_without_structured_retention_analysis_fails(tmp_path: Path) -> None:
    _write_fixture(
        tmp_path,
        depth="full",
        extra_citations=("analytics_data_20260717_120000.json#$.retention[0].average_retention = 0.62",),
    )
    _append_retention_section(tmp_path)
    _remove_retention_analysis(tmp_path)

    assert _run_validator(tmp_path).returncode != 0


def test_full_report_rejects_api_error_values_as_retention_evidence(tmp_path: Path) -> None:
    failed_retention = [
        {
            "video_id": "VID_1",
            "average_retention": 0.62,
            "midpoint_retention": 0.55,
            "data_points": 2,
            "retention_curve": [
                {"elapsed_ratio": 0.0, "watch_ratio": 0.9, "relative_performance": 0.1},
                {"elapsed_ratio": 0.5, "watch_ratio": 0.55, "relative_performance": -0.1},
            ],
            "error": "YouTube Analytics API request failed",
        }
    ]
    _write_fixture(
        tmp_path,
        depth="full",
        retention_override=failed_retention,
        extra_citations=("analytics_data_20260717_120000.json#$.retention[0].average_retention = 0.62",),
    )
    _append_retention_section(tmp_path)

    assert _run_validator(tmp_path).returncode != 0


def test_full_report_rejects_zero_retention_data_points(tmp_path: Path) -> None:
    zero_data_points = [
        {
            "video_id": "VID_1",
            "average_retention": 0.62,
            "midpoint_retention": 0.55,
            "data_points": 0,
            "retention_curve": [
                {"elapsed_ratio": 0.0, "watch_ratio": 0.9, "relative_performance": 0.1},
                {"elapsed_ratio": 0.5, "watch_ratio": 0.55, "relative_performance": -0.1},
            ],
        }
    ]
    _write_fixture(
        tmp_path,
        depth="full",
        retention_override=zero_data_points,
        extra_citations=("analytics_data_20260717_120000.json#$.retention[0].average_retention = 0.62",),
    )
    _append_retention_section(tmp_path)

    assert _run_validator(tmp_path).returncode != 0


def test_full_report_rejects_empty_retention_curve(tmp_path: Path) -> None:
    empty_curve = [
        {
            "video_id": "VID_1",
            "average_retention": 0.62,
            "midpoint_retention": 0.55,
            "data_points": 1,
            "retention_curve": [],
        }
    ]
    _write_fixture(
        tmp_path,
        depth="full",
        retention_override=empty_curve,
        extra_citations=("analytics_data_20260717_120000.json#$.retention[0].average_retention = 0.62",),
    )
    _append_retention_section(tmp_path)

    assert _run_validator(tmp_path).returncode != 0


def test_full_report_must_analyze_every_valid_retention_video(tmp_path: Path) -> None:
    _write_fixture(
        tmp_path,
        depth="full",
        extra_citations=(
            "analytics_data_20260717_120000.json#$.retention[0].average_retention = 0.62",
            "analytics_data_20260717_120000.json#$.retention[0].midpoint_retention = 0.55",
            "analytics_data_20260717_120000.json#$.retention[0].retention_curve[1].elapsed_ratio = 0.5",
            "analytics_data_20260717_120000.json#$.retention[0].retention_curve[1].watch_ratio = 0.55",
        ),
    )
    _append_retention_section(tmp_path)
    analytics_path = tmp_path / "data/analytics_data_20260717_120000.json"
    analytics = json.loads(analytics_path.read_text(encoding="utf-8"))
    analytics["retention"].append(
        {
            "video_id": "VID_2",
            "average_retention": 0.48,
            "midpoint_retention": 0.39,
            "data_points": 2,
            "retention_curve": [
                {"elapsed_ratio": 0.0, "watch_ratio": 0.8, "relative_performance": 0.0},
                {"elapsed_ratio": 0.5, "watch_ratio": 0.39, "relative_performance": -0.2},
            ],
        }
    )
    analytics_path.write_text(json.dumps(analytics), encoding="utf-8")

    assert _run_validator(tmp_path).returncode != 0


def test_report_without_traffic_trend_output_fails(tmp_path: Path) -> None:
    _write_fixture(tmp_path, depth="standard")
    _append_standard_retention_section(tmp_path)
    report_path = tmp_path / "reports/analysis_20260717.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    del report["commands"]["traffic_trend"]
    del report["cli_outputs"]["traffic_trend"]
    report_path.write_text(json.dumps(report), encoding="utf-8")

    assert _run_validator(tmp_path).returncode != 0


def test_report_without_traffic_trend_evidence_fails(tmp_path: Path) -> None:
    _write_fixture(tmp_path, depth="standard")
    _append_standard_retention_section(tmp_path)
    report_path = tmp_path / "reports/analysis_20260717.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["strategic_improvements"] = [
        item
        for item in report["strategic_improvements"]
        if all(evidence["source"] != "traffic_trend" for evidence in item["evidence"])
    ]
    report_path.write_text(json.dumps(report), encoding="utf-8")

    assert _run_validator(tmp_path).returncode != 0


def test_standard_report_without_full_collection_guidance_fails(tmp_path: Path) -> None:
    _write_fixture(tmp_path, depth="standard")

    assert _run_validator(tmp_path).returncode != 0


def test_standard_report_with_full_collection_guidance_passes(tmp_path: Path) -> None:
    _write_fixture(tmp_path, depth="standard")
    _append_standard_retention_section(tmp_path)

    result = _run_validator(tmp_path)

    assert result.returncode == 0, result.stderr


def test_schema_version_one_fails(tmp_path: Path) -> None:
    _write_fixture(tmp_path, depth="standard")
    _append_standard_retention_section(tmp_path)
    report_path = tmp_path / "reports/analysis_20260717.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["schema_version"] = 1
    report_path.write_text(json.dumps(report), encoding="utf-8")

    assert _run_validator(tmp_path).returncode != 0


def test_missing_ttp_health_fails(tmp_path: Path) -> None:
    _write_fixture(tmp_path, depth="standard")
    _append_standard_retention_section(tmp_path)
    report_path = tmp_path / "reports/analysis_20260717.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    del report["ttp_health"]
    report_path.write_text(json.dumps(report), encoding="utf-8")

    assert _run_validator(tmp_path).returncode != 0


def test_invalid_ttp_channel_status_fails(tmp_path: Path) -> None:
    _write_fixture(tmp_path, depth="standard")
    _append_standard_retention_section(tmp_path)
    report_path = tmp_path / "reports/analysis_20260717.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["ttp_health"]["channels"][0]["status"] = "unknown"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    assert _run_validator(tmp_path).returncode != 0


def test_alert_ttp_channel_requires_nonempty_valid_alerts(tmp_path: Path) -> None:
    _write_fixture(tmp_path, depth="standard")
    _append_standard_retention_section(tmp_path)
    report_path = tmp_path / "reports/analysis_20260717.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["ttp_health"]["channels"][0]["status"] = "alert"
    report["ttp_health"]["channels"][0]["alerts"] = []
    report_path.write_text(json.dumps(report), encoding="utf-8")

    assert _run_validator(tmp_path).returncode != 0
