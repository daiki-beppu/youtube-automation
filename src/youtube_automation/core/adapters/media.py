"""Media adapter boundary for domain modules."""

from youtube_automation.domains.analytics.video_analysis import VIDEO_ANALYSIS_DIRNAME
from youtube_automation.domains.collections.paths import CollectionPaths
from youtube_automation.infrastructure.media.probe import probe_duration

__all__ = ["VIDEO_ANALYSIS_DIRNAME", "CollectionPaths", "probe_duration"]
