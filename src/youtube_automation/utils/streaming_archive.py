"""ライブ配信のアーカイブ件数を YouTube Data API から数えるユーティリティ。

11h+1h サイクルでは 1 日 2 本のアーカイブが残るのが正常状態。これを下回ったら
配信トラブル（停止していて再開していない、live だが終了せずアーカイブ未生成等）
の可能性があるため、外部から件数を確認できる手段として提供する。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any


def count_archives_for_date(youtube_service: Any, target_date: date) -> int:
    """指定した日付に ``actualEndTime`` を持つアーカイブ済みライブ配信の件数を返す。

    判定:
        1. ``search.list`` で target_date 周辺のライブ配信完了動画を集める
           （``publishedAt`` は配信開始時刻なので UTC 日跨ぎ配信を取りこぼさないよう
           ``[target_date - 1d, target_date + 2d)`` の余白を持って検索する）
        2. ``videos.list(part="snippet,liveStreamingDetails")`` で詳細を取得
        3. ``snippet.liveBroadcastContent == "none"`` かつ
           ``liveStreamingDetails.actualEndTime`` が target_date(UTC) 内に収まるものを数える

    Args:
        youtube_service: ``googleapiclient`` の YouTube Data API v3 リソース
        target_date: 数える対象の日付（UTC 基準）

    Returns:
        条件を満たすアーカイブ件数
    """
    # search.list の publishedAt は配信開始時刻基準。11h+1h サイクルでは
    # 前日に開始 → target_date 早朝に終了する配信や、target_date 深夜に開始 →
    # 翌日早朝に終了する配信があるため、検索窓を ±1日広げて取りこぼしを防ぐ。
    # 最終的な日付一致判定は actualEndTime で行う。
    search_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc) - timedelta(
        days=1
    )
    search_end = search_start + timedelta(days=3)

    search_response = (
        youtube_service.search()
        .list(
            forMine=True,
            type="video",
            eventType="completed",
            publishedAfter=search_start.isoformat().replace("+00:00", "Z"),
            publishedBefore=search_end.isoformat().replace("+00:00", "Z"),
            part="id",
            maxResults=50,
        )
        .execute()
    )

    video_ids = [item["id"]["videoId"] for item in search_response.get("items", []) if "videoId" in item.get("id", {})]
    if not video_ids:
        return 0

    videos_response = (
        youtube_service.videos().list(id=",".join(video_ids), part="snippet,liveStreamingDetails").execute()
    )

    count = 0
    for video in videos_response.get("items", []):
        snippet = video.get("snippet", {})
        if snippet.get("liveBroadcastContent") != "none":
            continue
        details = video.get("liveStreamingDetails")
        if not details:
            # 通常動画（ライブ由来でない）は数えない
            continue
        actual_end = details.get("actualEndTime")
        if not actual_end:
            continue
        # Python 3.11+ の fromisoformat は末尾 'Z' を直接受理する
        ended_at = datetime.fromisoformat(actual_end)
        if ended_at.astimezone(timezone.utc).date() == target_date:
            count += 1
    return count
