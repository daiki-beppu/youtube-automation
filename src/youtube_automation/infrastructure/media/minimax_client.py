"""MiniMax media API の認証と JSON HTTP 往復を所有する共通 client。"""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlsplit

import requests

from youtube_automation.core.errors import GeneratorError
from youtube_automation.infrastructure.media._http_support import (
    is_safe_https,
    raise_transport_error,
    response_json,
)
from youtube_automation.infrastructure.secrets import get_secret

_BASE_URL = "https://api.minimax.io"


def get_api_key() -> str:
    """既存の secret resolver から MiniMax API key を解決する。"""
    return get_secret("MINIMAX_API_KEY")


def _url_for_path(path: str) -> str:
    if not path.startswith("/") or path.startswith("//") or "://" in path:
        raise GeneratorError("MiniMax API path は / で始まる相対 path である必要があります")
    return f"{_BASE_URL}{path}"


def request_json(
    path: str,
    payload: Mapping[str, object],
    *,
    timeout: float,
) -> dict[str, object]:
    """MiniMax API に JSON を POST し、JSON object response を返す。

    認証情報、request payload、response body、下位例外の文言はエラーへ含めない。
    """
    url = _url_for_path(path)
    api_key = get_api_key()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as error:
        raise_transport_error("MiniMax API request", error)
    return response_json(response, "MiniMax API")


def get_json(
    path: str,
    params: Mapping[str, object],
    *,
    timeout: float,
) -> dict[str, object]:
    """MiniMax API に認証付き GET を送り、JSON object response を返す。"""
    url = _url_for_path(path)
    api_key = get_api_key()
    try:
        response = requests.get(
            url,
            params=params,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        raise_transport_error("MiniMax API request", error)
    return response_json(response, "MiniMax API")


def download_bytes(url: str, *, timeout: float) -> bytes:
    """MiniMax が返した HTTPS download URL から認証情報なしで bytes を取得する。"""
    if not is_safe_https(urlsplit(url)):
        raise GeneratorError("MiniMax download URL は認証情報を含まない HTTPS URL である必要があります")
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as error:
        raise_transport_error("MiniMax file download", error)
    return response.content
