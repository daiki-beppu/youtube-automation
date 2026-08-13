"""全チャンネル動画の views-per-day ランキング構築。"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from fractions import Fraction
from typing import Protocol

from youtube_automation.core.errors import ValidationError


class _VideoCollector(Protocol):
    def get_all_channel_videos(self, refresh: bool = False) -> list[dict]: ...

    def get_video_details(self, video_ids: list[str]) -> dict[str, dict]: ...


def _parse_view_count(value: object, video_id: str) -> int:
    if isinstance(value, bool):
        raise ValidationError(f"videos.list statistics.viewCount が不正です: {video_id}")
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise ValidationError(f"videos.list statistics.viewCount が不正です: {video_id}") from error
    if parsed < 0 or str(parsed) != str(value):
        raise ValidationError(f"videos.list statistics.viewCount が不正です: {video_id}")
    return parsed


def collect_all_video_statistics(collector: _VideoCollector) -> list[dict[str, object]]:
    """uploads playlist 全ページを起点に累計 viewCount を全件取得する。"""
    uploads = collector.get_all_channel_videos(refresh=True)
    video_ids = [video["video_id"] for video in uploads]
    details: dict[str, dict] = {}
    for start in range(0, len(video_ids), 50):
        batch = video_ids[start : start + 50]
        details.update(collector.get_video_details(batch))

    result: list[dict[str, object]] = []
    for video in uploads:
        video_id = video["video_id"]
        detail = details.get(video_id)
        if not isinstance(detail, dict) or "view_count" not in detail:
            raise ValidationError(f"videos.list statistics.viewCount がありません: {video_id}")
        result.append(
            {
                "video_id": video_id,
                "title": video["title"],
                "published_at": video["published_at"],
                "cumulative_views": _parse_view_count(detail["view_count"], video_id),
            }
        )
    return result


def _published_utc(value: object, video_id: str) -> datetime:
    if not isinstance(value, str):
        raise ValidationError(f"published_at が不正です: {video_id}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValidationError(f"published_at が不正です: {video_id}") from error
    if parsed.tzinfo is None:
        raise ValidationError(f"published_at に timezone がありません: {video_id}")
    return parsed.astimezone(timezone.utc)


def _group(items: list[dict[str, object]]) -> dict[str, object]:
    vpds = [float(item["vpd"]) for item in items]
    return {
        "count": len(items),
        "min_vpd": min(vpds) if vpds else None,
        "max_vpd": max(vpds) if vpds else None,
        "items": items,
    }


def build_vpd_ranking(
    videos: list[dict[str, object]],
    *,
    now: datetime | None = None,
    min_age_days: int = 7,
    top_count: int | None = None,
) -> dict[str, object]:
    """累計 views / UTC 公開日齢を計算し、上位・中間・下位へ分割する。"""
    if min_age_days < 0:
        raise ValidationError("min-age-days は 0 以上で指定してください")
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        raise ValidationError("now は timezone-aware datetime でなければなりません")
    reference_date = reference.astimezone(timezone.utc).date()

    ranked_with_ratio: list[tuple[Fraction, dict[str, object]]] = []
    excluded_count = 0
    for video in videos:
        video_id = video.get("video_id")
        if not isinstance(video_id, str) or not video_id:
            raise ValidationError("video_id が不正です")
        published = _published_utc(video.get("published_at"), video_id)
        age_days = max(0, (reference_date - published.date()).days)
        if age_days < min_age_days:
            excluded_count += 1
            continue
        days_since_publish = max(1, age_days)
        views = _parse_view_count(video.get("cumulative_views"), video_id)
        ratio = Fraction(views, days_since_publish)
        item = {
            "video_id": video_id,
            "title": video.get("title", ""),
            "published_at": video["published_at"],
            "cumulative_views": views,
            "days_since_publish": days_since_publish,
            "vpd": round(float(ratio), 6),
        }
        ranked_with_ratio.append((ratio, item))

    ranked_with_ratio.sort(key=lambda pair: (-pair[0], str(pair[1]["video_id"])))
    ranking = [item for _, item in ranked_with_ratio]
    n = len(ranking)
    if n < 2:
        raise ValidationError("vpd の群分けには対象動画が 2 本以上必要です")

    k = math.ceil(n / 4) if top_count is None else top_count
    if k < 1 or k > n // 2:
        raise ValidationError(f"top-count は 1 以上 {n // 2} 以下で指定してください")
    top = ranking[:k]
    middle = ranking[k : n - k]
    bottom = ranking[n - k :]
    return {
        "n": n,
        "k": k,
        "min_age_days": min_age_days,
        "excluded_count": excluded_count,
        "ranking": ranking,
        "groups": {"top": _group(top), "middle": _group(middle), "bottom": _group(bottom)},
    }
