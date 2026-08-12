"""Compatibility module alias for the Gemini image provider."""

import sys

from youtube_automation.infrastructure.media.image_provider import gemini as _canonical

sys.modules[__name__] = _canonical
