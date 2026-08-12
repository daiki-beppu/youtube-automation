"""Compatibility module alias for image-provider configuration helpers."""

import sys

from youtube_automation.infrastructure.media.image_provider import config as _canonical

sys.modules[__name__] = _canonical
