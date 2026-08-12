"""Compatibility module alias for image-provider composition helpers."""

import sys

from youtube_automation.infrastructure.media.image_provider import composition as _canonical

sys.modules[__name__] = _canonical
