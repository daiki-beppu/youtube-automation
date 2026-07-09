"""YouTube Reporting API v1 クライアント。

YouTube Analytics API では `videoThumbnailImpressions` /
`videoThumbnailImpressionsClickThroughRate` が dimensions=video / day / 等
全パターンで 400 拒否されるため、Reporting API v1 (非同期 CSV bulk download) で
取得する基盤を提供する。

レポートタイプは **Reach 系**（`channel_reach_basic_a1` /
`channel_reach_combined_a1`）を使用する。これらの metrics に
`video_thumbnail_impressions` / `video_thumbnail_impressions_ctr` が含まれる
（公式: https://developers.google.com/youtube/reporting/v1/reports/channel_reports#reach-reports）。
`channel_basic_*` には thumbnail impressions / CTR は含まれていない（views や
card_impressions / annotation_impressions のみ）ため使用しない。

仕様上の制約:
- ジョブ作成後 **最大 48 時間**以内に最初のレポートが取得可能になる
- 初回取得時はジョブ作成日からさかのぼって **過去 30 日分**が backfill される
- 以降は日次で **D+2**（その日のデータは翌々日）にレポートが生成される
- API データ保持上限は現在から過去 **60 日**（それ以前のデータは取れない）
- CSV ダウンロードは AuthorizedSession 経由で downloadUrl を直叩き

Usage:
    from youtube_automation.utils.reporting_api import ReportingAPIClient
    from youtube_automation.utils.youtube_service import _default_registry

    client = ReportingAPIClient(_default_registry.reporting, _default_registry.credentials)
    summary = client.collect_impressions_summary(days=7)
"""

from __future__ import annotations

import csv
import io
import logging
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import requests.exceptions
from google.auth.transport.requests import AuthorizedSession
from googleapiclient.errors import HttpError

from youtube_automation.utils.exceptions import ConfigError, ValidationError, YouTubeAPIError

# CSV ダウンロードのタイムアウト（接続, 読み取り）秒
_DOWNLOAD_TIMEOUT = (5, 60)

logger = logging.getLogger(__name__)


# CSV 列名候補（reportType の version で揺れる可能性に備え複数を許容）
_IMPRESSIONS_COLUMNS = ("video_thumbnail_impressions",)
_CTR_COLUMNS = (
    "video_thumbnail_impressions_ctr",  # Reach レポート公式カラム名
    "video_thumbnail_impressions_click_through_rate",  # 将来の version suffix 揺れ向け
)
_VIDEO_ID_COLUMNS = ("video_id",)
_DATE_COLUMNS = ("date", "day")

# reportType ID 候補。`video_thumbnail_impressions` / `video_thumbnail_impressions_ctr`
# を metrics として持つのは Reach 系のみ（channel_basic_* は views と card/annotation
# 系の impressions しか含まない）。
# basic レポートより詳細な dimensions（traffic_source 等）を持つ combined を後段に置く。
_REPORT_TYPE_PRIORITIES = (
    "channel_reach_basic_a1",
    "channel_reach_combined_a1",
)


