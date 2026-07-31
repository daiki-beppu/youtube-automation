"""Compatibility facade for the channel-target configuration owner."""

import sys

from youtube_automation.configuration import channel_target as _canonical

sys.modules[__name__] = _canonical
