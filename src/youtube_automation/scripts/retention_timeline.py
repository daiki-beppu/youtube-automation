#!/usr/bin/env python3
"""保存済み retention と video-analyze のタイムラインを照合する CLI。"""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path

from youtube_automation.utils.config import channel_dir
from youtube_automation.utils.exceptions import ConfigError, ValidationError
from youtube_automation.utils.retention_timeline import (
    DEFAULT_DROP_THRESHOLD,
    correlate_retention_timeline,
    parse_iso8601_duration,
    write_retention_report,
)

logger = logging.getLogger(__name__)
_SAFE_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="retention drop と scene / BGM タイムラインを照合")
    parser.add_argument("--video", required=True, help="対象 YouTube video_id")
    parser.add_argument("--slug", help="data/video_analysis/<slug>/ を限定")
    parser.add_argument(
        "--drop-threshold",
        type=float,
        default=DEFAULT_DROP_THRESHOLD,
        help=f"隣接点間の最小低下量 (default: {DEFAULT_DROP_THRESHOLD})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    args = build_parser().parse_args(argv)
    try:
        root = channel_dir()
        analytics_path, analytics = _load_latest_analytics(root / "data")
        retention = _find_retention(analytics, args.video)
        if retention is None:
            return _print_skip(
                args.video,
                "retention 未収集です。`yt-analytics --depth full` を実行してください。",
            )

        analysis_path = _find_video_analysis(root / "data" / "video_analysis", args.video, args.slug)
        if analysis_path is None:
            return _print_skip(
                args.video,
                "/video-analyze 未実行です。`yt-video-analyze` で対象動画を解析してください。",
            )
        analysis = _load_json_object(analysis_path, label="video_analysis")
        duration = _resolve_duration(analytics, analysis, args.video)
        result = correlate_retention_timeline(
            video_id=args.video,
            duration_seconds=duration,
            retention_curve=retention.get("retention_curve") or [],
            video_analysis=analysis,
            threshold=args.drop_threshold,
        )
        json_path, markdown_path = write_retention_report(
            reports_dir=root / "reports",
            result=result,
            analytics_path=analytics_path.relative_to(root),
            analysis_path=analysis_path.relative_to(root),
        )
        print(
            json.dumps(
                {
                    **result,
                    "report_json": str(json_path.relative_to(root)),
                    "report_markdown": str(markdown_path.relative_to(root)),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except (ConfigError, ValidationError) as error:
        logger.error(str(error))
        return 2


def _load_latest_analytics(data_dir: Path) -> tuple[Path, dict]:
    candidates = sorted(data_dir.glob("analytics_data_*.json"))
    if not candidates:
        raise ConfigError(
            "analytics_data_*.json が見つかりません。先に `yt-analytics --depth full` を実行してください。"
        )
    path = candidates[-1]
    return path, _load_json_object(path, label="analytics_data")


def _load_json_object(path: Path, *, label: str) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValidationError(f"{label} JSON を読み込めません: {path}: {error}") from error
    if not isinstance(payload, dict):
        raise ValidationError(f"{label} JSON は object である必要があります: {path}")
    return payload


def _find_retention(analytics: dict, video_id: str) -> dict | None:
    retention = analytics.get("retention")
    if not isinstance(retention, list):
        return None
    return next((item for item in retention if isinstance(item, dict) and item.get("video_id") == video_id), None)


def _find_video_analysis(data_dir: Path, video_id: str, slug: str | None) -> Path | None:
    if slug and (not _SAFE_SLUG.fullmatch(slug) or slug in {".", ".."}):
        raise ValidationError(f"--slug が不正です: {slug!r}")
    candidates = [data_dir / slug / f"{video_id}.json"] if slug else sorted(data_dir.glob(f"*/{video_id}.json"))
    existing = [path for path in candidates if path.is_file()]
    root = data_dir.resolve()
    escaped = [path for path in existing if not path.resolve().is_relative_to(root)]
    if escaped:
        raise ValidationError("channel_dir 外を参照する video_analysis は読み込めません")
    if len(existing) > 1:
        paths = ", ".join(str(path) for path in existing)
        raise ValidationError(f"同じ video_id の video_analysis が複数あります。--slug で指定してください: {paths}")
    return existing[0] if existing else None


def _resolve_duration(analytics: dict, analysis: dict, video_id: str) -> float:
    videos = analytics.get("video_analytics")
    video = videos.get(video_id) if isinstance(videos, dict) else None
    iso_duration = video.get("duration") if isinstance(video, dict) else None
    if isinstance(iso_duration, str) and iso_duration:
        return parse_iso8601_duration(iso_duration)
    raw_seconds = analysis.get("duration_seconds")
    if isinstance(raw_seconds, (int, float)) and not isinstance(raw_seconds, bool) and raw_seconds > 0:
        return float(raw_seconds)
    raise ValidationError(
        f"動画尺がありません: video_analytics[{video_id!r}].duration または video_analysis.duration_seconds が必要です"
    )


def _print_skip(video_id: str, guidance: str) -> int:
    print(json.dumps({"status": "skipped", "video_id": video_id, "reason": guidance}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
