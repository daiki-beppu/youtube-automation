"""VPD 上位・下位群の属性別パターン集計。"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

from youtube_automation.core.errors import ValidationError
from youtube_automation.infrastructure.analytics.retention_timeline import parse_iso8601_duration
from youtube_automation.infrastructure.analytics.theme_performance import classify_videos_by_theme

VISUAL_ATTRIBUTES = ("composition", "color", "text_placement", "visual_flow", "subject")
AUTOMATIC_ATTRIBUTES = ("theme", "title_pattern", "duration", "publish_weekday", "publish_time")
UNDETERMINED = "undetermined"
DISCLAIMER = "Observed correlation in this VPD-ranked population; correlation does not imply causation."


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"ranking {name} は整数である必要があります")
    return value


def _group_items(ranking: dict, name: str) -> list[dict]:
    groups = ranking.get("groups")
    if not isinstance(groups, dict) or not isinstance(groups.get(name), dict):
        raise ValidationError(f"ranking group {name} が不正です")
    group = groups[name]
    items = group.get("items")
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ValidationError(f"ranking group {name}.items が不正です")
    if group.get("count") != len(items):
        raise ValidationError(f"ranking group {name}.count が items と一致しません")
    return items


def _ids(items: list[dict], context: str) -> list[str]:
    ids: list[str] = []
    for item in items:
        video_id = item.get("video_id")
        if not isinstance(video_id, str) or not video_id:
            raise ValidationError(f"ranking {context} の video_id が不正です")
        ids.append(video_id)
    if len(ids) != len(set(ids)):
        raise ValidationError(f"ranking {context} に重複 video_id があります")
    return ids


def validate_ranking(ranking: object) -> dict:
    """#3781 schema の群分けに重複・欠落・件数不整合がないことを確認する。"""
    if not isinstance(ranking, dict):
        raise ValidationError("ranking は JSON object である必要があります")
    n = _integer(ranking.get("n"), "n")
    k = _integer(ranking.get("k"), "k")
    ordered = ranking.get("ranking")
    if not isinstance(ordered, list) or not all(isinstance(item, dict) for item in ordered):
        raise ValidationError("ranking.ranking が不正です")
    top = _group_items(ranking, "top")
    middle = _group_items(ranking, "middle")
    bottom = _group_items(ranking, "bottom")
    if n != len(ordered) or n < 2:
        raise ValidationError("ranking n が ranking 件数と一致しません")
    if k < 1 or k > n // 2 or len(top) != k or len(bottom) != k or len(middle) != n - 2 * k:
        raise ValidationError("ranking k と group 件数が一致しません")
    ordered_ids = _ids(ordered, "ranking")
    grouped_ids = [*_ids(top, "top"), *_ids(middle, "middle"), *_ids(bottom, "bottom")]
    if len(grouped_ids) != len(set(grouped_ids)) or grouped_ids != ordered_ids:
        raise ValidationError("ranking group に重複・欠落・順序不整合があります")
    return ranking


def _compile_title_patterns(raw: object) -> list[tuple[str, re.Pattern[str]]]:
    if not isinstance(raw, list):
        raise ValidationError("title_patterns は配列である必要があります")
    compiled: list[tuple[str, re.Pattern[str]]] = []
    names: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict) or set(entry) != {"name", "regex"}:
            raise ValidationError("title_patterns の各要素には name と regex が必要です")
        name, regex = entry["name"], entry["regex"]
        if not isinstance(name, str) or not name.strip() or not isinstance(regex, str) or not regex:
            raise ValidationError("title_patterns の name / regex が不正です")
        if name in names or name in {"other", UNDETERMINED}:
            raise ValidationError(f"title_patterns の name が重複または予約済みです: {name!r}")
        try:
            pattern = re.compile(regex, re.IGNORECASE)
        except re.error as error:
            raise ValidationError(f"title_patterns の正規表現が不正です: {name!r}") from error
        names.add(name)
        compiled.append((name, pattern))
    return compiled


def _duration_bin(raw: object) -> str:
    if raw is None:
        return UNDETERMINED
    if not isinstance(raw, str):
        raise ValidationError("動画 duration は ISO 8601 文字列である必要があります")
    seconds = parse_iso8601_duration(raw)
    if seconds < 60:
        return "under_60_seconds"
    if seconds < 600:
        return "60_to_599_seconds"
    if seconds < 3600:
        return "600_to_3599_seconds"
    return "3600_seconds_or_more"


