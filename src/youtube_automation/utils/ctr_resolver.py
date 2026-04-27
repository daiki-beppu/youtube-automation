"""CTR メトリクスの取得元を一元化するヘルパー。

YouTube Analytics API では `videoThumbnailImpressions` が取得できないため、
Reporting API v1 由来データ (`reporting_api.impressions_summary`) があれば最優先で使う。

優先順:
  1. reporting_api.impressions_summary (Reporting API v1, #84)
  2. ctr_analysis.impressions_summary (旧予約口、現状 None)
  3. channel_ctr.average_ctr * 100 (フォールバック)

使用例:
    from youtube_automation.utils.ctr_resolver import resolve_ctr_summary

    summary = resolve_ctr_summary(analytics_data)
    if summary:
        ctr_pct = summary["aggregated_ctr_percentage"]
"""

from __future__ import annotations

from typing import Any


def index_reporting_per_video(source: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Reporting API per_video データを {video_id: row} に索引化する（fail-open）。

    `source` は以下のいずれの形でも受け付ける:
      - analytics_data 全体（`reporting_api.impressions_summary.per_video` を掘る）
      - impressions_summary 直接（`per_video` を直接読む）
      - None / 不正形 → {} を返す
    """
    if not isinstance(source, dict):
        return {}
    if "reporting_api" in source:
        summary = source.get("reporting_api", {})
        if isinstance(summary, dict):
            summary = summary.get("impressions_summary", {})
    else:
        summary = source
    if not isinstance(summary, dict):
        return {}
    per_video = summary.get("per_video") or []
    return {row["video_id"]: row for row in per_video if isinstance(row, dict) and row.get("video_id")}


def resolve_ctr_summary(analytics_data: dict[str, Any]) -> dict[str, Any] | None:
    """analytics_data から CTR サマリを取り出す（最優先 reporting_api → 旧 → fallback）。

    Args:
        analytics_data: analytics_collector.collect_basic_analytics() の戻り値

    Returns:
        以下のキーを持つ dict、または取得不能時に None:
        - source: str (取得元の識別子)
        - aggregated_ctr_percentage: float | None
        - 上記以外のキーは取得元によって異なる
    """
    reporting = analytics_data.get("reporting_api", {})
    if isinstance(reporting, dict):
        ra = reporting.get("impressions_summary")
        if isinstance(ra, dict) and ra.get("aggregated_ctr_percentage") is not None:
            return ra

    legacy = analytics_data.get("ctr_analysis", {})
    if isinstance(legacy, dict):
        legacy_summary = legacy.get("impressions_summary")
        if isinstance(legacy_summary, dict) and legacy_summary.get("aggregated_ctr_percentage") is not None:
            return legacy_summary

    channel_ctr = analytics_data.get("channel_ctr", {})
    if isinstance(channel_ctr, dict):
        avg = channel_ctr.get("average_ctr")
        if isinstance(avg, (int, float)) and avg > 0:
            return {
                "source": "fallback:channel_ctr",
                "aggregated_ctr_percentage": avg * 100,
            }

    return None
