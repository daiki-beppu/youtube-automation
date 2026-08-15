from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from tests.helpers.paths import REPO_ROOT
from youtube_automation.commands.analytics import ad_coverage
from youtube_automation.core.errors import ConfigError


def _available_revenue(by_video: dict[str, dict[str, int | float]]) -> dict[str, object]:
    return {
        "status": "available",
        "by_video": by_video,
    }


def _video(playbacks: int, ads_per_playback: float) -> dict[str, int | float]:
    return {
        "monetized_playbacks": playbacks,
        "ads_per_playback": ads_per_playback,
    }


def _write_snapshot(root: Path, stamp: str, revenue: dict[str, object]) -> None:
    data_dir = root / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / f"analytics_data_{stamp}.json").write_text(
        json.dumps({"revenue_analytics": revenue}),
        encoding="utf-8",
    )


def test_analyze_warns_for_video_below_default_median_ratio() -> None:
    revenue = _available_revenue(
        {
            "video-normal-a": _video(500, 2.0),
            "video-normal-b": _video(400, 2.2),
            "video-low": _video(300, 0.4),
        }
    )

    result = ad_coverage.analyze_ad_coverage(revenue, threshold=0.5, min_playbacks=100)

    assert result["median_ads_per_playback"] == 2.0
    assert result["warning_count"] == 1
    assert result["warnings"] == [
        {
            "video_id": "video-low",
            "ads_per_playback": 0.4,
            "median_ratio": 0.2,
        }
    ]


def test_analyze_uses_overridden_threshold() -> None:
    revenue = _available_revenue(
        {
            "video-mid": _video(300, 1.2),
            "video-baseline": _video(300, 2.0),
            "video-high": _video(300, 2.8),
        }
    )

    default_result = ad_coverage.analyze_ad_coverage(revenue, threshold=0.5, min_playbacks=100)
    overridden_result = ad_coverage.analyze_ad_coverage(revenue, threshold=0.7, min_playbacks=100)

    assert default_result["warning_count"] == 0
    assert [warning["video_id"] for warning in overridden_result["warnings"]] == ["video-mid"]
    assert overridden_result["warnings"][0]["median_ratio"] == pytest.approx(0.6)


def test_analyze_excludes_low_playbacks_from_median_and_warnings() -> None:
    revenue = _available_revenue(
        {
            "video-low-sample": _video(99, 0.0),
            "video-a": _video(100, 2.0),
            "video-b": _video(200, 4.0),
        }
    )

    result = ad_coverage.analyze_ad_coverage(revenue, threshold=0.5, min_playbacks=100)

    assert result["eligible_video_count"] == 2
    assert result["median_ads_per_playback"] == 3.0
    assert result["warnings"] == []


def test_analyze_preserves_unavailable_reason_without_warnings() -> None:
    revenue = {
        "status": "unavailable",
        "reason": "monetary data forbidden",
        "by_video": {},
    }

    result = ad_coverage.analyze_ad_coverage(revenue, threshold=0.5, min_playbacks=100)

    assert result == {
        "status": "unavailable",
        "reason": "monetary data forbidden",
        "warning_count": 0,
        "warnings": [],
    }


def test_analyze_accepts_partial_revenue_with_video_coverage_data() -> None:
    revenue = {
        "status": "partial",
        "errors": {"day": "daily query forbidden"},
        "by_video": {
            "video-normal": _video(300, 2.0),
            "video-low": _video(300, 0.4),
        },
    }

    result = ad_coverage.analyze_ad_coverage(revenue, threshold=0.5, min_playbacks=100)

    assert result["status"] == "available"
    assert result["warning_count"] == 1
    assert [warning["video_id"] for warning in result["warnings"]] == ["video-low"]


def test_analyze_partial_revenue_keeps_missing_coverage_metrics_fail_closed() -> None:
    revenue = {
        "status": "partial",
        "errors": {"day": "daily query forbidden"},
        "by_video": {
            "video-1": {
                "monetized_playbacks": 600,
                "estimated_revenue": 8.0,
                "cpm": 13.0,
            }
        },
    }

    with pytest.raises(ConfigError, match="ads_per_playback は数値"):
        ad_coverage.analyze_ad_coverage(revenue, threshold=0.5, min_playbacks=100)


@pytest.mark.parametrize("status", [None, "unknown", 1])
def test_analyze_rejects_unknown_or_malformed_revenue_status(status: object) -> None:
    revenue = {"status": status, "by_video": {}}

    with pytest.raises(ConfigError, match="available、partial、unavailable"):
        ad_coverage.analyze_ad_coverage(revenue, threshold=0.5, min_playbacks=100)


