"""Instance-scoped YouTube client cache tests."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from youtube_automation.infrastructure.errors import ValidationError
from youtube_automation.infrastructure.google.youtube import YouTubeClients, validate_youtube_response_items


def _handler(*, youtube=None):
    handler = MagicMock()
    handler.get_youtube_service.return_value = youtube
    handler.authenticate.return_value = SimpleNamespace(kind="credentials")
    return handler


def test_inject_handler_resolves_full_service():
    handler = _handler(youtube="injected_youtube")

    clients = YouTubeClients(full_handler=handler)

    assert clients.youtube == "injected_youtube"
    handler.get_youtube_service.assert_called_once_with()


def test_full_and_readonly_services_are_cached_independently():
    full_handler = _handler(youtube="full")
    readonly_handler = _handler(youtube="readonly")
    clients = YouTubeClients(full_handler=full_handler, readonly_handler=readonly_handler)

    assert clients.youtube is clients.youtube
    assert clients.youtube_readonly is clients.youtube_readonly
    assert clients.youtube == "full"
    assert clients.youtube_readonly == "readonly"
    full_handler.get_youtube_service.assert_called_once_with()
    readonly_handler.get_youtube_service.assert_called_once_with()


def test_reset_clears_only_this_instance_cache():
    first_handler = _handler(youtube="first")
    second_handler = _handler(youtube="second")
    first = YouTubeClients(full_handler=first_handler)
    second = YouTubeClients(full_handler=second_handler)

    assert first.youtube == "first"
    assert second.youtube == "second"
    first.reset()
    assert first.youtube == "first"
    assert second.youtube == "second"
    assert first_handler.get_youtube_service.call_count == 2
    second_handler.get_youtube_service.assert_called_once_with()


@pytest.mark.parametrize("response", [None, {"items": None}, {"items": {}}])
def test_validate_youtube_response_items_rejects_invalid_shapes(response):
    with pytest.raises(ValidationError):
        validate_youtube_response_items(response, "playlistItems.list")


@pytest.mark.parametrize(
    ("response", "expected"),
    [({"items": []}, []), ({"items": [{"id": "item-1"}]}, [{"id": "item-1"}]), ({}, [])],
)
def test_validate_youtube_response_items_returns_valid_items(response, expected):
    assert validate_youtube_response_items(response, "playlistItems.list") == expected
