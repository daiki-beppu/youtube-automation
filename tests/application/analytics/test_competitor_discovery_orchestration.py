from unittest.mock import Mock, call

import pytest

from youtube_automation.application.analytics import competitor_discovery
from youtube_automation.core.errors import ConfigError, YouTubeAPIError
from youtube_automation.infrastructure.analytics.competitor_discovery import SearchCacheMode
from youtube_automation.infrastructure.analytics.competitor_scoring import DiscoveryParams


@pytest.mark.parametrize("search_fails", [False, True])
def test_config_exclusions_are_loaded_only_after_all_searches(
    monkeypatch: pytest.MonkeyPatch, search_fails: bool
) -> None:
    events = Mock()
    events.search.return_value = {}
    if search_fails:
        events.search.side_effect = YouTubeAPIError("search failed")
    events.config.side_effect = ConfigError("config failed")
    monkeypatch.setattr(competitor_discovery.discovery_io, "_cached_search_channels", events.search)
    monkeypatch.setattr(competitor_discovery, "load_config", events.config)
    params = DiscoveryParams(("first", "second"), 1, 100, 30, 10, 20)
    youtube = Mock()

    with pytest.raises(YouTubeAPIError if search_fails else ConfigError):
        competitor_discovery.discover_competitors(youtube, params)

    expected = [call.search(youtube, "first", 20, SearchCacheMode.USE)]
    if not search_fails:
        expected.extend([call.search(youtube, "second", 20, SearchCacheMode.USE), call.config()])
    assert events.mock_calls == expected
    youtube.assert_not_called()
    assert youtube.mock_calls == []