@pytest.mark.parametrize("status", [[], {}], ids=["list", "object"])
def test_analyze_rejects_unhashable_revenue_status_as_config_error(status: object) -> None:
    revenue = {"status": status, "by_video": {}}

    with pytest.raises(ConfigError, match="available、partial、unavailable"):
        ad_coverage.analyze_ad_coverage(revenue, threshold=0.5, min_playbacks=100)


def test_cli_reads_latest_snapshot_and_prints_json(tmp_path: Path, monkeypatch, capsys) -> None:
    _write_snapshot(tmp_path, "20260801", _available_revenue({"old": _video(200, 0.1)}))
    _write_snapshot(
        tmp_path,
        "20260802",
        _available_revenue(
            {
                "video-mid": _video(300, 1.2),
                "video-baseline": _video(300, 2.0),
                "video-high": _video(300, 2.8),
            }
        ),
    )
    monkeypatch.setattr(ad_coverage, "_channel_dir", lambda: tmp_path)
    assert ad_coverage.main(["--threshold", "0.7"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["threshold"] == 0.7
    assert [warning["video_id"] for warning in output["warnings"]] == ["video-mid"]
    assert output["warnings"][0]["ads_per_playback"] == 1.2
    assert output["warnings"][0]["median_ratio"] == pytest.approx(0.6)


def test_cli_degrades_empty_partial_video_data_without_breaking_pipeline(tmp_path: Path, monkeypatch, capsys) -> None:
    _write_snapshot(
        tmp_path,
        "20260802",
        {
            "status": "partial",
            "errors": {"video": "video query unsupported"},
            "daily_metrics": [{"date": "2026-08-01", "estimated_revenue": 10.0}],
            "by_video": {},
        },
    )
    monkeypatch.setattr(ad_coverage, "_channel_dir", lambda: tmp_path)
    assert ad_coverage.main([]) == 0

    assert json.loads(capsys.readouterr().out) == {
        "status": "unavailable",
        "reason": "video: video query unsupported",
        "warning_count": 0,
        "warnings": [],
    }


def test_cli_text_reports_zero_warnings(tmp_path: Path, monkeypatch, capsys) -> None:
    _write_snapshot(
        tmp_path,
        "20260802",
        _available_revenue({"video-a": _video(300, 2.0), "video-b": _video(300, 2.0)}),
    )
    monkeypatch.setattr(ad_coverage, "_channel_dir", lambda: tmp_path)
    assert ad_coverage.main(["--text"]) == 0

    assert "警告: 0 件" in capsys.readouterr().out


def test_cli_text_reports_unavailable_reason(tmp_path: Path, monkeypatch, capsys) -> None:
    _write_snapshot(
        tmp_path,
        "20260802",
        {"status": "unavailable", "reason": "monetary data forbidden", "by_video": {}},
    )
    monkeypatch.setattr(ad_coverage, "_channel_dir", lambda: tmp_path)
    assert ad_coverage.main(["--text"]) == 0

    output = capsys.readouterr().out
    assert "収益データを取得できません" in output
    assert "monetary data forbidden" in output
    assert "ミッドロール広告が欠けた疑い" not in output


def test_cli_returns_two_for_invalid_snapshot_shape(tmp_path: Path, monkeypatch, caplog) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "analytics_data_20260802.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(ad_coverage, "_channel_dir", lambda: tmp_path)
    assert ad_coverage.main([]) == 2

    assert "JSON object" in caplog.text


@pytest.mark.parametrize("status", [[], {}], ids=["list", "object"])
def test_cli_returns_two_without_traceback_for_unhashable_revenue_status(
    status: object, tmp_path: Path, monkeypatch, caplog, capsys
) -> None:
    _write_snapshot(tmp_path, "20260802", {"status": status, "by_video": {}})
    monkeypatch.setattr(ad_coverage, "_channel_dir", lambda: tmp_path)
    assert ad_coverage.main([]) == 2

    captured = capsys.readouterr()
    assert "available、partial、unavailable" in caplog.text
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    "arguments",
    [
        ["--threshold", "0"],
        ["--threshold", "1.1"],
        ["--threshold", "nan"],
        ["--min-playbacks", "0"],
        ["--min-playbacks", "1.5"],
    ],
)
def test_cli_rejects_invalid_detection_options(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        ad_coverage.main(arguments)

    assert exited.value.code == 2


def test_analyze_rejects_non_object_video_metrics() -> None:
    revenue = {"status": "available", "by_video": []}

    with pytest.raises(ConfigError, match="by_video は JSON object"):
        ad_coverage.analyze_ad_coverage(revenue, threshold=0.5, min_playbacks=100)


def test_project_script_registers_entrypoint() -> None:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["scripts"]["yt-ad-coverage"] == "youtube_automation.entrypoints:yt_ad_coverage"


def test_load_latest_revenue_raises_when_snapshot_is_missing(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"analytics_data_\*\.json が見つかりません"):
        ad_coverage.load_latest_revenue(tmp_path)