def _published_bins(raw: object, video_id: str) -> tuple[str, str]:
    if not isinstance(raw, str):
        raise ValidationError(f"published_at が不正です: {video_id}")
    try:
        published = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValidationError(f"published_at が不正です: {video_id}") from error
    if published.tzinfo is None:
        raise ValidationError(f"published_at に timezone がありません: {video_id}")
    utc = published.astimezone(timezone.utc)
    start = (utc.hour // 6) * 6
    return utc.strftime("%A"), f"{start:02d}:00-{start + 5:02d}:59"


def build_automatic_attributes(
    videos: list[dict],
    *,
    theme_keywords: dict[str, list[str]],
    title_patterns: object,
) -> dict[str, dict[str, str]]:
    """テーマ・タイトル型・尺・UTC 公開曜日/時間帯を決定的に分類する。"""
    video_ids = _ids(videos, "automatic attributes")
    metadata = {video_id: video for video_id, video in zip(video_ids, videos, strict=True)}
    theme_groups = classify_videos_by_theme(metadata, theme_keywords)
    themes = {video_id: theme for theme, ids in theme_groups.items() for video_id in ids}
    compiled_patterns = _compile_title_patterns(title_patterns)
    output = {name: {} for name in AUTOMATIC_ATTRIBUTES}
    for video_id, video in metadata.items():
        title = video.get("title")
        if not isinstance(title, str):
            raise ValidationError(f"title が不正です: {video_id}")
        title_pattern = next((name for name, pattern in compiled_patterns if pattern.search(title)), "other")
        weekday, time_bin = _published_bins(video.get("published_at"), video_id)
        output["theme"][video_id] = themes[video_id]
        output["title_pattern"][video_id] = title_pattern
        output["duration"][video_id] = _duration_bin(video.get("duration"))
        output["publish_weekday"][video_id] = weekday
        output["publish_time"][video_id] = time_bin
    return output


def load_annotations(path: Path | None, *, known_video_ids: set[str]) -> dict[str, dict[str, str]]:
    """目視 5 属性を strict JSON から読み、欠損を undetermined に正規化する。"""
    output = {name: {video_id: UNDETERMINED for video_id in known_video_ids} for name in VISUAL_ATTRIBUTES}
    if path is None:
        return output
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValidationError(f"annotation JSON を読めません: {path}") from error
    if not isinstance(payload, dict) or set(payload) != {"videos"} or not isinstance(payload["videos"], list):
        raise ValidationError("annotation root は videos 配列だけを持つ object である必要があります")
    seen: set[str] = set()
    for entry in payload["videos"]:
        if not isinstance(entry, dict) or not set(entry).issubset({"video_id", *VISUAL_ATTRIBUTES}):
            raise ValidationError("annotation entry の shape が不正です")
        video_id = entry.get("video_id")
        if not isinstance(video_id, str) or video_id not in known_video_ids or video_id in seen:
            raise ValidationError(f"annotation video_id が未知・不正・重複です: {video_id!r}")
        seen.add(video_id)
        for name in VISUAL_ATTRIBUTES:
            value = entry.get(name)
            if value is None:
                continue
            if not isinstance(value, str) or not value.strip() or value == UNDETERMINED:
                raise ValidationError(f"annotation {name} が不正です: {video_id}")
            output[name][video_id] = value
    return output


def evaluate_pattern(*, top_count: int, top_known: int, bottom_count: int, bottom_known: int) -> str:
    """丸め前の有理数で 60% / 20pp の inclusive 境界を判定する。"""
    if top_known == 0 or bottom_known == 0:
        return "hold"
    top = Fraction(top_count, top_known)
    bottom = Fraction(bottom_count, bottom_known)
    threshold = Fraction(3, 5)
    difference = Fraction(1, 5)
    if top >= threshold and top - bottom >= difference:
        return "win"
    if bottom >= threshold and bottom - top >= difference:
        return "loss"
    return "hold"


def aggregate_patterns(ranking: dict, attributes: dict[str, dict[str, str]]) -> dict[str, dict]:
    """入力元を問わず全属性を同一の known-denominator 集計器へ通す。"""
    ranking = validate_ranking(ranking)
    top_ids = _ids(_group_items(ranking, "top"), "top")
    bottom_ids = _ids(_group_items(ranking, "bottom"), "bottom")
    known_ids = set(_ids(ranking["ranking"], "ranking"))
    result: dict[str, dict] = {}
    for attribute, mapping in attributes.items():
        if not isinstance(mapping, dict) or set(mapping) != known_ids:
            raise ValidationError(f"attribute {attribute} の video_id に欠落・未知 ID があります")
        if not all(isinstance(value, str) and value for value in mapping.values()):
            raise ValidationError(f"attribute {attribute} の分類値が不正です")
        top_known = sum(mapping[video_id] != UNDETERMINED for video_id in top_ids)
        bottom_known = sum(mapping[video_id] != UNDETERMINED for video_id in bottom_ids)
        values = sorted(set(mapping.values()) - {UNDETERMINED})
        value_results: dict[str, dict] = {}
        for value in values:
            top_matches = [video_id for video_id in top_ids if mapping[video_id] == value]
            bottom_matches = [video_id for video_id in bottom_ids if mapping[video_id] == value]
            top_ratio = Fraction(len(top_matches), top_known) if top_known else None
            bottom_ratio = Fraction(len(bottom_matches), bottom_known) if bottom_known else None
            pp = float((top_ratio - bottom_ratio) * 100) if top_ratio is not None and bottom_ratio is not None else None
            value_results[value] = {
                "top_count": len(top_matches),
                "bottom_count": len(bottom_matches),
                "top_known_count": top_known,
                "bottom_known_count": bottom_known,
                "top_percentage": round(float(top_ratio * 100), 6) if top_ratio is not None else None,
                "bottom_percentage": round(float(bottom_ratio * 100), 6) if bottom_ratio is not None else None,
                "pp_difference": round(pp, 6) if pp is not None else None,
                "classification": evaluate_pattern(
                    top_count=len(top_matches),
                    top_known=top_known,
                    bottom_count=len(bottom_matches),
                    bottom_known=bottom_known,
                ),
                "undetermined_count": {
                    "top": len(top_ids) - top_known,
                    "bottom": len(bottom_ids) - bottom_known,
                },
                "representative_video_ids": sorted([*top_matches, *bottom_matches]),
            }
        result[attribute] = {
            "top_known_count": top_known,
            "bottom_known_count": bottom_known,
            "undetermined_count": {"top": len(top_ids) - top_known, "bottom": len(bottom_ids) - bottom_known},
            "values": value_results,
        }
    return result


def build_win_pattern_result(ranking: dict, attributes: dict[str, dict[str, str]]) -> dict[str, object]:
    ranking = validate_ranking(ranking)
    return {
        "n": ranking["n"],
        "k": ranking["k"],
        "min_age_days": ranking.get("min_age_days"),
        "attributes": aggregate_patterns(ranking, attributes),
        "disclaimer": DISCLAIMER,
    }
