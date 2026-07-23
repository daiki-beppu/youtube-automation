#!/usr/bin/env python3
"""Apply the opt-in thumbnail.jpg -> main.jpg shared-background contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from youtube_automation.utils.exceptions import ConfigError, ValidationError
from youtube_automation.utils.skill_config import load_skill_config


def _textless_enabled(config: Mapping[str, object]) -> bool:
    textless = config.get("textless", {})
    if not isinstance(textless, Mapping):
        raise ConfigError("thumbnail.textless は mapping である必要があります")
    enabled = textless.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ConfigError("thumbnail.textless.enabled は boolean で指定してください")
    return enabled


def _sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def share_thumbnail_as_main(collection_dir: Path, *, enabled: bool) -> dict[str, object]:
    """Copy the approved thumbnail atomically and verify identical content."""
    assets_dir = collection_dir.resolve() / "10-assets"
    thumbnail = assets_dir / "thumbnail.jpg"
    main_jpg = assets_dir / "main.jpg"
    main_png = assets_dir / "main.png"

    if enabled:
        return {
            "status": "SKIP",
            "reason": "textless.enabled=true",
            "source": str(thumbnail),
            "destination": str(main_jpg),
        }
    if not thumbnail.is_file() or thumbnail.is_symlink():
        raise ValidationError(f"承認済み通常ファイルが必要です: {thumbnail}")

    assets_dir.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=assets_dir,
            prefix=".main-shared-",
            suffix=".jpg",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        shutil.copyfile(thumbnail, temporary_path)
        source_digest = _sha256(thumbnail)
        copied_digest = _sha256(temporary_path)
        if source_digest != copied_digest:
            raise ValidationError("thumbnail.jpg と一時コピーの SHA-256 が一致しません")
        os.replace(temporary_path, main_jpg)
        temporary_path = None
        if main_png.exists() or main_png.is_symlink():
            main_png.unlink()
        if _sha256(main_jpg) != source_digest:
            raise ValidationError("確定後の main.jpg が thumbnail.jpg と一致しません")
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    return {
        "status": "SHARED",
        "source": str(thumbnail),
        "destination": str(main_jpg),
        "sha256": source_digest,
        "removed_main_png": not main_png.exists(),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection", type=Path, help="collection directory")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        config = load_skill_config("thumbnail")
        result = share_thumbnail_as_main(args.collection, enabled=_textless_enabled(config))
    except (ConfigError, OSError, ValidationError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
