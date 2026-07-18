"""TTP 対象チャンネルの投稿停滞・再生低下を判定する純関数。"""

from __future__ import annotations

from datetime import date, timedelta


def _window(start: date, end: date, videos: list[tuple[date, int]]) -> dict:
    values = [views for published_at, views in videos if start <= published_at <= end]
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "video_count": len(values),
        "avg_views": round(sum(values) / len(values)) if values else None,
    }


def _missing_channel(config_channel: dict, kind: str, detail: str) -> dict:
    return {
        "slug": config_channel.get("slug"),
        "name": config_channel.get("name"),
        "channel_id": config_channel.get("id"),
        "status": "missing_data",
        "last_upload_at": None,
        "days_since_last_upload": None,
        "recent_window": None,
        "prior_window": None,
        "alerts": [],
        "insufficiencies": [{"kind": kind, "detail": detail}],
    }


def _find_benchmark_channel(config_channel: dict, benchmark_channels: list[dict]) -> dict | None:
    slug = config_channel.get("slug")
    if slug:
        return next((channel for channel in benchmark_channels if channel.get("slug") == slug), None)
    channel_id = config_channel.get("id")
    if channel_id:
        return next(
            (channel for channel in benchmark_channels if channel.get("channel_id", channel.get("id")) == channel_id),
            None,
        )
    return None


def evaluate_ttp_health(
    config_channels: list[dict],
    benchmark_data: dict,
    *,
    stale_days: int = 60,
    decline_ratio: float = 0.5,
    window_days: int = 90,
) -> dict:
    """Benchmark の pre-filter 投稿走査結果から TTP 健全性を評価する。"""
    reference_date = date.fromisoformat(benchmark_data["collected_at"])
    source = benchmark_data.get("source") or f"benchmark_{reference_date.strftime('%Y%m%d')}.json"
    benchmark_channels = benchmark_data.get("channels") or []
    recent_start = reference_date - timedelta(days=window_days)
    prior_start = reference_date - timedelta(days=2 * window_days)
    prior_end = recent_start - timedelta(days=1)
    results = []

    for config_channel in config_channels:
        benchmark_channel = _find_benchmark_channel(config_channel, benchmark_channels)
        identity = config_channel.get("slug") or config_channel.get("id") or "識別子なし"
        if benchmark_channel is None:
            results.append(
                _missing_channel(
                    config_channel,
                    "missing_benchmark_entry",
                    f"benchmark JSON に対象チャンネルがありません: {identity}",
                )
            )
            continue

        upload_scan = benchmark_channel.get("upload_scan")
        if not isinstance(upload_scan, dict):
            results.append(
                _missing_channel(
                    config_channel,
                    "missing_upload_scan",
                    f"{identity} に upload_scan がありません。/benchmark を再実行してください。",
                )
            )
            continue

        alerts: list[dict] = []
        insufficiencies: list[dict] = []
        parsed_videos: list[tuple[date, int]] = []
        raw_scan_videos = upload_scan.get("videos") or []
        for index, video in enumerate(raw_scan_videos):
            published_at = video.get("published_at")
            try:
                parsed_date = date.fromisoformat(published_at)
            except (TypeError, ValueError):
                insufficiencies.append(
                    {
                        "kind": "invalid_upload_date",
                        "detail": f"upload_scan.videos[{index}].published_at を解釈できません: {published_at!r}",
                    }
                )
                continue
            parsed_videos.append((parsed_date, int(video.get("views", 0))))

        recent_window = _window(recent_start, reference_date, parsed_videos)
        prior_window = _window(prior_start, prior_end, parsed_videos)

        latest_upload_at = upload_scan.get("latest_upload_at")
        days_since_last_upload = None
        if not raw_scan_videos:
            insufficiencies.append({"kind": "no_scanned_uploads", "detail": "走査できた投稿がありません。"})
        else:
            try:
                latest_date = date.fromisoformat(latest_upload_at)
            except (TypeError, ValueError):
                insufficiencies.append(
                    {
                        "kind": "invalid_latest_upload_at",
                        "detail": f"latest_upload_at を解釈できません: {latest_upload_at!r}",
                    }
                )
            else:
                days_since_last_upload = (reference_date - latest_date).days
                if days_since_last_upload >= stale_days:
                    alerts.append(
                        {
                            "type": "stale_posting",
                            "reason": (
                                f"最終投稿 {latest_upload_at} から {days_since_last_upload} 日経過"
                                f"（閾値 {stale_days} 日）"
                            ),
                            "days_since_last_upload": days_since_last_upload,
                            "threshold_days": stale_days,
                        }
                    )

        coverage_complete = upload_scan.get("complete") is True
        if not coverage_complete:
            oldest_upload_at = upload_scan.get("oldest_upload_at")
            try:
                oldest_date = date.fromisoformat(oldest_upload_at)
            except (TypeError, ValueError):
                oldest_date = None
            coverage_complete = oldest_date is not None and oldest_date <= prior_start

        if not coverage_complete:
            insufficiencies.append(
                {
                    "kind": "incomplete_window_coverage",
                    "detail": (
                        f"走査範囲が前期開始日 {prior_start.isoformat()} まで到達していません"
                        f"（oldest_upload_at={upload_scan.get('oldest_upload_at')!r}）。"
                    ),
                }
            )
        elif prior_window["video_count"] == 0:
            insufficiencies.append(
                {"kind": "no_prior_window_uploads", "detail": "前期ウィンドウに比較対象の投稿がありません。"}
            )
        elif prior_window["avg_views"] <= 0:
            insufficiencies.append(
                {"kind": "nonpositive_prior_average", "detail": "前期平均再生数が 0 以下のため比較できません。"}
            )
        else:
            recent_average = recent_window["avg_views"] if recent_window["avg_views"] is not None else 0
            prior_average = prior_window["avg_views"]
            ratio = recent_average / prior_average
            if ratio <= decline_ratio:
                if recent_window["video_count"] == 0:
                    reason = (
                        f"直近{window_days}日に投稿なし。前期平均 {prior_average:,} に対する比率は 0%"
                        f"（閾値 {decline_ratio:.0%}）"
                    )
                else:
                    reason = (
                        f"直近{window_days}日平均 {recent_average:,} は前期平均 {prior_average:,} の "
                        f"{ratio:.0%}（閾値 {decline_ratio:.0%}）"
                    )
                alerts.append(
                    {
                        "type": "views_decline",
                        "reason": reason,
                        "recent_avg_views": recent_average,
                        "prior_avg_views": prior_average,
                        "ratio": round(ratio, 2),
                        "threshold_ratio": decline_ratio,
                        "recent_window": recent_window,
                        "prior_window": prior_window,
                    }
                )

        status = "alert" if alerts else "insufficient_data" if insufficiencies else "healthy"
        results.append(
            {
                "slug": config_channel.get("slug") or benchmark_channel.get("slug"),
                "name": config_channel.get("name") or benchmark_channel.get("name"),
                "channel_id": config_channel.get("id") or benchmark_channel.get("channel_id"),
                "status": status,
                "last_upload_at": latest_upload_at,
                "days_since_last_upload": days_since_last_upload,
                "recent_window": recent_window,
                "prior_window": prior_window,
                "alerts": alerts,
                "insufficiencies": insufficiencies,
            }
        )

    return {
        "status": "ok",
        "source": source,
        "reference_date": reference_date.isoformat(),
        "thresholds": {
            "stale_days": stale_days,
            "decline_ratio": decline_ratio,
            "window_days": window_days,
        },
        "channels": results,
    }
