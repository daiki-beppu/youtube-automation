"""Issue #110 帯域モニタリングのデータフロー統合テスト。

CLI --report の入口から末端 (notify) までの一連の流れを、I/O 境界 (subprocess /
urllib / googleapiclient) のみ差し替えて、内部モジュール (vultr_bandwidth,
threshold, cycle_uptime, monthly_report, notification) は本物を動かす。

判定基準 (3 モジュール以上を横断する/呼び出しチェーンを通じて伝搬する):
- instance_resolver → vultr_bandwidth → monthly_report → notification
- --instance-id が resolver を経て fetch_bandwidth まで伝搬
- 通知 content にレポート文字列が乗ること
"""

from __future__ import annotations

import json
from unittest.mock import patch

from youtube_automation.cli import stream_bandwidth

_BYTES_PER_GB = 1024**3


def _fake_urlopen_for_vultr(payload: dict):
    """Vultr API mock。CLI -> vultr_bandwidth.fetch_bandwidth 経由で呼ばれる。"""

    class _Resp:
        def __init__(self, body: bytes):
            self._body = body
            self.status = 200

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return _Resp(json.dumps(payload).encode("utf-8"))


def test_report_flow_posts_combined_report(monkeypatch):
    """Given Vultr API が 2026-04 の合計 1188 GB を返す + アーカイブ 58 本
    When CLI --report --month 2026-04 を実行
    Then notification.notify が webhook URL 付きで呼ばれ、
         content に 2026-04 / 1188 / 58 / 60 が全て含まれる。
    """
    bandwidth_payload = {
        "bandwidth": {
            "2026-04-15": {"incoming_bytes": _BYTES_PER_GB * 1188, "outgoing_bytes": 0},
        }
    }
    captured = {}

    def fake_urlopen(req, timeout=None):
        # Vultr API か webhook かを URL で判別
        url = req.full_url
        if "vultr.com" in url:
            return _fake_urlopen_for_vultr(bandwidth_payload)
        if "discord.com" in url:
            captured["webhook_url"] = url
            captured["webhook_body"] = req.data
            return _fake_urlopen_for_vultr({"ok": True})
        raise AssertionError(f"unexpected URL: {url}")

    # シークレット解決
    def fake_get_secret(name: str):
        return {
            "VULTR_API_KEY": "fake-vultr-key",
            "STREAM_WEBHOOK_URL": "https://discord.com/api/webhooks/123/abc",
        }[name]

    # アーカイブ計数を直接モック (YouTube API は複雑な mock になるため境界で切る)
    def fake_count_archives(service, *, channel_id, year, month):
        return 58

    # YouTube サービスはダミー (count_archives モックが service を見ないので無害)
    def fake_get_youtube():
        return object()

    with (
        patch("youtube_automation.cli.stream_bandwidth.get_secret", side_effect=fake_get_secret),
        patch("youtube_automation.cli.stream_bandwidth.count_archives", side_effect=fake_count_archives),
        patch("youtube_automation.cli.stream_bandwidth.get_youtube", side_effect=fake_get_youtube),
        patch(
            "youtube_automation.utils.streaming.vultr_bandwidth.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ),
        patch(
            "youtube_automation.utils.notification.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ),
    ):
        rc = stream_bandwidth.main(["--report", "--month", "2026-04", "--instance-id", "VULTR_X"])

    assert rc == 0
    assert "webhook_body" in captured, "webhook 投稿が一度も発生していない"
    body = json.loads(captured["webhook_body"].decode("utf-8"))
    content = body["content"]
    # レポートに必須の値が全て乗っていること
    assert "2026-04" in content
    assert "1188" in content
    assert "58" in content
    assert "60" in content


def test_check_threshold_flow_silent_under_limit():
    """Given Vultr API が 100 GB のみを返す (閾値 1638.4 GB の下)
    When CLI --check-threshold を実行
    Then 通知用 webhook はヒットしない (静黙)。
    """
    bandwidth_payload = {
        "bandwidth": {
            "2026-04-15": {"incoming_bytes": _BYTES_PER_GB * 100, "outgoing_bytes": 0},
        }
    }
    webhook_calls = []

    def fake_urlopen(req, timeout=None):
        url = req.full_url
        if "vultr.com" in url:
            return _fake_urlopen_for_vultr(bandwidth_payload)
        if "discord.com" in url:
            webhook_calls.append(url)
            return _fake_urlopen_for_vultr({"ok": True})
        raise AssertionError(f"unexpected URL: {url}")

    def fake_get_secret(name: str):
        return {
            "VULTR_API_KEY": "fake-vultr-key",
            "STREAM_WEBHOOK_URL": "https://discord.com/api/webhooks/123/abc",
        }[name]

    with (
        patch("youtube_automation.cli.stream_bandwidth.get_secret", side_effect=fake_get_secret),
        patch("youtube_automation.cli.stream_bandwidth.count_archives", return_value=10),
        patch("youtube_automation.cli.stream_bandwidth.get_youtube", return_value=object()),
        patch(
            "youtube_automation.utils.streaming.vultr_bandwidth.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ),
        patch(
            "youtube_automation.utils.notification.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ),
        patch(
            "youtube_automation.cli.stream_bandwidth.today",
            return_value=__import__("datetime").date(2026, 4, 30),
        ),
    ):
        rc = stream_bandwidth.main(["--check-threshold", "--instance-id", "VULTR_X"])

    assert rc == 0
    assert webhook_calls == [], f"閾値未満で webhook が呼ばれた: {webhook_calls}"
