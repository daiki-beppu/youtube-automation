"""Compatibility facade for the downstream image-provider import path."""

import importlib
import sys

from youtube_automation.infrastructure.media.image_provider import *  # noqa: F403
from youtube_automation.infrastructure.media.image_provider import prompt_schema as prompt_schema

for _name in ("config", "composition", "prompt_schema", "gemini", "openai", "gemini_cli"):
    _module = importlib.import_module(f"youtube_automation.infrastructure.media.image_provider.{_name}")
    sys.modules[f"{__name__}.{_name}"] = _module
    setattr(sys.modules[__name__], _name, _module)
