"""Compatibility module alias for the OpenAI image provider."""

import sys

from youtube_automation.infrastructure.media.image_provider import openai as _canonical

sys.modules[__name__] = _canonical
