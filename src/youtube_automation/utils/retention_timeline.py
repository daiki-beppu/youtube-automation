"""Retention drop と動画解析タイムラインの照合。

保存済みの ``audienceWatchRatio`` を動画内秒へ変換し、``video-analyze`` の
``scene_timeline`` / ``bgm_arc`` に割り当てる。API 呼び出しは行わない。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from itertools import pairwise
from pathlib import Path

from youtube_automation.utils.exceptions import ValidationError

DEFAULT_DROP_THRESHOLD = 0.05
REPORT_DIRNAME = "retention_analysis"

_ISO_DURATION = re.compile(
    r"^P(?:(?P<days>\d+)D)?T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?$"
)
_CLOCK = re.compile(r"(?<!\d)(?:(?P<hours>\d+):)?(?P<minutes>\d{1,2}):(?P<seconds>\d{2})(?!\d)")
_RANGE_START = re.compile(r"^\s*(?P<seconds>\d+(?:\.\d+)?)\s*-")
_SECONDS = re.compile(r"(?<![\d.])(?P<seconds>\d+(?:\.\d+)?)\s*s\b", re.IGNORECASE)


@dataclass(frozen=True)
class TimelineMatch:
    """1 drop 地点に対応する scene / BGM 情報。"""

    elapsed_ratio: float
    elapsed_seconds: float
    watch_ratio: float
    previous_watch_ratio: float
    drop_amount: float
    relative_performance: float | None
    scene: str | None
    scene_start_seconds: float | None
    bgm: str | None
    bgm_start_seconds: float | None
    mapping_status: str


def parse_iso8601_duration(value: str) -> float:
    """YouTube Data API の ISO 8601 duration を秒へ変換する。"""
    match = _ISO_DURATION.fullmatch(value.strip())
    if not match:
        raise ValidationError(f"動画尺が不正です: {value!r}")
    parts = {key: float(raw or 0) for key, raw in match.groupdict().items()}
    seconds = parts["days"] * 86400 + parts["hours"] * 3600 + parts["minutes"] * 60 + parts["seconds"]
    if seconds <= 0:
        raise ValidationError(f"動画尺は正の値である必要があります: {value!r}")
    return seconds


def parse_timestamp(value: object) -> float | None:
    """``M:SS`` / ``H:MM:SS`` / ``15s`` を先頭時刻の秒へ変換する。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value >= 0 else None
    if not isinstance(value, str):
        return None
    range_start = _RANGE_START.search(value)
    if range_start:
        return float(range_start.group("seconds"))
    clock = _CLOCK.search(value)
    if clock:
        hours = int(clock.group("hours") or 0)
        minutes = int(clock.group("minutes"))
        seconds = int(clock.group("seconds"))
        if minutes >= 60 or seconds >= 60:
            return None
        return float(hours * 3600 + minutes * 60 + seconds)
    seconds_match = _SECONDS.search(value)
    if seconds_match:
        return float(seconds_match.group("seconds"))
    return None


