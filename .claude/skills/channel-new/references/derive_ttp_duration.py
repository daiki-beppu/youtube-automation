#!/usr/bin/env python3
"""承認済み TTP の benchmark から初期動画尺の推奨範囲を導出する。"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections.abc import Iterable
from pathlib import Path

from youtube_automation.scripts.benchmark_collector import (
    TTP_VIDEO_ANALYZE_TOP_N,
    find_latest_benchmark_json,
    is_live_benchmark_video,
    is_short_benchmark_video,
)

_DURATION_RE = re.compile(
    r"P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?\Z"
)


class DurationDerivationError(ValueError):
    """動画尺の入力または反映先が不正。"""


def parse_duration_seconds(value: object) -> int | None:
    """YouTube contentDetails.duration の ISO 8601 値を秒へ変換する。"""
    text = str(value or "").strip()
    match = _DURATION_RE.fullmatch(text)
    if not match or not any(match.groupdict().values()):
        return None
    days = int(match.group("days") or 0)
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)
    return days * 86_400 + hours * 3_600 + minutes * 60 + seconds


def _views(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _video_evidence(video: dict[str, object], *, duration_seconds: int) -> dict[str, object]:
    return {
        "video_id": str(video.get("video_id") or ""),
        "views": _views(video.get("views")),
        "duration_iso": str(video.get("duration_iso") or ""),
        "duration_display": str(video.get("duration_display") or ""),
        "duration_seconds": duration_seconds,
    }


def _excluded_evidence(video: dict[str, object], reason: str) -> dict[str, object]:
    return {
        "video_id": str(video.get("video_id") or ""),
        "views": _views(video.get("views")),
        "duration_iso": str(video.get("duration_iso") or ""),
        "reason": reason,
    }


def derive_ttp_duration(
    benchmark: dict[str, object],
    approved_channels: list[dict[str, object]],
    *,
    top_n: int = TTP_VIDEO_ANALYZE_TOP_N,
) -> dict[str, object]:
    """各承認 TTP から上位 Long VOD を選び、分単位の外向き範囲を返す。"""
    raw_channels = benchmark.get("channels")
    if not isinstance(raw_channels, list):
        raise DurationDerivationError("benchmark JSON の channels が配列ではありません")

    benchmark_by_slug = {
        str(channel.get("slug") or "").strip(): channel
        for channel in raw_channels
        if isinstance(channel, dict) and str(channel.get("slug") or "").strip()
    }
    results: list[dict[str, object]] = []
    errors: list[str] = []
    all_selected: list[dict[str, object]] = []
    seen_slugs: set[str] = set()

    for approved in approved_channels:
        slug = str(approved.get("slug") or "").strip()
        if not slug:
            errors.append("承認済み TTP channel に slug がありません")
            continue
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        benchmark_channel = benchmark_by_slug.get(slug)
        if benchmark_channel is None:
            errors.append(f"{slug}: 最新 benchmark JSON に channel がありません")
            continue
        raw_videos = benchmark_channel.get("videos")
        if not isinstance(raw_videos, list):
            errors.append(f"{slug}: benchmark videos が配列ではありません")
            continue

        videos = [video for video in raw_videos if isinstance(video, dict)]
        videos.sort(key=lambda video: (-_views(video.get("views")), str(video.get("video_id") or "")))
        selected: list[dict[str, object]] = []
        excluded: list[dict[str, object]] = []
        for video in videos:
            if len(selected) >= top_n:
                break
            if is_live_benchmark_video(video):
                excluded.append(_excluded_evidence(video, "live"))
                continue
            if is_short_benchmark_video(video):
                excluded.append(_excluded_evidence(video, "short"))
                continue
            duration_seconds = parse_duration_seconds(video.get("duration_iso"))
            if duration_seconds is None or duration_seconds <= 0:
                excluded.append(_excluded_evidence(video, "invalid_duration"))
                continue
            if not str(video.get("video_id") or "").strip():
                excluded.append(_excluded_evidence(video, "missing_video_id"))
                continue
            evidence = _video_evidence(video, duration_seconds=duration_seconds)
            selected.append(evidence)
            all_selected.append(evidence)

        result = {
            "slug": slug,
            "channel_id": str(approved.get("id") or ""),
            "name": str(approved.get("name") or benchmark_channel.get("name") or ""),
            "selected": selected,
            "excluded": excluded,
        }
        results.append(result)
        if len(selected) < top_n:
            errors.append(f"{slug}: 有効な Long VOD が不足 ({len(selected)}/{top_n})")

    report: dict[str, object] = {
        "status": "insufficient" if errors else "ok",
        "top_n": top_n,
        "channels": results,
        "errors": errors,
    }
    if not errors and all_selected:
        shortest = min(int(video["duration_seconds"]) for video in all_selected)
        longest = max(int(video["duration_seconds"]) for video in all_selected)
        report.update(
            {
                "target_duration_min": math.floor(shortest / 60),
                "target_duration_max": math.ceil(longest / 60),
            }
        )
    return report


def _read_json_object(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DurationDerivationError(f"ファイルが見つかりません: {path}") from exc
    except (json.JSONDecodeError, OSError) as exc:
        raise DurationDerivationError(f"JSON を読み込めません: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise DurationDerivationError(f"JSON のトップレベルが object ではありません: {path}")
    return payload


def _approved_channels(channel_dir: Path) -> list[dict[str, object]]:
    analytics = _read_json_object(channel_dir / "config" / "channel" / "analytics.json")
    benchmark = analytics.get("benchmark")
    channels = benchmark.get("channels") if isinstance(benchmark, dict) else None
    if not isinstance(channels, list) or not channels:
        raise DurationDerivationError("analytics.json に承認済み benchmark.channels がありません")
    if not all(isinstance(channel, dict) for channel in channels):
        raise DurationDerivationError("benchmark.channels に object 以外の entry があります")
    return channels


def apply_duration_recommendation(channel_dir: Path, report: dict[str, object]) -> Path:
    """承認後の推奨値を既存 audio.json の duration 2項目だけへ反映する。"""
    if report.get("status") != "ok":
        raise DurationDerivationError("動画不足または入力不備があるため推奨値を反映できません")
    target_min = report.get("target_duration_min")
    target_max = report.get("target_duration_max")
    if not isinstance(target_min, int) or not isinstance(target_max, int):
        raise DurationDerivationError("推奨 min/max が整数ではありません")

    audio_path = channel_dir / "config" / "channel" / "audio.json"
    payload = _read_json_object(audio_path)
    audio = payload.get("audio")
    if not isinstance(audio, dict):
        raise DurationDerivationError("audio.json::audio が object ではありません")
    audio["target_duration_min"] = float(target_min)
    audio["target_duration_max"] = float(target_max)
    audio_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return audio_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel-dir", type=Path, default=Path.cwd())
    parser.add_argument(
        "--apply",
        action="store_true",
        help="ユーザー承認後に限り、推奨 min/max を config/channel/audio.json へ反映する",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    channel_dir = args.channel_dir.resolve()
    try:
        approved = _approved_channels(channel_dir)
        benchmark_path = find_latest_benchmark_json(channel_dir / "data")
        if benchmark_path is None:
            raise DurationDerivationError("data/benchmark_*.json がありません。先に /benchmark を実行してください")
        report = derive_ttp_duration(_read_json_object(benchmark_path), approved)
        report["benchmark_path"] = benchmark_path.relative_to(channel_dir).as_posix()
        if args.apply:
            report["applied_path"] = (
                apply_duration_recommendation(channel_dir, report).relative_to(channel_dir).as_posix()
            )
    except DurationDerivationError as exc:
        print(json.dumps({"status": "error", "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
