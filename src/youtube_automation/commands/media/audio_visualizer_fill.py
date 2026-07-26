"""Audio visualizer の gradient / conical fill を実行時生成する。"""

from __future__ import annotations

import argparse
from pathlib import Path

from youtube_automation.utils.audio_visualizer_fill import create_fill_asset


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--type", required=True, choices=("solid", "gradient", "rainbow", "conical"))
    parser.add_argument("--size", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--color", default="white")
    parser.add_argument("--top", default="0xA9CBF0")
    parser.add_argument("--bottom", default="0x3A5696")
    args = parser.parse_args()
    try:
        effective_type = create_fill_asset(
            args.type, args.size, args.output, color=args.color, top=args.top, bottom=args.bottom
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(effective_type)


if __name__ == "__main__":
    main()
