"""通知層（Issue #110 / R13, R14、#109 と共有）。

設計:
- 単一エントリポイント `notify(content, webhook_url)`
- Discord-compat JSON `{"content": <text>}` を root shape で POST する
  (Slack の `text` キーや別 envelope を流用しない)
- webhook_url が None / 空文字なら HTTP は呼ばず、stderr に fail-soft で print
- webhook_url 指定時は HTTPS スキーム＋ Discord ホスト whitelist で検証
  （secret store 侵害時の SSRF 化を防止、Issue #166）
- HTTP 失敗 (URLError 等) は AutomationError 派生で raise
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from youtube_automation.utils.exceptions import AutomationError

_HTTP_TIMEOUT_SEC = 30
_ALLOWED_SCHEME = "https"
_ALLOWED_HOSTS = frozenset({"discord.com", "discordapp.com"})


class NotificationError(AutomationError):
    """通知投稿の失敗。"""


def notify(*, content: str, webhook_url: str | None) -> None:
    """webhook に通知メッセージを投稿する。

    Args:
        content: 投稿本文 (Discord webhook の `content` フィールドにそのまま入る)
        webhook_url: 投稿先 URL。None または空文字なら HTTP 経由ではなく stderr に出力。

    Raises:
        NotificationError: webhook_url が不正 (scheme/host が許可外) または HTTP 投稿に失敗した場合
    """
    if not webhook_url:
        print(content, file=sys.stderr)
        return

    parts = urlsplit(webhook_url)
    if parts.scheme != _ALLOWED_SCHEME:
        raise NotificationError(
            f"webhook URL must be {_ALLOWED_SCHEME}, got {parts.scheme!r}"
        )
    if parts.hostname not in _ALLOWED_HOSTS:
        raise NotificationError(
            f"webhook host must be one of {sorted(_ALLOWED_HOSTS)}, "
            f"got {parts.hostname!r}"
        )

    body = json.dumps({"content": content}).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT_SEC) as resp:
            resp.read()
    except (urllib.error.URLError, TimeoutError) as e:
        raise NotificationError(f"webhook POST failed: {e}") from e
