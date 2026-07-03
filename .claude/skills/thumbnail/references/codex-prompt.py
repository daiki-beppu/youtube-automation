#!/usr/bin/env python3
"""Render the thumbnail Codex prompt from skill-config."""

from __future__ import annotations

import argparse

from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.image_provider.config import build_codex_prompt
from youtube_automation.utils.skill_config import load_skill_config


def main() -> int:
    parser = argparse.ArgumentParser(description="Render image_generation.codex.default_prompt_template")
    parser.add_argument("title", help="thumbnail title to inject into {title}")
    args = parser.parse_args()

    try:
        print(build_codex_prompt(load_skill_config("thumbnail"), args.title))
    except ConfigError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
