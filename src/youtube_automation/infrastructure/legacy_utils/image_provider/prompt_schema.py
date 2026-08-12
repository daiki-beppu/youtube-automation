"""Compatibility module alias for the shared image prompt schema."""

import sys

from youtube_automation.infrastructure.media.image_provider import prompt_schema as _canonical

sys.modules[__name__] = _canonical
