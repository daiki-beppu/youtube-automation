"""retention drop × scene / BGM 照合のテスト。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.infrastructure.errors import ValidationError
from youtube_automation.scripts import retention_timeline as cli
from youtube_automation.utils.retention_timeline import (
    correlate_retention_timeline,
    detect_retention_drops,
    parse_iso8601_duration,
    parse_timestamp,
)


def test_detects_drop_and_maps_scene_and_track() -> None:
    result = correlate_retention_timeline(
        video_id="VID123",
        duration_seconds=600,
        retention_curve=[
            {"elapsed_ratio": 0.0, "watch_ratio": 1.0, "relative_performance": 1.1},
            {"elapsed_ratio": 0.1, "watch_ratio": 0.96, "relative_performance": 1.0},
            {"elapsed_ratio": 0.25, "watch_ratio": 0.84, "relative_performance": 0.8},
            {"elapsed_ratio": 0.5, "watch_ratio": 0.81, "relative_performance": 0.7},
        ],
        video_analysis={
            "analysis_window_sec": 600,
            "scene_timeline": [
                {"start": "0:00", "summary": "cafe exterior"},
                {"start": "2:00", "summary": "piano close-up"},
            ],
            "bgm_arc": {
                "segments": [
                    {"start": "0:00", "end": "2:29", "track": "Morning Coffee"},
                    {
                        "start": "2:30",
                        "end": "5:00",
                        "track": "Rainy Rhodes",
                        "description": "energy rises",
                    },
                ]
            },
        },
    )

    assert result["drop_count"] == 1
    drop = result["drops"][0]
    assert drop["elapsed_seconds"] == 150
    assert drop["drop_amount"] == pytest.approx(0.12)
    assert drop["scene"] == "piano close-up"
    assert drop["bgm"] == "Rainy Rhodes: energy rises"
    assert drop["mapping_status"] == "matched"


def test_drop_outside_analysis_window_is_not_guessed() -> None:
    result = correlate_retention_timeline(
        video_id="VID123",
        duration_seconds=3600,
        retention_curve=[
            {"elapsed_ratio": 0.2, "watch_ratio": 0.8},
            {"elapsed_ratio": 0.5, "watch_ratio": 0.7},
        ],
        video_analysis={
            "analysis_window_sec": 900,
            "scene_timeline": [{"start": "0:00", "summary": "opening"}],
            "bgm_arc": {"intro": "0:00-0:15", "peak": "1:30"},
        },
    )

    assert result["drops"][0]["elapsed_seconds"] == 1800
    assert result["drops"][0]["scene"] is None
    assert result["drops"][0]["bgm"] is None
    assert result["drops"][0]["mapping_status"] == "outside_analysis_window"


def test_legacy_bgm_arc_maps_to_phase() -> None:
    result = correlate_retention_timeline(
        video_id="VID123",
        duration_seconds=600,
        retention_curve=[
            {"elapsed_ratio": 0.1, "watch_ratio": 0.9},
            {"elapsed_ratio": 0.2, "watch_ratio": 0.8},
        ],
        video_analysis={"bgm_arc": {"intro": "0-15s", "peak": "1:30", "outro": "9:30-end"}},
    )

    assert result["drops"][0]["bgm"] == "peak: 1:30"


def test_parses_seconds_range_from_its_start() -> None:
    assert parse_timestamp("0-15s") == 0
    assert parse_timestamp("12.5-30s") == 12.5


def test_threshold_is_configurable_and_validated() -> None:
    curve = [
        {"elapsed_ratio": 0.0, "watch_ratio": 1.0},
        {"elapsed_ratio": 0.1, "watch_ratio": 0.96},
    ]
    assert detect_retention_drops(curve, threshold=0.05) == []
    assert len(detect_retention_drops(curve, threshold=0.03)) == 1
    with pytest.raises(ValidationError, match="threshold"):
        detect_retention_drops(curve, threshold=0)


@pytest.mark.parametrize(
    ("duration", "expected"),
    [("PT1H23M45S", 5025), ("PT15M", 900), ("PT30.5S", 30.5)],
)
def test_parses_youtube_duration(duration: str, expected: float) -> None:
    assert parse_iso8601_duration(duration) == expected


def test_cli_writes_json_and_markdown_reports(tmp_path: Path, monkeypatch, capsys) -> None:
    _write_analytics(tmp_path)
    analysis_dir = tmp_path / "data" / "video_analysis" / "own"
    analysis_dir.mkdir(parents=True)
    (analysis_dir / "VID123.json").write_text(
        json.dumps(
            {
                "analysis_window_sec": 600,
                "scene_timeline": [{"start": "0:00", "summary": "opening"}],
                "bgm_arc": {"segments": [{"start": "0:00", "track": "track 1"}]},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "channel_dir", lambda: tmp_path)

    assert cli.main(["--video", "VID123"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ok"
    assert output["drop_count"] == 1
    markdown = tmp_path / output["report_markdown"]
    assert markdown.is_file()
    assert "opening" in markdown.read_text(encoding="utf-8")
    assert (tmp_path / output["report_json"]).is_file()


def test_cli_skips_with_video_analyze_guidance(tmp_path: Path, monkeypatch, capsys) -> None:
    _write_analytics(tmp_path)
    monkeypatch.setattr(cli, "channel_dir", lambda: tmp_path)

    assert cli.main(["--video", "VID123"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "skipped"
    assert "/video-analyze 未実行" in output["reason"]
    assert not (tmp_path / "reports").exists()


def test_cli_skips_when_retention_was_not_collected(tmp_path: Path, monkeypatch, capsys) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "analytics_data_20260718.json").write_text(
        json.dumps({"video_analytics": {"VID123": {"duration": "PT10M"}}}), encoding="utf-8"
    )
    monkeypatch.setattr(cli, "channel_dir", lambda: tmp_path)

    assert cli.main(["--video", "VID123"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "skipped"
    assert "yt-analytics --depth full" in output["reason"]


def test_cli_rejects_slug_traversal(tmp_path: Path, monkeypatch, caplog) -> None:
    _write_analytics(tmp_path)
    monkeypatch.setattr(cli, "channel_dir", lambda: tmp_path)

    assert cli.main(["--video", "VID123", "--slug", "../../outside"]) == 2

    assert "--slug が不正" in caplog.text


def _write_analytics(root: Path) -> None:
    data_dir = root / "data"
    data_dir.mkdir()
    (data_dir / "analytics_data_20260718.json").write_text(
        json.dumps(
            {
                "video_analytics": {"VID123": {"duration": "PT10M"}},
                "retention": [
                    {
                        "video_id": "VID123",
                        "retention_curve": [
                            {"elapsed_ratio": 0.0, "watch_ratio": 1.0},
                            {"elapsed_ratio": 0.1, "watch_ratio": 0.9},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
