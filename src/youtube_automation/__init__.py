"""YouTube channels automation toolkit."""

from importlib.metadata import PackageNotFoundError, version

from youtube_automation.cli_stdio import configure_utf8_stdio

configure_utf8_stdio()

try:
    __version__ = version("youtube-channels-automation")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"
