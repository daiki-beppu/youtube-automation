"""Subprocess boundary for media processing."""

import subprocess
import tempfile
from pathlib import Path


def compress_image(source: Path, qualities: list[int], max_bytes: int) -> Path:
    output = Path(tempfile.NamedTemporaryFile(suffix=".jpg", delete=False).name)
    for quality in qualities:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(source.resolve()), "-qscale:v", str(quality), str(output)],
            capture_output=True,
        )
        if output.exists() and output.stat().st_size <= max_bytes:
            return output
    output.unlink(missing_ok=True)
    return source
