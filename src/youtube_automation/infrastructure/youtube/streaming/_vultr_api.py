"""`infrastructure/youtube/streaming/` 内の Vultr API client が共有する HTTP GET helper。"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from youtube_automation.core.errors import YouTubeAPIError

_HTTP_TIMEOUT_SECONDS = 30


def get_vultr_json(url: str, *, api_key: str, api_label: str) -> object:
    """Bearer 認証で Vultr API を GET し、decode 済み JSON を形状検証せずに返す。

    通信・timeout・UTF-8 decode・JSON parse の失敗は
    `YouTubeAPIError("<api_label> request failed: ...")` に正規化する。
    """
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise YouTubeAPIError(f"{api_label} request failed: {error}") from error


__all__ = ["get_vultr_json"]
