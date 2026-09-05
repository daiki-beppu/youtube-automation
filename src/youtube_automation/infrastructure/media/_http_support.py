"""``infrastructure/media`` の HTTP client が共有する低レベルヘルパー。

media client 共通の流儀 — エラー文言に secret・payload・response body・下位例外の
文言を含めない — をここに集約し、client ごとの再実装を防ぐ。
"""

from __future__ import annotations

from typing import NoReturn
from urllib.parse import SplitResult

import requests

from youtube_automation.core.errors import GeneratorError


def http_status(response: requests.Response | None) -> int | None:
    """response から int の status code だけを安全に取り出す。"""
    if response is None:
        return None
    status_code = response.status_code
    return status_code if isinstance(status_code, int) else None


def raise_transport_error(operation: str, error: requests.RequestException) -> NoReturn:
    """transport 例外を、secret や body を含まない ``GeneratorError`` へ変換する。"""
    if isinstance(error, requests.Timeout):
        raise GeneratorError(f"{operation} が timeout しました") from None
    if isinstance(error, requests.HTTPError):
        status = http_status(error.response)
        detail = f" (status={status})" if status is not None else ""
        raise GeneratorError(f"{operation} HTTP error{detail}") from None
    raise GeneratorError(f"{operation} に失敗しました") from None


def response_json(response: requests.Response, subject: str) -> dict[str, object]:
    """response body を JSON object として解釈する。復号できない body は文言へ含めない。"""
    try:
        body = response.json()
    except requests.exceptions.JSONDecodeError:
        raise GeneratorError(f"{subject} response を JSON として解釈できません") from None
    if not isinstance(body, dict):
        raise GeneratorError(f"{subject} response は JSON object である必要があります")
    return body


def is_safe_https(parsed: SplitResult) -> bool:
    """認証情報を埋め込んでいない HTTPS URL かを判定する（host allowlist は含まない）。"""
    if parsed.scheme != "https" or not parsed.netloc:
        return False
    return parsed.username is None and parsed.password is None
