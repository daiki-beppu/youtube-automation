"""MiniMax 共通 HTTP クライアントの契約テスト。"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
import requests

from youtube_automation.core.errors import GeneratorError
from youtube_automation.infrastructure.media import minimax_client


def test_get_api_key_uses_registered_secret_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    get_secret = Mock(return_value="resolved-key")
    monkeypatch.setattr(minimax_client, "get_secret", get_secret)

    assert minimax_client.get_api_key() == "resolved-key"
    get_secret.assert_called_once_with("MINIMAX_API_KEY")


def test_request_json_posts_object_with_bearer_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    response = Mock(spec=requests.Response)
    response.json.return_value = {"trace_id": "trace-1", "data": {"task_id": "task-1"}}
    post = Mock(return_value=response)
    monkeypatch.setattr(minimax_client, "get_api_key", Mock(return_value="minimax-secret"))
    monkeypatch.setattr(minimax_client.requests, "post", post)
    payload = {"model": "music-2.6", "prompt": "ambient"}

    result = minimax_client.request_json("/v1/music_generation", payload, timeout=30)

    assert result == {"trace_id": "trace-1", "data": {"task_id": "task-1"}}
    post.assert_called_once_with(
        "https://api.minimax.io/v1/music_generation",
        json=payload,
        headers={
            "Authorization": "Bearer minimax-secret",
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    response.raise_for_status.assert_called_once_with()


@pytest.mark.parametrize("status_code", [400, 503])
def test_request_json_converts_http_error_without_exposing_secret(
    status_code: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "minimax-secret-that-must-not-leak"
    response = Mock(spec=requests.Response)
    response.status_code = status_code
    response.raise_for_status.side_effect = requests.HTTPError(
        f"failure with {secret}",
        response=response,
    )
    monkeypatch.setattr(minimax_client, "get_api_key", Mock(return_value=secret))
    monkeypatch.setattr(minimax_client.requests, "post", Mock(return_value=response))

    with pytest.raises(GeneratorError) as exc_info:
        minimax_client.request_json("/v1/music_generation", {"prompt": secret}, timeout=30)

    assert f"status={status_code}" in str(exc_info.value)
    assert secret not in str(exc_info.value)
    assert not isinstance(exc_info.value, requests.RequestException)


def test_request_json_converts_timeout_without_exposing_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "minimax-secret-that-must-not-leak"
    monkeypatch.setattr(minimax_client, "get_api_key", Mock(return_value=secret))
    monkeypatch.setattr(
        minimax_client.requests,
        "post",
        Mock(side_effect=requests.Timeout(f"timeout with {secret}")),
    )

    with pytest.raises(GeneratorError) as exc_info:
        minimax_client.request_json("/v1/video_generation", {"prompt": secret}, timeout=12)

    assert "timeout" in str(exc_info.value).lower()
    assert secret not in str(exc_info.value)
    assert not isinstance(exc_info.value, requests.RequestException)


def test_request_json_converts_json_decode_error_without_exposing_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "minimax-secret-that-must-not-leak"
    response = Mock(spec=requests.Response)
    response.json.side_effect = requests.exceptions.JSONDecodeError("invalid", secret, 0)
    monkeypatch.setattr(minimax_client, "get_api_key", Mock(return_value=secret))
    monkeypatch.setattr(minimax_client.requests, "post", Mock(return_value=response))

    with pytest.raises(GeneratorError) as exc_info:
        minimax_client.request_json("/v1/music_generation", {"prompt": secret}, timeout=30)

    assert "JSON" in str(exc_info.value)
    assert secret not in str(exc_info.value)


@pytest.mark.parametrize("body", [[], "text", 1, None])
def test_request_json_rejects_non_object_response(body: object, monkeypatch: pytest.MonkeyPatch) -> None:
    response = Mock(spec=requests.Response)
    response.json.return_value = body
    monkeypatch.setattr(minimax_client, "get_api_key", Mock(return_value="minimax-secret"))
    monkeypatch.setattr(minimax_client.requests, "post", Mock(return_value=response))

    with pytest.raises(GeneratorError, match="JSON object"):
        minimax_client.request_json("/v1/music_generation", {}, timeout=30)


def test_request_json_rejects_external_url_before_resolving_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_api_key = Mock(side_effect=AssertionError("secret must not be resolved"))
    post = Mock()
    monkeypatch.setattr(minimax_client, "get_api_key", get_api_key)
    monkeypatch.setattr(minimax_client.requests, "post", post)

    with pytest.raises(GeneratorError, match="path"):
        minimax_client.request_json("https://example.com/steal", {}, timeout=30)

    get_api_key.assert_not_called()
    post.assert_not_called()
