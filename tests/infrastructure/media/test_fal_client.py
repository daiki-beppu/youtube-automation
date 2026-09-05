"""fal.ai HTTP client の契約テスト。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from youtube_automation.core.errors import GeneratorError
from youtube_automation.infrastructure.media import fal_client


def _json_response(body: object) -> Mock:
    response = Mock(spec=requests.Response)
    response.status_code = 200
    response.json.return_value = body
    return response


def test_submit_uses_key_auth_and_queue_host(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _json_response({"request_id": "request-1"})
    post = Mock(return_value=response)
    monkeypatch.setattr(fal_client, "get_api_key", Mock(return_value="fal-secret"))
    monkeypatch.setattr(fal_client.requests, "post", post)

    assert fal_client.submit("minimax/h3/image-to-video", {"prompt": "loop"}, timeout=30) == {"request_id": "request-1"}
    post.assert_called_once_with(
        "https://queue.fal.run/minimax/h3/image-to-video",
        json={"prompt": "loop"},
        headers={"Authorization": "Key fal-secret", "Content-Type": "application/json"},
        timeout=30,
    )


@pytest.mark.parametrize("path", ["/model", "https://example.com/model", "//example.com/model", ""])
def test_submit_rejects_non_relative_endpoint(path: str, monkeypatch: pytest.MonkeyPatch) -> None:
    post = Mock()
    monkeypatch.setattr(fal_client.requests, "post", post)
    with pytest.raises(GeneratorError, match="path"):
        fal_client.submit(path, {}, timeout=1)
    post.assert_not_called()


@pytest.mark.parametrize(
    "url",
    [
        "http://queue.fal.run/request/1",
        "https://example.com/request/1",
        "https://queue.fal.run.evil.example/request/1",
        "https://user:pass@fal.run/request/1",
    ],
)
def test_get_url_rejects_unsafe_url(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    get = Mock()
    monkeypatch.setattr(fal_client.requests, "get", get)
    with pytest.raises(GeneratorError):
        fal_client.get_url(url, timeout=1)
    get.assert_not_called()


@pytest.mark.parametrize(
    "url",
    [
        "https://queue.fal.run/requests/1/status",
        "https://fal.run/model/requests/1",
        "https://rest.alpha.fal.ai/requests/1",
        "https://v3.fal.media/files/video.mp4",
    ],
)
def test_get_url_accepts_allowlisted_hosts(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    get = Mock(return_value=_json_response({"status": "COMPLETED"}))
    monkeypatch.setattr(fal_client, "get_api_key", Mock(return_value="key"))
    monkeypatch.setattr(fal_client.requests, "get", get)
    assert fal_client.get_url(url, timeout=4) == {"status": "COMPLETED"}
    get.assert_called_once_with(url, headers={"Authorization": "Key key"}, timeout=4, allow_redirects=False)


def test_download_returns_bytes_without_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    response = Mock(spec=requests.Response)
    response.status_code = 200
    response.content = b"video"
    get = Mock(return_value=response)
    monkeypatch.setattr(fal_client.requests, "get", get)
    assert fal_client.download("https://cdn.fal.media/video.mp4", timeout=8) == b"video"
    get.assert_called_once_with("https://cdn.fal.media/video.mp4", timeout=8, allow_redirects=False)


def test_errors_do_not_expose_api_key_or_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "secret-must-not-leak"
    response = Mock(spec=requests.Response)
    response.status_code = 200
    response.status_code = 422
    response.raise_for_status.side_effect = requests.HTTPError(secret, response=response)
    monkeypatch.setattr(fal_client, "get_api_key", Mock(return_value=secret))
    monkeypatch.setattr(fal_client.requests, "post", Mock(return_value=response))
    with pytest.raises(GeneratorError) as exc_info:
        fal_client.submit("model/run", {"prompt": secret}, timeout=1)
    assert secret not in str(exc_info.value)
    assert "status=422" in str(exc_info.value)


def test_upload_file_initiates_then_puts_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "input.png"
    source.write_bytes(b"png-data")
    initiate = _json_response(
        {"upload_url": "https://signed-storage.example/put", "file_url": "https://cdn.fal.media/input.png"}
    )
    put_response = Mock(spec=requests.Response)
    put_response.status_code = 200
    post = Mock(return_value=initiate)
    put = Mock(return_value=put_response)
    monkeypatch.setattr(fal_client, "get_api_key", Mock(return_value="fal-secret"))
    monkeypatch.setattr(fal_client.requests, "post", post)
    monkeypatch.setattr(fal_client.requests, "put", put)

    assert fal_client.upload_file(source, timeout=20) == "https://cdn.fal.media/input.png"
    post.assert_called_once_with(
        "https://rest.alpha.fal.ai/storage/upload/initiate",
        params={"storage_type": "fal-cdn-v3"},
        json={"file_name": "input.png", "content_type": "image/png"},
        headers={
            "Authorization": "Key fal-secret",
            "Content-Type": "application/json",
            "X-Fal-Object-Lifecycle-Preference": '{"expiration_duration_seconds": 86400}',
        },
        timeout=20,
    )
    put.assert_called_once_with(
        "https://signed-storage.example/put",
        data=b"png-data",
        headers={"Content-Type": "image/png"},
        timeout=20,
    )


@pytest.mark.parametrize("operation", ["get_url", "download"])
@pytest.mark.parametrize("target", ["http://outside.invalid/private", "https://outside.invalid/private"])
def test_redirect_is_rejected_without_following(monkeypatch: pytest.MonkeyPatch, operation: str, target: str) -> None:
    class RedirectAdapter(requests.adapters.BaseAdapter):
        def __init__(self) -> None:
            self.urls: list[str] = []

        def send(self, request, **kwargs):
            self.urls.append(request.url)
            response = requests.Response()
            response.request = request
            response.url = request.url
            response.status_code = 302 if len(self.urls) == 1 else 200
            response.headers["Location"] = target
            response._content = b"{}"
            return response

        def close(self) -> None:
            pass

    adapter = RedirectAdapter()
    with requests.Session() as session:
        session.trust_env = False
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        monkeypatch.setattr(fal_client.requests, "get", session.get)
        monkeypatch.setattr(fal_client, "get_api_key", lambda: "test-key")
        with pytest.raises(GeneratorError, match="redirect"):
            getattr(fal_client, operation)("https://v3.fal.media/output", timeout=1)
    assert adapter.urls == ["https://v3.fal.media/output"]
