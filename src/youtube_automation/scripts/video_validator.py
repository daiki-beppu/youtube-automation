"""ffprobe adapter and command entry point for video validation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

from youtube_automation.domains.media.video_validator import VideoValidator


def read_video_metadata(video_path: Path) -> Optional[dict]:
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        "--",
        str(video_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        video_stream = next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"), None)
        if not video_stream:
            return None
        format_info = data.get("format", {})
        return {
            "duration": float(format_info.get("duration", 0)),
            "resolution": f"{video_stream.get('width', 0)}x{video_stream.get('height', 0)}",
            "codec": video_stream.get("codec_name", "unknown"),
            "bitrate": int(format_info["bit_rate"]) if format_info.get("bit_rate") else None,
            "fps": _parse_fps(video_stream.get("r_frame_rate", "0/1")),
        }
    except (subprocess.CalledProcessError, json.JSONDecodeError, OSError, ValueError) as exc:
        print(f"ffprobe エラー {video_path.name}: {exc}", file=sys.stderr)
        return None


def _parse_fps(value: str) -> float:
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        return float(numerator) / float(denominator)
    return float(value)


def main() -> int:
    if len(sys.argv) != 2:
        print("使用法: python video_validator.py <collection_directory>")
        return 1
    validator = VideoValidator(read_video_metadata)
    results = validator.validate_collection(sys.argv[1])
    print(validator.generate_validation_report(results))
    return 1 if results["summary"]["invalid"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
