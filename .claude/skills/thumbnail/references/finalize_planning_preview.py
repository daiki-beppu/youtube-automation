#!/usr/bin/env python3
"""Finalize an adopted planning preview as the upload thumbnail."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from PIL import Image

from youtube_automation.core.errors import ValidationError

_JPEG_QUALITY = 100


def finalize_planning_preview(collection_dir: Path) -> dict[str, str]:
    """Convert planning-preview.png to thumbnail.jpg without changing composition."""
    assets_dir = collection_dir.resolve() / "10-assets"
    source = assets_dir / "planning-preview.png"
    destination = assets_dir / "thumbnail.jpg"

    if source.is_symlink():
        raise ValidationError(f"planning preview は通常ファイルである必要があります: {source}")
    if not source.exists():
        return {"status": "MISSING", "source": str(source)}
    if not source.is_file():
        raise ValidationError(f"planning preview は通常ファイルである必要があります: {source}")

    temporary_path: Path | None = None
    try:
        file_descriptor, temporary_name = tempfile.mkstemp(
            dir=assets_dir,
            prefix=".thumbnail-preview-",
            suffix=".jpg",
        )
        os.close(file_descriptor)
        temporary_path = Path(temporary_name)

        with Image.open(source) as opened:
            opened.load()
            source_size = opened.size
            opened.convert("RGB").save(
                temporary_path,
                format="JPEG",
                quality=_JPEG_QUALITY,
                subsampling=0,
            )

        with Image.open(temporary_path) as converted:
            converted.load()
            if converted.format != "JPEG" or converted.size != source_size:
                raise ValidationError("planning preview の JPEG 形式変換を検証できませんでした")

        os.replace(temporary_path, destination)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    return {
        "status": "FINALIZED",
        "source": str(source),
        "destination": str(destination),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="planning-preview.png を AI 再生成せず thumbnail.jpg に確定します",
    )
    parser.add_argument("collection_dir", type=Path, help="対象 collection directory")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = finalize_planning_preview(args.collection_dir)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
