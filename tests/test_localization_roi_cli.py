"""yt-localization-roi CLI のユニットテスト."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from youtube_automation.scripts import localization_roi

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "localization_roi" / "sample_country_analytics.json"


@pytest.fixture
def fixture_countries() -> dict:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _patch_collector(monkeypatch, fixture: dict) -> None:
    """YouTubeAnalyticsCollector を MagicMock で差し替える."""
    instance = MagicMock()
    instance.initialize.return_value = None
    instance.get_country_analytics.return_value = fixture

    factory = MagicMock(return_value=instance)
    monkeypatch.setattr(localization_roi, "YouTubeAnalyticsCollector", factory)


def test_build_analysis_structure(fixture_countries):
    analysis = localization_roi.build_analysis(
        fixture_countries["countries"],
        current_supported=["ja", "ko", "es", "pt", "zh-CN"],
        days=90,
        keep_floor=0.5,
        add_floor=1.0,
    )
    assert {"countries", "languages", "recommended", "thresholds"}.issubset(analysis)
    langs = {row["language"] for row in analysis["languages"]}
    assert "en" in langs and "ja" in langs and "de" in langs
    # 未登録国は other バケットに集約される
    assert "other" in langs


def test_recommended_add_includes_en_de(fixture_countries):
    analysis = localization_roi.build_analysis(
        fixture_countries["countries"],
        current_supported=["ja", "ko", "es", "pt", "zh-CN"],
        days=90,
        keep_floor=0.5,
        add_floor=1.0,
    )
    rec = analysis["recommended"]
    assert "en" in rec["add"]
    assert "de" in rec["add"]


def test_render_markdown_contains_required_sections(fixture_countries):
    analysis = localization_roi.build_analysis(
        fixture_countries["countries"],
        current_supported=["ja", "ko"],
        days=90,
        keep_floor=0.5,
        add_floor=1.0,
    )
    md = localization_roi.render_markdown(analysis)
    assert "# Localization ROI Report" in md
    assert "## 国別 views" in md
    assert "## 言語別集計" in md
    assert "## 推奨 supported_languages" in md


def test_main_writes_markdown_and_json(monkeypatch, tmp_path, fixture_countries, capsys):
    _patch_collector(monkeypatch, fixture_countries)

    output = tmp_path / "report.md"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "yt-localization-roi",
            "--days",
            "90",
            "--output",
            str(output),
        ],
    )

    code = localization_roi.main()

    assert code == 0
    assert output.exists()
    md = output.read_text(encoding="utf-8")
    assert "Localization ROI Report" in md

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["window_days"] == 90
    assert payload["output_path"] == str(output)
    # 新 example の supported_languages は [en, de, no, ja]。en は既に含まれるので keep 側
    assert "en" in payload["recommended"]["keep"]
    assert payload["recommended"]["mandatory_languages"] == ["de", "en", "no"]


def test_main_text_mode_emits_summary(monkeypatch, tmp_path, fixture_countries, capsys):
    _patch_collector(monkeypatch, fixture_countries)

    output = tmp_path / "report.md"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "yt-localization-roi",
            "--text",
            "--output",
            str(output),
        ],
    )

    code = localization_roi.main()

    assert code == 0
    captured = capsys.readouterr()
    assert "📄" in captured.out
    assert "Add:" in captured.out


def test_main_returns_1_when_country_analytics_empty(monkeypatch, tmp_path, capsys):
    _patch_collector(monkeypatch, {"countries": {}, "total_views": 0})

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "yt-localization-roi",
            "--output",
            str(tmp_path / "r.md"),
        ],
    )

    code = localization_roi.main()
    assert code == 1


def test_main_returns_1_when_api_error(monkeypatch, tmp_path):
    _patch_collector(
        monkeypatch,
        {"countries": {}, "total_views": 0, "error": "quota exceeded"},
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "yt-localization-roi",
            "--output",
            str(tmp_path / "r.md"),
        ],
    )

    code = localization_roi.main()
    assert code == 1
