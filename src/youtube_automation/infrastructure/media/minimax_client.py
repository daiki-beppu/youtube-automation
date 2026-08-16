"""MiniMax media API の認証と JSON HTTP 往復を所有する共通 client。"""

from __future__ import annotations

from collections.abc import Mapping

import requests

from youtube_automation.core.errors import GeneratorError
from youtube_automation.infrastructure.secrets import get_secret

_BASE_URL = "https://api.minimax.io"


def get_api_key() -> str:
    """既存の secret resolver から MiniMax API key を解決する。"""
    return get_secret("MINIMAX_API_KEY")


def _url_for_path(path: str) -> str:
    if not path.startswith("/") or path.startswith("//") or "://" in path:
        raise GeneratorError("MiniMax API path は / で始まる相対 path である必要があります")
    return f"{_BASE_URL}{path}"


def _http_status(response: requests.Response | None) -> int | None:
    if response is None:
        return None
    status_code = response.status_code
    return status_code if isinstance(status_code, int) else None


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
    except requests.Timeout:
        raise GeneratorError("MiniMax API request が timeout しました") from None
    except requests.HTTPError as error:
        status = _http_status(error.response)
        detail = f" (status={status})" if status is not None else ""
        raise GeneratorError(f"MiniMax API HTTP error{detail}") from None
    except requests.RequestException:
        raise GeneratorError("MiniMax API request に失敗しました") from None

    try:
        body = response.json()
    except requests.exceptions.JSONDecodeError:
        raise GeneratorError("MiniMax API response を JSON として解釈できません") from None
    if not isinstance(body, dict):
        raise GeneratorError("MiniMax API response は JSON object である必要があります")
    return body
