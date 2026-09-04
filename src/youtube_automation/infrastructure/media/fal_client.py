"""fal.ai queue / storage API の認証と HTTP 往復を所有する client。"""

from __future__ import annotations

import json
import mimetypes
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

import requests

from youtube_automation.core.errors import GeneratorError
from youtube_automation.infrastructure.secrets import get_secret

_QUEUE_BASE_URL = "https://queue.fal.run"
_STORAGE_INITIATE_URL = "https://rest.alpha.fal.ai/storage/upload/initiate"
_EXACT_HOSTS = frozenset({"queue.fal.run", "fal.run", "rest.alpha.fal.ai"})
_LIFECYCLE_PREFERENCE = json.dumps({"expiration_duration_seconds": 86400})


def get_api_key() -> str:
    """既存の secret resolver から fal API key を解決する。"""
    return get_secret("FAL_KEY")


def _authorization_headers(*, json_content: bool = False) -> dict[str, str]:
    headers = {"Authorization": f"Key {get_api_key()}"}
    if json_content:
        headers["Content-Type"] = "application/json"
    return headers


def _queue_url(path: str) -> str:
    if not path or path.startswith("/") or "://" in path:
        raise GeneratorError("fal API path は / を含まない相対 path である必要があります")
    return f"{_QUEUE_BASE_URL}/{path}"


def _validated_url(url: str) -> str:
    parsed = urlsplit(url)
    host = parsed.hostname
    allowed = host in _EXACT_HOSTS or (host is not None and host.endswith(".fal.media"))
    if parsed.scheme != "https" or not allowed or parsed.username is not None or parsed.password is not None:
        raise GeneratorError("fal URL は許可された host の認証情報を含まない HTTPS URL である必要があります")
    return url


def _status(response: requests.Response | None) -> int | None:
    if response is None:
        return None
    return response.status_code if isinstance(response.status_code, int) else None


def _raise_transport_error(operation: str, error: requests.RequestException) -> None:
    if isinstance(error, requests.Timeout):
        raise GeneratorError(f"fal {operation} が timeout しました") from None
    if isinstance(error, requests.HTTPError):
        status = _status(error.response)
        detail = f" (status={status})" if status is not None else ""
        raise GeneratorError(f"fal {operation} HTTP error{detail}") from None
    raise GeneratorError(f"fal {operation} に失敗しました") from None


def _response_json(response: requests.Response, operation: str) -> dict[str, object]:
    try:
        body = response.json()
    except requests.exceptions.JSONDecodeError:
        raise GeneratorError(f"fal {operation} response を JSON として解釈できません") from None
    if not isinstance(body, dict):
        raise GeneratorError(f"fal {operation} response は JSON object である必要があります")
    return body


def submit(path: str, payload: Mapping[str, object], *, timeout: float) -> dict[str, object]:
    """queue endpoint へ job を submit する。"""
    url = _queue_url(path)
    try:
        response = requests.post(
            url,
            json=payload,
            headers=_authorization_headers(json_content=True),
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        _raise_transport_error("submit", error)
    return _response_json(response, "submit")


def get_url(url: str, *, timeout: float) -> dict[str, object]:
    """allowlist 済みの fal URL へ認証付き GET を送る。"""
    safe_url = _validated_url(url)
    try:
        response = requests.get(safe_url, headers=_authorization_headers(), timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as error:
        _raise_transport_error("GET", error)
    return _response_json(response, "GET")


def download(url: str, *, timeout: float) -> bytes:
    """allowlist 済みの fal media URL から認証情報なしで bytes を取得する。"""
    safe_url = _validated_url(url)
    try:
        response = requests.get(safe_url, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as error:
        _raise_transport_error("download", error)
    return response.content


def upload_file(path: Path, *, timeout: float) -> str:
    """fal storage の initiate / signed PUT を実行し公開 ``file_url`` を返す。"""
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    headers = {
        **_authorization_headers(json_content=True),
        "X-Fal-Object-Lifecycle-Preference": _LIFECYCLE_PREFERENCE,
    }
    try:
        response = requests.post(
            _STORAGE_INITIATE_URL,
            params={"storage_type": "fal-cdn-v3"},
            json={"file_name": path.name, "content_type": content_type},
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        _raise_transport_error("storage initiate", error)

    body = _response_json(response, "storage initiate")
    upload_url = body.get("upload_url")
    file_url = body.get("file_url")
    if not isinstance(upload_url, str) or not isinstance(file_url, str):
        raise GeneratorError("fal storage initiate response に必要な URL がありません")
    _validated_url(file_url)
    parsed_upload = urlsplit(upload_url)
    if parsed_upload.scheme != "https" or not parsed_upload.netloc or parsed_upload.username or parsed_upload.password:
        raise GeneratorError("fal storage upload URL が安全な HTTPS URL ではありません")
    try:
        data = path.read_bytes()
    except OSError:
        raise GeneratorError("fal upload file を読み込めません") from None
    try:
        put_response = requests.put(
            upload_url,
            data=data,
            headers={"Content-Type": content_type},
            timeout=timeout,
        )
        put_response.raise_for_status()
    except requests.RequestException as error:
        _raise_transport_error("storage upload", error)
    return file_url
