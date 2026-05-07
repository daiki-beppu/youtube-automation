"""utils/notification.py のユニットテスト。

要件 R13/R14: Discord/Slack 等の webhook に投稿する通知層 (#109 と共有)。

設計:
- `notify(content, webhook_url)` が単一エントリポイント
- webhook_url=None なら stderr に print する fail-soft
- webhook_url 指定時は Discord-compat JSON {"content": <content>} を POST
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from youtube_automation.utils import notification
from youtube_automation.utils.exceptions import AutomationError


def _fake_urlopen(status: int = 204):
    class _Resp:
        def __init__(self):
            self.status = status

        def read(self):
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return _Resp()


def test_notify_with_url_posts_json_content():
    """Given webhook_url 指定 + content="hello"
    When notify を呼ぶ
    Then POST body が {"content": "hello"} の JSON で送られる。
    """
    captured = {}

    def fake_open(req, timeout=None):
        captured["url"] = req.full_url
        captured["data"] = req.data
        captured["headers"] = {k.lower(): v for k, v in req.header_items()}
        return _fake_urlopen()

    with patch("youtube_automation.utils.notification.urllib.request.urlopen", side_effect=fake_open):
        notification.notify(content="hello", webhook_url="https://discord.com/api/webhooks/abc/xyz")

    assert captured["url"] == "https://discord.com/api/webhooks/abc/xyz"
    body = json.loads(captured["data"].decode("utf-8"))
    assert body == {"content": "hello"}
    assert captured["headers"].get("content-type", "").startswith("application/json")


def test_notify_with_none_url_falls_back_to_stderr(capsys):
    """Given webhook_url=None
    When notify を呼ぶ
    Then HTTP は呼ばれず、content が stderr に print される (fail-soft)。
    """
    with patch("youtube_automation.utils.notification.urllib.request.urlopen") as mock_open:
        notification.notify(content="fallback message", webhook_url=None)
    mock_open.assert_not_called()
    err = capsys.readouterr().err
    assert "fallback message" in err


def test_notify_with_empty_url_falls_back_to_stderr(capsys):
    """Given webhook_url="" (空文字)
    When notify を呼ぶ
    Then HTTP は呼ばれず、stderr に出力される (None と同等扱い)。
    """
    with patch("youtube_automation.utils.notification.urllib.request.urlopen") as mock_open:
        notification.notify(content="x", webhook_url="")
    mock_open.assert_not_called()
    err = capsys.readouterr().err
    assert "x" in err


def test_notify_propagates_http_error():
    """Given webhook_url 指定 + urlopen が URLError
    When notify を呼ぶ
    Then AutomationError 派生が raise される (黙って握り潰さない)。
    """
    import urllib.error

    with patch("youtube_automation.utils.notification.urllib.request.urlopen") as mock_open:
        mock_open.side_effect = urllib.error.URLError("dns failure")
        with pytest.raises(AutomationError):
            notification.notify(content="x", webhook_url="https://example.com/hook")


def test_notify_passes_content_root_shape_not_envelope():
    """Given Discord webhook の契約は {"content": <text>}
    When notify を呼ぶ
    Then text が body の "content" キーに直接入り、別の envelope に包まれない。
    """
    captured = {}

    def fake_open(req, timeout=None):
        captured["data"] = req.data
        return _fake_urlopen()

    with patch("youtube_automation.utils.notification.urllib.request.urlopen", side_effect=fake_open):
        notification.notify(content="root-shape", webhook_url="https://example.com/h")

    body = json.loads(captured["data"].decode("utf-8"))
    assert "content" in body
    assert body["content"] == "root-shape"
    # envelope 流用の検査: 余分なキーが付いていない
    assert set(body.keys()) == {"content"}
