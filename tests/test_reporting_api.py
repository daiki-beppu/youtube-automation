"""ReportingAPIClient のユニットテスト。

MagicMock で discovery service を差し替え、AuthorizedSession の HTTP は
monkeypatch で吸収する。`tests/test_ctr_analytics.py` の流儀に準拠。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from youtube_automation.utils.exceptions import ConfigError, ValidationError, YouTubeAPIError
from youtube_automation.utils.reporting_api import ReportingAPIClient

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "reporting_api"
_FIXTURE = _FIXTURE_DIR / "channel_reach_basic_a1_sample.csv"
_FIXTURE_COMBINED = _FIXTURE_DIR / "channel_reach_combined_a1_sample.csv"


def _make_service(report_types: list[dict] | None = None, jobs: list[dict] | None = None):
    """reportTypes.list() / jobs.list() / jobs.create() を返す MagicMock を作る。"""
    service = MagicMock()
    service.reportTypes.return_value.list.return_value.execute.return_value = {"reportTypes": report_types or []}
    service.jobs.return_value.list.return_value.execute.return_value = {"jobs": jobs or []}
    return service


# ---------------------------------------------------------------------------
# select_report_type
# ---------------------------------------------------------------------------
def test_select_report_type_prefers_reach_basic_over_combined():
    service = _make_service(
        report_types=[
            {"id": "channel_reach_combined_a1", "name": "Reach combined"},
            {"id": "channel_reach_basic_a1", "name": "Reach basic"},
            {"id": "channel_basic_a3", "name": "User activity"},
        ]
    )
    client = ReportingAPIClient(service)
    assert client.select_report_type() == "channel_reach_basic_a1"


def test_select_report_type_falls_back_to_reach_combined():
    service = _make_service(
        report_types=[
            {"id": "channel_reach_combined_a1", "name": "Reach combined"},
            {"id": "channel_basic_a3", "name": "User activity"},
        ]
    )
    client = ReportingAPIClient(service)
    assert client.select_report_type() == "channel_reach_combined_a1"


def test_select_report_type_raises_when_no_match():
    service = _make_service(
        report_types=[
            {"id": "channel_basic_a3", "name": "User activity"},
            {"id": "channel_demographics_a1", "name": "Demographics"},
            {"id": "channel_traffic_source_a3", "name": "Traffic"},
        ]
    )
    client = ReportingAPIClient(service)
    with pytest.raises(ConfigError):
        client.select_report_type()


# ---------------------------------------------------------------------------
# ensure_job
# ---------------------------------------------------------------------------
def test_ensure_job_reuses_existing():
    service = _make_service(
        jobs=[
            {"id": "job-existing", "reportTypeId": "channel_reach_basic_a1", "name": "yt-automation"},
            {"id": "job-other", "reportTypeId": "channel_demographics_a1", "name": "other"},
        ]
    )
    client = ReportingAPIClient(service)

    job_id = client.ensure_job("channel_reach_basic_a1")

    assert job_id == "job-existing"
    service.jobs.return_value.create.assert_not_called()


def test_ensure_job_creates_when_missing():
    service = _make_service(jobs=[])
    service.jobs.return_value.create.return_value.execute.return_value = {"id": "job-new"}
    client = ReportingAPIClient(service)

    job_id = client.ensure_job("channel_reach_basic_a1")

    assert job_id == "job-new"
    service.jobs.return_value.create.assert_called_once_with(
        body={"reportTypeId": "channel_reach_basic_a1", "name": "yt-automation"}
    )


# ---------------------------------------------------------------------------
# parse_csv
# ---------------------------------------------------------------------------
def test_parse_csv_extracts_per_video_and_per_day():
    csv_text = _FIXTURE.read_text(encoding="utf-8")
    client = ReportingAPIClient(MagicMock())

    rows = client.parse_csv(csv_text)

    assert len(rows) == 5
    first = rows[0]
    assert first["date"] == "2026-04-20"
    assert first["video_id"] == "vid001"
    assert first["impressions"] == 2000
    # Reporting API の CTR は 0-1 の比率 → 100 倍されて % に正規化される
    assert first["ctr_percentage"] == pytest.approx(5.0)


def test_parse_csv_raises_when_columns_missing():
    csv_text = "date,channel_id,video_id,views\n2026-04-20,UCabc,vid001,100\n"
    client = ReportingAPIClient(MagicMock())

    with pytest.raises(ValidationError):
        client.parse_csv(csv_text)


def test_parse_csv_handles_empty_csv():
    client = ReportingAPIClient(MagicMock())
    assert client.parse_csv("") == []


# ---------------------------------------------------------------------------
# download_report_csv
# ---------------------------------------------------------------------------
def test_download_report_csv_requires_credentials():
    client = ReportingAPIClient(MagicMock(), credentials=None)
    with pytest.raises(YouTubeAPIError):
        client.download_report_csv("https://example.com/x.csv")


def test_download_report_csv_returns_text(monkeypatch):
    fake_response = MagicMock(status_code=200, content=b"date,video_thumbnail_impressions\n2026-04-20,1000\n")
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response

    def _fake_authed_session(*_args, **_kwargs):
        return fake_session

    monkeypatch.setattr(
        "youtube_automation.utils.reporting_api.AuthorizedSession",
        _fake_authed_session,
    )

    client = ReportingAPIClient(MagicMock(), credentials=MagicMock())
    text = client.download_report_csv("https://example.com/x.csv")

    assert "video_thumbnail_impressions" in text
    fake_session.get.assert_called_once_with("https://example.com/x.csv", timeout=(5, 60))


def test_download_report_csv_raises_on_http_error(monkeypatch):
    fake_response = MagicMock(status_code=403, content=b"forbidden", text="forbidden")
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response

    monkeypatch.setattr(
        "youtube_automation.utils.reporting_api.AuthorizedSession",
        lambda *_a, **_k: fake_session,
    )

    client = ReportingAPIClient(MagicMock(), credentials=MagicMock())
    with pytest.raises(YouTubeAPIError):
        client.download_report_csv("https://example.com/x.csv")


# ---------------------------------------------------------------------------
# collect_impressions_summary
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "fixture_path, report_type, expected_total_imp, expected_total_weighted, expected_video_ids, expected_dates",
    [
        # Reach basic: 1 (video, date) ごとに 1 行
        # weighted CTR: (2000×5 + 5000×8 + 2200×6 + 5500×10 + 1500×4) / 16200 = 124200/16200
        (
            _FIXTURE,
            "channel_reach_basic_a1",
            16200,
            124200.0,
            {"vid001", "vid002", "vid003"},
            {"2026-04-20", "2026-04-21", "2026-04-22"},
        ),
        # Reach combined: 1 (video, date) に traffic_source / country / subscribed_status の組合せで複数行
        # weighted CTR: (1000×5 + 1500×6 + 500×10 + 2000×7 + 800×4) / 5800 = 36200/5800
        (
            _FIXTURE_COMBINED,
            "channel_reach_combined_a1",
            5800,
            36200.0,
            {"vid001", "vid002"},
            {"2026-04-20", "2026-04-21"},
        ),
    ],
    ids=["reach_basic", "reach_combined"],
)
def test_collect_impressions_summary_aggregates(
    monkeypatch,
    fixture_path,
    report_type,
    expected_total_imp,
    expected_total_weighted,
    expected_video_ids,
    expected_dates,
):
    csv_text = fixture_path.read_text(encoding="utf-8")

    service = _make_service(
        report_types=[{"id": report_type, "name": report_type}],
        jobs=[{"id": "job-1", "reportTypeId": report_type, "name": "yt-automation"}],
    )
    service.jobs.return_value.reports.return_value.list.return_value.execute.return_value = {
        "reports": [{"id": "r1", "downloadUrl": "https://example.com/r1.csv"}]
    }

    fake_response = MagicMock(status_code=200, content=csv_text.encode("utf-8"))
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response
    monkeypatch.setattr(
        "youtube_automation.utils.reporting_api.AuthorizedSession",
        lambda *_a, **_k: fake_session,
    )

    client = ReportingAPIClient(service, credentials=MagicMock())
    summary = client.collect_impressions_summary(days=7)

    assert summary["selected_report_type"] == report_type
    assert summary["report_count"] == 1
    assert summary["aggregated_impressions"] == expected_total_imp
    assert summary["aggregated_ctr_percentage"] == pytest.approx(expected_total_weighted / expected_total_imp)
    assert {row["video_id"] for row in summary["per_video"]} == expected_video_ids
    assert {row["date"] for row in summary["per_day"]} == expected_dates


def test_collect_impressions_summary_combined_uses_weighted_ctr(monkeypatch):
    """Reach combined で 1 video × 1 date に複数 segment がある場合、CTR が impression
    加重平均になっていることを per_video / per_day の数値で確認する。

    単純平均だと segment 数で割ってしまい、impression が大きい segment が過小評価される。
    """
    csv_text = _FIXTURE_COMBINED.read_text(encoding="utf-8")

    service = _make_service(
        report_types=[{"id": "channel_reach_combined_a1", "name": "Reach combined"}],
        jobs=[{"id": "job-1", "reportTypeId": "channel_reach_combined_a1", "name": "yt-automation"}],
    )
    service.jobs.return_value.reports.return_value.list.return_value.execute.return_value = {
        "reports": [{"id": "r1", "downloadUrl": "https://example.com/r1.csv"}]
    }

    fake_response = MagicMock(status_code=200, content=csv_text.encode("utf-8"))
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response
    monkeypatch.setattr(
        "youtube_automation.utils.reporting_api.AuthorizedSession",
        lambda *_a, **_k: fake_session,
    )

    client = ReportingAPIClient(service, credentials=MagicMock())
    summary = client.collect_impressions_summary(days=7)

    # vid001: 4 segments を加重平均
    # impressions = 1000+1500+500+2000 = 5000
    # weighted CTR = (1000×5 + 1500×6 + 500×10 + 2000×7) / 5000 = 33000/5000 = 6.6%
    vid001 = next(row for row in summary["per_video"] if row["video_id"] == "vid001")
    assert vid001["impressions"] == 5000
    assert vid001["ctr_percentage"] == pytest.approx(6.6)

    # 2026-04-20: vid001 の 3 segments のみ
    # impressions = 3000, weighted CTR = (5000+9000+5000)/3000 = 19000/3000 ≈ 6.333%
    day0 = next(row for row in summary["per_day"] if row["date"] == "2026-04-20")
    assert day0["impressions"] == 3000
    assert day0["ctr_percentage"] == pytest.approx(19000 / 3000)


def test_collect_impressions_summary_returns_empty_when_no_reports():
    service = _make_service(
        report_types=[{"id": "channel_reach_basic_a1", "name": "Reach basic"}],
        jobs=[{"id": "job-1", "reportTypeId": "channel_reach_basic_a1", "name": "yt-automation"}],
    )
    service.jobs.return_value.reports.return_value.list.return_value.execute.return_value = {"reports": []}

    client = ReportingAPIClient(service, credentials=MagicMock())
    summary = client.collect_impressions_summary(days=7)

    assert summary["report_count"] == 0
    assert summary["aggregated_impressions"] is None
    assert summary["aggregated_ctr_percentage"] is None
    assert summary["per_video"] == []
    assert summary["per_day"] == []


# ---------------------------------------------------------------------------
# ReportingAPIMixin (fail-open)
# ---------------------------------------------------------------------------
def test_mixin_fail_open_returns_none_on_exception(monkeypatch):
    from youtube_automation.utils import reporting_analytics
    from youtube_automation.utils.exceptions import YouTubeAPIError

    class _BoomClient:
        def __init__(self, *_a, **_k):
            pass

        def collect_impressions_summary(self, days: int = 7):  # noqa: ARG002
            raise YouTubeAPIError("boom")

    monkeypatch.setattr(reporting_analytics, "ReportingAPIClient", _BoomClient)
    monkeypatch.setattr(reporting_analytics, "get_reporting", lambda: MagicMock())
    monkeypatch.setattr(reporting_analytics, "get_credentials", lambda: MagicMock())

    class _C(reporting_analytics.ReportingAPIMixin):
        pass

    assert _C().get_reporting_impressions_summary(days=7) is None


def test_mixin_returns_summary_on_success(monkeypatch):
    from youtube_automation.utils import reporting_analytics

    class _OkClient:
        def __init__(self, *_a, **_k):
            pass

        def collect_impressions_summary(self, days: int = 7):  # noqa: ARG002
            return {"aggregated_ctr_percentage": 4.2}

    monkeypatch.setattr(reporting_analytics, "ReportingAPIClient", _OkClient)
    monkeypatch.setattr(reporting_analytics, "get_reporting", lambda: MagicMock())
    monkeypatch.setattr(reporting_analytics, "get_credentials", lambda: MagicMock())

    class _C(reporting_analytics.ReportingAPIMixin):
        pass

    summary = _C().get_reporting_impressions_summary(days=7)
    assert summary == {"aggregated_ctr_percentage": 4.2}
