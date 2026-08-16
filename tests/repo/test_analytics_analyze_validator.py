"""analytics の analysis JSON / Markdown validator 契約テスト。"""

import json
import subprocess
from pathlib import Path

from tests.helpers.paths import REPO_ROOT
from youtube_automation.core.errors import AutomationError
from youtube_automation.domains.documents.schema_registry import RepositorySchema
from youtube_automation.infrastructure.documents.publishing import publish_json_document

ROOT = REPO_ROOT
VALIDATOR = ROOT / ".claude/skills/analytics/references/analysis-json-validator.md"


def _validator_script() -> str:
    text = VALIDATOR.read_text(encoding="utf-8")
    execution = text.split("## 実行", 1)[1]
    return execution.split("```bash\n", 1)[1].split("\n```", 1)[0].replace("analysis_YYYYMMDD", "analysis_20260717")


def test_validator_uses_cwd_independent_canonical_cli_boundary() -> None:
    script = _validator_script()

    assert "yt-document-render" in script
    assert "--check" in script
    assert "uv run python" not in script
    assert "from youtube_automation" not in script


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
    ranking_path = tmp_path / "reports/analysis_20260717.vpd-ranking.json"
    annotations_path = tmp_path / "reports/analysis_20260717.visual-annotations.json"
    win_pattern_path = tmp_path / "reports/analysis_20260717.win-pattern.json"
    for path in (
        analytics_path,
        daily_path,
        content_path,
        report_path,
        markdown_path,
        ranking_path,
        annotations_path,
        win_pattern_path,
    ):
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

    top = {
        "video_id": "VID_TOP",
        "title": "Top",
        "published_at": "2026-06-01T00:00:00Z",
        "cumulative_views": 4200,
        "days_since_publish": 42,
        "duration": "PT1H",
        "vpd": 100.0,
    }
    bottom = {
        "video_id": "VID_BOTTOM",
        "title": "Bottom",
        "published_at": "2026-05-01T00:00:00Z",
        "cumulative_views": 420,
        "days_since_publish": 42,
        "duration": "PT45M",
        "vpd": 10.0,
    }
    vpd_ranking = {
        "n": 2,
        "k": 1,
        "min_age_days": 7,
        "excluded_count": 0,
        "ranking": [top, bottom],
        "groups": {
            "top": {"count": 1, "min_vpd": 100.0, "max_vpd": 100.0, "items": [top]},
            "middle": {"count": 0, "min_vpd": None, "max_vpd": None, "items": []},
            "bottom": {"count": 1, "min_vpd": 10.0, "max_vpd": 10.0, "items": [bottom]},
        },
    }
    visual_annotations = {
        "videos": [
            {
                "video_id": "VID_TOP",
                "composition": "centered",
                "color": None,
                "text_placement": None,
                "visual_flow": None,
                "subject": None,
            },
            {
                "video_id": "VID_BOTTOM",
                "composition": "left",
                "color": None,
                "text_placement": None,
                "visual_flow": None,
                "subject": None,
            },
        ]
    }
    visual_undetermined = {
        name: {
            "top_known_count": 0,
            "bottom_known_count": 0,
            "undetermined_count": {"top": 1, "bottom": 1},
            "values": {},
        }
        for name in ("color", "text_placement", "visual_flow", "subject")
    }
    automatic_known = {
        name: {
            "top_known_count": 1,
            "bottom_known_count": 1,
            "undetermined_count": {"top": 0, "bottom": 0},
            "values": {},
        }
        for name in ("title_pattern", "duration", "publish_weekday", "publish_time")
    }
    win_pattern = {
        "n": 2,
        "k": 1,
        "min_age_days": 7,
        "attributes": {
            "theme": {
                "top_known_count": 1,
                "bottom_known_count": 1,
                "undetermined_count": {"top": 0, "bottom": 0},
                "values": {
                    "focus": {
                        "top_count": 1,
                        "bottom_count": 0,
                        "top_known_count": 1,
                        "bottom_known_count": 1,
                        "top_percentage": 100.0,
                        "bottom_percentage": 0.0,
                        "pp_difference": 100.0,
                        "classification": "win",
                        "undetermined_count": {"top": 0, "bottom": 0},
                        "representative_video_ids": ["VID_TOP"],
                    }
                },
            },
            **automatic_known,
            "composition": {
                "top_known_count": 1,
                "bottom_known_count": 1,
                "undetermined_count": {"top": 0, "bottom": 0},
                "values": {},
            },
            **visual_undetermined,
        },
        "disclaimer": "Observed correlation in this VPD-ranked population; correlation does not imply causation.",
    }
    ranking_path.write_text(json.dumps(vpd_ranking), encoding="utf-8")
    annotations_path.write_text(json.dumps(visual_annotations), encoding="utf-8")
    win_pattern_path.write_text(json.dumps(win_pattern), encoding="utf-8")

    report = {
        "schema_version": 3,
        "generated_at": "2026-07-17T03:00:00Z",
        "summary": "主要指標と戦略示唆のサマリ",
        "inputs": {
            "analysis_target": str(analytics_path.relative_to(tmp_path)),
            "cli_selected": [
                str(analytics_path.relative_to(tmp_path)),
                str(daily_path.relative_to(tmp_path)),
                str(content_path.relative_to(tmp_path)),
            ],
            "supplemental": [],
            "intermediate": {
                "vpd_ranking": str(ranking_path.relative_to(tmp_path)),
                "visual_annotations": str(annotations_path.relative_to(tmp_path)),
                "win_pattern": str(win_pattern_path.relative_to(tmp_path)),
            },
        },
        "commands": {
            "launch_curve": "uv run yt-launch-curve --latest",
            "channel_trend": "uv run yt-channel-trend",
            "theme_compare": "uv run yt-theme-compare",
            "traffic_trend": "uv run yt-traffic-trend",
            "vpd_ranking": "uv run yt-vpd-rank",
            "win_pattern": (
                "uv run yt-win-pattern --ranking reports/analysis_20260717.vpd-ranking.json "
                "--annotations reports/analysis_20260717.visual-annotations.json"
            ),
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
        "vpd_ranking": vpd_ranking,
        "win_pattern": win_pattern,
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
            {
                "statement": "VPD 上位群の規模",
                "evidence": [{"source": "vpd_ranking", "json_path": "$.vpd_ranking.n", "value": 2}],
                "confidence": "high",
            },
            {
                "statement": "勝ち型の上位割合",
                "evidence": [
                    {
                        "source": "win_pattern",
                        "json_path": "$.win_pattern.attributes.theme.values.focus.top_percentage",
                        "value": 100.0,
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
        "revenue_analysis": {
            "status": "not_collected",
            "themes": [],
            "collections": [],
        },
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
        "analysis_20260717.json#$.vpd_ranking.n = 2",
        "analysis_20260717.json#$.win_pattern.attributes.theme.values.focus.top_percentage = 100.0",
    ]
    citations.extend(extra_citations)
    vpd_section = (
        "## VPD 上位 / 下位の定量比較",
        "相関注記: Observed correlation in this VPD-ranked population; correlation does not imply causation.",
        "判定不能: visual attributes",
    )
    undetermined_citations = [
        f"analysis_20260717.json#$.win_pattern.attributes.{attribute}.undetermined_count.{group} = 1"
        for attribute in ("color", "text_placement", "visual_flow", "subject")
        for group in ("top", "bottom")
    ]
    markdown_path.write_text(
        "\n".join([*citations, *vpd_section, *undetermined_citations]) + "\n\n## 収益・RPM 分析\n",
        encoding="utf-8",
    )


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
    report = tmp_path / "reports/analysis_20260717.json"
    report.with_suffix(".html").unlink(missing_ok=True)
    try:
        publish_json_document(report, RepositorySchema.ANALYSIS_REPORT)
    except AutomationError:
        pass
    return subprocess.run(
        ["bash", "-c", _validator_script()],
        cwd=tmp_path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _set_available_revenue(tmp_path: Path, *, rpm: float) -> None:
    analytics_path = tmp_path / "data/analytics_data_20260717_120000.json"
    analytics = json.loads(analytics_path.read_text(encoding="utf-8"))
    analytics["revenue_analytics"] = {"status": "available", "currency": "USD"}
    analytics_path.write_text(json.dumps(analytics), encoding="utf-8")

    report_path = tmp_path / "reports/analysis_20260717.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["revenue_analysis"] = {
        "status": "available",
        "currency": "USD",
        "themes": [
            {
                "name": "Fantasy",
                "estimated_revenue": 31.0,
                "views": 5000,
                "rpm": rpm,
                "video_count": 2,
            }
        ],
        "collections": [],
    }
    report_path.write_text(json.dumps(report), encoding="utf-8")


def test_available_revenue_with_weighted_rpm_passes(tmp_path: Path) -> None:
    _write_fixture(tmp_path, depth="standard")
    _append_standard_retention_section(tmp_path)
    _set_available_revenue(tmp_path, rpm=6.2)

    result = _run_validator(tmp_path)

    assert result.returncode == 0, result.stderr


def test_stale_html_is_not_a_successful_analysis_pair(tmp_path: Path) -> None:
    _write_fixture(tmp_path, depth="standard")
    _append_standard_retention_section(tmp_path)
    assert _run_validator(tmp_path).returncode == 0
    (tmp_path / "reports/analysis_20260717.html").write_text("stale", encoding="utf-8")

    result = subprocess.run(
        ["bash", "-c", _validator_script()],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0


def test_available_revenue_rejects_unweighted_rpm(tmp_path: Path) -> None:
    _write_fixture(tmp_path, depth="standard")
    _append_standard_retention_section(tmp_path)
    _set_available_revenue(tmp_path, rpm=7.5)

    assert _run_validator(tmp_path).returncode != 0


def test_full_report_does_not_require_legacy_markdown_retention_citation(tmp_path: Path) -> None:
    _write_fixture(tmp_path, depth="full")

    assert _run_validator(tmp_path).returncode == 0


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


def test_full_report_does_not_read_legacy_markdown_retention_section(tmp_path: Path) -> None:
    _write_fixture(
        tmp_path,
        depth="full",
        extra_citations=("analytics_data_20260717_120000.json#$.retention[0].average_retention = 0.62",),
    )

    assert _run_validator(tmp_path).returncode == 0


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


def test_standard_report_does_not_require_legacy_markdown_guidance(tmp_path: Path) -> None:
    _write_fixture(tmp_path, depth="standard")

    assert _run_validator(tmp_path).returncode == 0


def test_standard_report_with_full_collection_guidance_passes(tmp_path: Path) -> None:
    _write_fixture(tmp_path, depth="standard")
    _append_standard_retention_section(tmp_path)

    result = _run_validator(tmp_path)

    assert result.returncode == 0, result.stderr


def test_fresh_schema_version_two_fails(tmp_path: Path) -> None:
    _write_fixture(tmp_path, depth="standard")
    _append_standard_retention_section(tmp_path)
    report_path = tmp_path / "reports/analysis_20260717.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["schema_version"] = 2
    report_path.write_text(json.dumps(report), encoding="utf-8")

    assert _run_validator(tmp_path).returncode != 0


def test_vpd_partition_overlap_fails(tmp_path: Path) -> None:
    _write_fixture(tmp_path, depth="standard")
    _append_standard_retention_section(tmp_path)
    report_path = tmp_path / "reports/analysis_20260717.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["vpd_ranking"]["groups"]["bottom"]["items"] = report["vpd_ranking"]["groups"]["top"]["items"]
    ranking_path = tmp_path / report["inputs"]["intermediate"]["vpd_ranking"]
    ranking_path.write_text(json.dumps(report["vpd_ranking"]), encoding="utf-8")
    report_path.write_text(json.dumps(report), encoding="utf-8")

    assert _run_validator(tmp_path).returncode != 0


def test_vpd_duplicate_ranking_id_fails(tmp_path: Path) -> None:
    _write_fixture(tmp_path, depth="standard")
    _append_standard_retention_section(tmp_path)
    report_path = tmp_path / "reports/analysis_20260717.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["vpd_ranking"]["ranking"][1]["video_id"] = "VID_TOP"
    ranking_path = tmp_path / report["inputs"]["intermediate"]["vpd_ranking"]
    ranking_path.write_text(json.dumps(report["vpd_ranking"]), encoding="utf-8")
    report_path.write_text(json.dumps(report), encoding="utf-8")

    assert _run_validator(tmp_path).returncode != 0


def test_win_pattern_population_mismatch_fails(tmp_path: Path) -> None:
    _write_fixture(tmp_path, depth="standard")
    _append_standard_retention_section(tmp_path)
    report_path = tmp_path / "reports/analysis_20260717.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["win_pattern"]["n"] = 3
    win_path = tmp_path / report["inputs"]["intermediate"]["win_pattern"]
    win_path.write_text(json.dumps(report["win_pattern"]), encoding="utf-8")
    report_path.write_text(json.dumps(report), encoding="utf-8")

    assert _run_validator(tmp_path).returncode != 0


def test_missing_automatic_attribute_fails(tmp_path: Path) -> None:
    _write_fixture(tmp_path, depth="standard")
    _append_standard_retention_section(tmp_path)
    report_path = tmp_path / "reports/analysis_20260717.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    del report["win_pattern"]["attributes"]["publish_time"]
    win_path = tmp_path / report["inputs"]["intermediate"]["win_pattern"]
    win_path.write_text(json.dumps(report["win_pattern"]), encoding="utf-8")
    report_path.write_text(json.dumps(report), encoding="utf-8")

    assert _run_validator(tmp_path).returncode != 0


def test_all_duration_undetermined_fails(tmp_path: Path) -> None:
    _write_fixture(tmp_path, depth="standard")
    _append_standard_retention_section(tmp_path)
    report_path = tmp_path / "reports/analysis_20260717.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    duration = report["win_pattern"]["attributes"]["duration"]
    duration["top_known_count"] = 0
    duration["bottom_known_count"] = 0
    duration["undetermined_count"] = {"top": 1, "bottom": 1}
    for item in report["vpd_ranking"]["ranking"]:
        item["duration"] = None
    for group in ("top", "bottom"):
        report["vpd_ranking"]["groups"][group]["items"][0]["duration"] = None
    ranking_path = tmp_path / report["inputs"]["intermediate"]["vpd_ranking"]
    ranking_path.write_text(json.dumps(report["vpd_ranking"]), encoding="utf-8")
    win_path = tmp_path / report["inputs"]["intermediate"]["win_pattern"]
    win_path.write_text(json.dumps(report["win_pattern"]), encoding="utf-8")
    report_path.write_text(json.dumps(report), encoding="utf-8")

    assert _run_validator(tmp_path).returncode != 0


def test_attribute_known_and_undetermined_population_mismatch_fails(tmp_path: Path) -> None:
    _write_fixture(tmp_path, depth="standard")
    _append_standard_retention_section(tmp_path)
    report_path = tmp_path / "reports/analysis_20260717.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["win_pattern"]["attributes"]["color"]["undetermined_count"]["top"] = 0
    win_path = tmp_path / report["inputs"]["intermediate"]["win_pattern"]
    win_path.write_text(json.dumps(report["win_pattern"]), encoding="utf-8")
    report_path.write_text(json.dumps(report), encoding="utf-8")

    assert _run_validator(tmp_path).returncode != 0


def test_modified_captured_stdout_fails(tmp_path: Path) -> None:
    _write_fixture(tmp_path, depth="standard")
    _append_standard_retention_section(tmp_path)
    ranking_path = tmp_path / "reports/analysis_20260717.vpd-ranking.json"
    ranking = json.loads(ranking_path.read_text(encoding="utf-8"))
    ranking["excluded_count"] = 99
    ranking_path.write_text(json.dumps(ranking), encoding="utf-8")

    assert _run_validator(tmp_path).returncode != 0


def test_missing_vpd_numeric_evidence_fails(tmp_path: Path) -> None:
    _write_fixture(tmp_path, depth="standard")
    _append_standard_retention_section(tmp_path)
    report_path = tmp_path / "reports/analysis_20260717.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["strategic_improvements"] = [
        item
        for item in report["strategic_improvements"]
        if all(evidence["source"] != "vpd_ranking" for evidence in item["evidence"])
    ]
    report_path.write_text(json.dumps(report), encoding="utf-8")

    assert _run_validator(tmp_path).returncode != 0


def test_legacy_markdown_vpd_phrase_is_not_a_consumer_input(tmp_path: Path) -> None:
    _write_fixture(tmp_path, depth="standard")
    _append_standard_retention_section(tmp_path)
    markdown_path = tmp_path / "reports/analysis_20260717.md"
    markdown = markdown_path.read_text(encoding="utf-8")
    markdown_path.write_text(
        markdown.replace("analysis_20260717.json#$.vpd_ranking.n = 2", "VPD n は 2"), encoding="utf-8"
    )

    assert _run_validator(tmp_path).returncode == 0


def test_legacy_markdown_undetermined_label_is_not_a_consumer_input(tmp_path: Path) -> None:
    _write_fixture(tmp_path, depth="standard")
    _append_standard_retention_section(tmp_path)
    markdown_path = tmp_path / "reports/analysis_20260717.md"
    markdown = markdown_path.read_text(encoding="utf-8")
    markdown = markdown.replace("判定不能: visual attributes\n", "")
    markdown = markdown.replace(
        "analysis_20260717.json#$.win_pattern.attributes.color.undetermined_count.top = 1\n", ""
    )
    markdown_path.write_text(markdown, encoding="utf-8")

    assert _run_validator(tmp_path).returncode == 0


def test_legacy_markdown_heading_is_not_a_consumer_input(tmp_path: Path) -> None:
    _write_fixture(tmp_path, depth="standard")
    _append_standard_retention_section(tmp_path)
    markdown_path = tmp_path / "reports/analysis_20260717.md"
    markdown = markdown_path.read_text(encoding="utf-8")
    markdown = markdown.replace("## VPD 上位 / 下位の定量比較\n", "")
    markdown = markdown.replace("相関注記: Observed correlation", "note: Observed correlation")
    markdown_path.write_text(markdown, encoding="utf-8")

    assert _run_validator(tmp_path).returncode == 0


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
