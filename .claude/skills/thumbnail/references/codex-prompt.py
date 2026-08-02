#!/usr/bin/env python3
"""Render the thumbnail Codex prompt from skill-config."""

from __future__ import annotations

import argparse

from youtube_automation.configuration.skills import load_skill_config
from youtube_automation.core.errors import ConfigError
from youtube_automation.infrastructure.media.image_provider.config import build_codex_prompt


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