class ReportingAPIClient:
    """YouTube Reporting API v1 クライアント。

    ジョブ管理 → レポート列挙 → CSV ダウンロード → パース → 集計までを 1 クラスで提供。
    """

    JOB_NAME = "yt-automation"

    def __init__(self, reporting_service: Any, credentials: Any = None):
        """
        Args:
            reporting_service: googleapiclient.discovery.Resource (youtubereporting v1)
            credentials: google.oauth2.credentials.Credentials (CSV ダウンロード用)
        """
        self._service = reporting_service
        self._credentials = credentials

    # ------------------------------------------------------------------
    # reportType 選定
    # ------------------------------------------------------------------
    def select_report_type(self) -> str:
        """`video_thumbnail_impressions` を含む Reach レポートの ID を返す。

        `reportTypes.list()` で利用可能なレポートタイプ ID を列挙し、
        `_REPORT_TYPE_PRIORITIES` のうち最初に見つかったものを返す。

        Raises:
            ConfigError: 該当レポートタイプが見つからない
            YouTubeAPIError: API 呼び出し失敗
        """
        try:
            response = self._service.reportTypes().list().execute()
        except HttpError as e:
            raise YouTubeAPIError.from_http_error(e, "reporting:reportTypes.list") from e

        available = {rt["id"] for rt in response.get("reportTypes", []) if "id" in rt}
        for candidate in _REPORT_TYPE_PRIORITIES:
            if candidate in available:
                logger.info(f"Reporting API: reportType={candidate} を選択")
                return candidate

        raise ConfigError(
            "Reporting API: video_thumbnail_impressions を含む Reach reportType が見つかりません。"
            f" 利用可能: {sorted(available)}"
        )

    def dry_run_inspection(self) -> dict[str, Any]:
        """副作用なしで Reporting API の現状を観察する（実行系ジョブ作成・CSV DL は行わない）。

        Returns:
            "report_types_count" / "jobs_count" / "available_priority_matches" /
            "selected_report_type" / "existing_job" / "recent_reports_count" を含む dict
        """
        try:
            rt_response = self._service.reportTypes().list().execute()
        except HttpError as e:
            raise YouTubeAPIError.from_http_error(e, "reporting:reportTypes.list") from e

        try:
            job_response = self._service.jobs().list().execute()
        except HttpError as e:
            raise YouTubeAPIError.from_http_error(e, "reporting:jobs.list") from e

        report_types = rt_response.get("reportTypes", [])
        available_ids = {rt["id"] for rt in report_types if "id" in rt}
        priority_matches = [c for c in _REPORT_TYPE_PRIORITIES if c in available_ids]
        selected = priority_matches[0] if priority_matches else None

        jobs = job_response.get("jobs", [])
        existing_job = None
        if selected is not None:
            for job in jobs:
                if job.get("reportTypeId") == selected and job.get("name") == self.JOB_NAME:
                    existing_job = job
                    break

        recent_reports_count: int | None = None
        if existing_job is not None:
            try:
                reports = self.list_recent_reports(existing_job["id"], since_days=60)
                recent_reports_count = len(reports)
            except YouTubeAPIError as e:
                logger.warning(f"dry-run: list_recent_reports 失敗（続行）: {e}")

        return {
            "report_types_count": len(report_types),
            "available_priority_matches": priority_matches,
            "selected_report_type": selected,
            "jobs_count": len(jobs),
            "existing_job": existing_job,
            "recent_reports_count": recent_reports_count,
        }

    # ------------------------------------------------------------------
    # ジョブ管理（冪等化）
    # ------------------------------------------------------------------
    def ensure_job(self, report_type_id: str) -> str:
        """`reportTypeId + name` 一致のジョブを再利用、無ければ create。

        Args:
            report_type_id: 利用するレポートタイプ ID

        Returns:
            ジョブ ID

        Raises:
            YouTubeAPIError: API 呼び出し失敗
        """
        try:
            existing = self._service.jobs().list().execute()
        except HttpError as e:
            raise YouTubeAPIError.from_http_error(e, "reporting:jobs.list") from e

        for job in existing.get("jobs", []):
            if job.get("reportTypeId") == report_type_id and job.get("name") == self.JOB_NAME:
                logger.info(f"Reporting API: 既存ジョブを再利用 jobId={job['id']}")
                return job["id"]

        try:
            created = (
                self._service.jobs().create(body={"reportTypeId": report_type_id, "name": self.JOB_NAME}).execute()
            )
        except HttpError as e:
            raise YouTubeAPIError.from_http_error(e, "reporting:jobs.create") from e

        job_id = created["id"]
        logger.info(
            f"Reporting API: ジョブを作成しました jobId={job_id} reportType={report_type_id}。"
            " 最初のレポート取得可能まで最大 48 時間（backfill で過去 30 日分が含まれる）。"
        )
        return job_id

    # ------------------------------------------------------------------
    # レポート列挙・ダウンロード
    # ------------------------------------------------------------------
    def list_recent_reports(self, job_id: str, since_days: int = 60) -> list[dict]:
        """指定ジョブの最近 since_days 日以内に生成されたレポートを返す。

        Args:
            job_id: ジョブ ID
            since_days: 何日前以降のレポートを取るか（最大 60 日）

        Returns:
            レポート dict のリスト（startTime / endTime / downloadUrl などを含む）
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        created_after = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

        reports: list[dict] = []
        page_token: str | None = None

        while True:
            try:
                kwargs: dict[str, Any] = {"jobId": job_id, "createdAfter": created_after}
                if page_token:
                    kwargs["pageToken"] = page_token
                response = self._service.jobs().reports().list(**kwargs).execute()
            except HttpError as e:
                raise YouTubeAPIError.from_http_error(e, "reporting:jobs.reports.list") from e

            reports.extend(response.get("reports", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break

        return reports

    def download_report_csv(self, download_url: str) -> str:
        """downloadUrl から CSV を取得して文字列で返す。

        AuthorizedSession で OAuth 付き HTTP GET を実行する。

        Args:
            download_url: report["downloadUrl"]

        Returns:
            UTF-8 デコード済み CSV テキスト

        Raises:
            YouTubeAPIError: HTTP 失敗、credentials 不在
        """
        if self._credentials is None:
            raise YouTubeAPIError("Reporting API: CSV ダウンロードには credentials が必要です")

        session = AuthorizedSession(self._credentials)
        try:
            response = session.get(download_url, timeout=_DOWNLOAD_TIMEOUT)
        except requests.exceptions.RequestException as e:
            raise YouTubeAPIError(f"reporting:download_csv: {e}") from e

        if response.status_code != 200:
            raise YouTubeAPIError(
                f"reporting:download_csv: HTTP {response.status_code} {response.text[:200]}",
                status_code=response.status_code,
            )

        return response.content.decode("utf-8")

    # ------------------------------------------------------------------
    # CSV パース
    # ------------------------------------------------------------------
    def parse_csv(self, csv_text: str) -> list[dict[str, Any]]:
        """CSV テキストを行ごとの dict にパース。

        ヘッダ行から impressions / ctr / video_id / date 列のインデックスを動的解決し、
        欠損列はスキップ（fail-open）。

        Args:
            csv_text: ダウンロード済み CSV テキスト

        Returns:
            行 dict のリスト。各 dict は以下のキーを持つ可能性がある:
            - date: str | None
            - video_id: str | None
            - impressions: int | None
            - ctr_percentage: float | None  (CTR 値、％換算済み)

        Raises:
            ValidationError: ヘッダに impressions / ctr 列が両方無い
        """
        reader = csv.reader(io.StringIO(csv_text))
        try:
            header = next(reader)
        except StopIteration:
            return []

        idx = {col.strip(): i for i, col in enumerate(header)}

        impressions_idx = _first_index(idx, _IMPRESSIONS_COLUMNS)
        ctr_idx = _first_index(idx, _CTR_COLUMNS)
        video_id_idx = _first_index(idx, _VIDEO_ID_COLUMNS)
        date_idx = _first_index(idx, _DATE_COLUMNS)

        if impressions_idx is None and ctr_idx is None:
            raise ValidationError(f"Reporting API CSV: impressions / ctr 列が見つかりません header={header}")

        rows: list[dict[str, Any]] = []
        for row in reader:
            if not row:
                continue
            entry: dict[str, Any] = {
                "date": _safe_str(row, date_idx),
                "video_id": _safe_str(row, video_id_idx),
                "impressions": _safe_int(row, impressions_idx),
                "ctr_percentage": _normalize_ctr(_safe_float(row, ctr_idx)),
            }
            rows.append(entry)
        return rows

    # ------------------------------------------------------------------
    # 高水準 API
    # ------------------------------------------------------------------
    def collect_impressions_summary(self, days: int = 7) -> dict[str, Any]:
        """select → ensure_job → list_recent_reports → download → parse → 集計。

        Args:
            days: 集計対象とする最近の日数（過去 60 日が最大）

        Returns:
            "source" / "selected_report_type" / "window_days" / "report_count" /
            "aggregated_impressions" / "aggregated_ctr_percentage" /
            "per_video" / "per_day" を含む dict
        """
        report_type_id = self.select_report_type()
        job_id = self.ensure_job(report_type_id)
        reports = self.list_recent_reports(job_id, since_days=days)

        if not reports:
            logger.warning(
                "Reporting API: 利用可能なレポートがありません。"
                " ジョブ作成直後の場合は最大 48 時間後に再実行してください。"
            )
            return {
                "source": f"youtubereporting.v1/{report_type_id}",
                "selected_report_type": report_type_id,
                "window_days": days,
                "report_count": 0,
                "aggregated_impressions": None,
                "aggregated_ctr_percentage": None,
                "per_video": [],
                "per_day": [],
            }

        all_rows: list[dict[str, Any]] = []
        for report in reports:
            url = report.get("downloadUrl")
            if not url:
                continue
            try:
                csv_text = self.download_report_csv(url)
                all_rows.extend(self.parse_csv(csv_text))
            except (YouTubeAPIError, ValidationError) as e:
                logger.warning(f"Reporting API: レポート 1 件のパースに失敗（続行）: {e}")
                continue

        return _aggregate_rows(
            rows=all_rows,
            report_type_id=report_type_id,
            window_days=days,
            report_count=len(reports),
        )


# ---------------------------------------------------------------------------
# ヘルパー（モジュール private）
# ---------------------------------------------------------------------------
def _first_index(idx: dict[str, int], candidates: Iterable[str]) -> int | None:
    for name in candidates:
        if name in idx:
            return idx[name]
    return None


def _safe_str(row: list[str], i: int | None) -> str | None:
    if i is None or i >= len(row):
        return None
    val = row[i].strip()
    return val or None


def _safe_int(row: list[str], i: int | None) -> int | None:
    val = _safe_str(row, i)
    if val is None:
        return None
    try:
        f = float(val)
    except ValueError:
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return int(f)


def _safe_float(row: list[str], i: int | None) -> float | None:
    val = _safe_str(row, i)
    if val is None:
        return None
    try:
        return float(val)
    except ValueError:
        return None


def _normalize_ctr(value: float | None) -> float | None:
    """Reporting API は CTR を 0-1 の比率で返すので 100 倍して % 化する。

    既に % 表記（>1.0）の場合はそのまま返す（堅牢化）。
    """
    if value is None:
        return None
    if 0.0 <= value <= 1.0:
        return value * 100
    return value


def _aggregate_rows(
    rows: list[dict[str, Any]],
    report_type_id: str,
    window_days: int,
    report_count: int,
) -> dict[str, Any]:
    """行データを per_video / per_day / aggregated に集計する。

    CTR は **impression 加重平均** で計算する (`weighted_ctr = Σ(imp × ctr) / Σ(imp)`)。
    Reach combined レポートでは 1 (video, date) に traffic_source / country / device 等
    複数 dimension の行が含まれるため、単純平均だと impression が大きい segment が
    過小評価され統計的に正しくない。Reach basic 単一行ケースでも結果は変わらない。
    """
    per_video_imp: dict[str, int] = defaultdict(int)
    per_video_weighted: dict[str, float] = defaultdict(float)

    per_day_imp: dict[str, int] = defaultdict(int)
    per_day_weighted: dict[str, float] = defaultdict(float)

    total_impressions = 0
    total_weighted = 0.0

    for row in rows:
        imp = row.get("impressions")
        ctr = row.get("ctr_percentage")
        vid = row.get("video_id")
        day = row.get("date")

        if imp is None:
            continue

        total_impressions += imp
        if vid:
            per_video_imp[vid] += imp
        if day:
            per_day_imp[day] += imp

        if ctr is None:
            continue

        weighted = imp * ctr
        total_weighted += weighted
        if vid:
            per_video_weighted[vid] += weighted
        if day:
            per_day_weighted[day] += weighted

    per_video = [
        {
            "video_id": vid,
            "impressions": per_video_imp[vid],
            "ctr_percentage": (per_video_weighted[vid] / per_video_imp[vid]) if per_video_imp[vid] > 0 else None,
        }
        for vid in sorted(per_video_imp)
    ]
    per_day = [
        {
            "date": day,
            "impressions": per_day_imp[day],
            "ctr_percentage": (per_day_weighted[day] / per_day_imp[day]) if per_day_imp[day] > 0 else None,
        }
        for day in sorted(per_day_imp)
    ]

    return {
        "source": f"youtubereporting.v1/{report_type_id}",
        "selected_report_type": report_type_id,
        "window_days": window_days,
        "report_count": report_count,
        "aggregated_impressions": total_impressions if total_impressions else None,
        "aggregated_ctr_percentage": (total_weighted / total_impressions) if total_impressions else None,
        "per_video": per_video,
        "per_day": per_day,
    }