def detect_retention_drops(
    retention_curve: list[dict[str, object]], *, threshold: float = DEFAULT_DROP_THRESHOLD
) -> list[dict[str, float | None]]:
    """隣接する retention 点間で ``threshold`` 以上低下した地点を返す。"""
    if not 0 < threshold <= 1:
        raise ValidationError("drop threshold は 0 より大きく 1 以下である必要があります")

    points: list[dict[str, float | None]] = []
    for raw in retention_curve:
        try:
            elapsed = float(raw["elapsed_ratio"])
            watch = float(raw["watch_ratio"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValidationError("retention_curve の elapsed_ratio / watch_ratio が不正です") from error
        if not 0 <= elapsed <= 1 or watch < 0:
            raise ValidationError("retention_curve の値が範囲外です")
        relative = raw.get("relative_performance")
        points.append(
            {
                "elapsed_ratio": elapsed,
                "watch_ratio": watch,
                "relative_performance": float(relative) if relative is not None else None,
            }
        )

    points.sort(key=lambda point: float(point["elapsed_ratio"] or 0))
    drops: list[dict[str, float | None]] = []
    for previous, current in pairwise(points):
        drop_amount = float(previous["watch_ratio"] or 0) - float(current["watch_ratio"] or 0)
        if drop_amount + 1e-12 < threshold:
            continue
        drops.append(
            {
                **current,
                "previous_watch_ratio": previous["watch_ratio"],
                "drop_amount": drop_amount,
            }
        )
    return drops


def correlate_retention_timeline(
    *,
    video_id: str,
    duration_seconds: float,
    retention_curve: list[dict[str, object]],
    video_analysis: dict[str, object],
    threshold: float = DEFAULT_DROP_THRESHOLD,
) -> dict[str, object]:
    """drop 地点を scene / BGM タイムラインへ割り当てる。"""
    if duration_seconds <= 0:
        raise ValidationError("duration_seconds は正の値である必要があります")
    if not isinstance(video_analysis, dict):
        raise ValidationError("video_analysis JSON は object である必要があります")

    scenes = _scene_markers(video_analysis.get("scene_timeline"))
    bgm = _bgm_markers(video_analysis.get("bgm_arc"))
    window = _optional_positive_number(video_analysis.get("analysis_window_sec"))
    matches: list[TimelineMatch] = []
    for drop in detect_retention_drops(retention_curve, threshold=threshold):
        seconds = float(drop["elapsed_ratio"] or 0) * duration_seconds
        outside_window = window is not None and seconds > window
        scene = None if outside_window else _marker_at(scenes, seconds)
        music = None if outside_window else _marker_at(bgm, seconds)
        mapping_status = _mapping_status(outside_window=outside_window, scene=scene, music=music)
        matches.append(
            TimelineMatch(
                elapsed_ratio=float(drop["elapsed_ratio"] or 0),
                elapsed_seconds=round(seconds, 3),
                watch_ratio=float(drop["watch_ratio"] or 0),
                previous_watch_ratio=float(drop["previous_watch_ratio"] or 0),
                drop_amount=round(float(drop["drop_amount"] or 0), 6),
                relative_performance=drop["relative_performance"],
                scene=scene[1] if scene else None,
                scene_start_seconds=scene[0] if scene else None,
                bgm=music[1] if music else None,
                bgm_start_seconds=music[0] if music else None,
                mapping_status=mapping_status,
            )
        )

    return {
        "status": "ok",
        "video_id": video_id,
        "duration_seconds": duration_seconds,
        "analysis_window_sec": window,
        "drop_threshold": threshold,
        "drop_count": len(matches),
        "drops": [asdict(match) for match in matches],
    }


def render_retention_report(result: dict[str, object], *, analytics_path: Path, analysis_path: Path) -> str:
    """照合結果を postmortem から引用しやすい Markdown にする。"""
    window = _format_seconds(result["analysis_window_sec"]) if result["analysis_window_sec"] else "動画全体"
    lines = [
        f"# Retention drop 照合 — {result['video_id']}",
        "",
        f"- drop threshold: {result['drop_threshold']:.1%}",
        f"- video duration: {_format_seconds(result['duration_seconds'])}",
        f"- analysis window: {window}",
        f"- retention source: `{analytics_path}`",
        f"- video analysis source: `{analysis_path}`",
        "",
        "| drop 地点 | 維持率変化 | scene | BGM / 曲 | 照合状態 |",
        "|---|---:|---|---|---|",
    ]
    for drop in result["drops"]:
        scene = _escape_table(drop["scene"] or "該当情報なし")
        bgm = _escape_table(drop["bgm"] or "該当情報なし")
        change = f"{drop['previous_watch_ratio']:.1%} → {drop['watch_ratio']:.1%} (-{drop['drop_amount']:.1%})"
        location = f"{_format_seconds(drop['elapsed_seconds'])} ({drop['elapsed_ratio']:.1%})"
        lines.append(f"| {location} | {change} | {scene} | {bgm} | {drop['mapping_status']} |")
    if not result["drops"]:
        lines.append("| — | 閾値以上の drop なし | — | — | matched |")
    lines.extend(
        [
            "",
            "> `outside_analysis_window` は `/video-analyze` の冒頭クリップ窓外です。scene / BGM を推測していません。",
            "",
        ]
    )
    return "\n".join(lines)


def write_retention_report(
    *, reports_dir: Path, result: dict[str, object], analytics_path: Path, analysis_path: Path
) -> tuple[Path, Path]:
    """JSON と Markdown の照合レポートを書き出す。"""
    output_dir = reports_dir / REPORT_DIRNAME
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = str(result["video_id"])
    json_path = output_dir / f"{stem}.json"
    markdown_path = output_dir / f"{stem}.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(
        render_retention_report(result, analytics_path=analytics_path, analysis_path=analysis_path),
        encoding="utf-8",
    )
    return json_path, markdown_path


def _scene_markers(raw: object) -> list[tuple[float, str]]:
    if not isinstance(raw, list):
        return []
    markers: list[tuple[float, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        start = parse_timestamp(item.get("start"))
        if start is None:
            continue
        label = item.get("summary") or item.get("scene") or item.get("label")
        if label:
            markers.append((start, str(label)))
    return sorted(markers)


def _bgm_markers(raw: object) -> list[tuple[float, str]]:
    if not isinstance(raw, dict):
        return []
    segments = raw.get("segments")
    markers: list[tuple[float, str]] = []
    if isinstance(segments, list):
        for index, item in enumerate(segments, 1):
            if not isinstance(item, dict):
                continue
            start = parse_timestamp(item.get("start"))
            if start is None:
                continue
            label = item.get("track") or item.get("title") or item.get("name") or item.get("label")
            description = item.get("description") or item.get("energy")
            text = str(label or f"track {index}")
            if description:
                text = f"{text}: {description}"
            markers.append((start, text))
    if markers:
        return sorted(markers)

    for phase in ("intro", "peak", "outro"):
        value = raw.get(phase)
        start = parse_timestamp(value)
        if start is not None:
            markers.append((start, f"{phase}: {value}"))
    return sorted(markers)


def _marker_at(markers: list[tuple[float, str]], seconds: float) -> tuple[float, str] | None:
    candidates = [marker for marker in markers if marker[0] <= seconds]
    return candidates[-1] if candidates else None


def _mapping_status(*, outside_window: bool, scene: tuple[float, str] | None, music: tuple[float, str] | None) -> str:
    if outside_window:
        return "outside_analysis_window"
    if scene and music:
        return "matched"
    if scene:
        return "scene_only"
    if music:
        return "bgm_only"
    return "unmatched"


def _optional_positive_number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _format_seconds(value: float) -> str:
    total = round(value)
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
