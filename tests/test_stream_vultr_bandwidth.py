"""utils/streaming/vultr_bandwidth.py のユニットテスト。

要件 R1/R2: Vultr `/v2/instances/{id}/bandwidth` から月次帯域を取得し GB 換算する。

設計:
- `fetch_bandwidth(instance_id, api_key)` は raw レスポンスの `bandwidth` dict を返す
  (キー = 日付 "YYYY-MM-DD"、値 = {"incoming_bytes": N, "outgoing_bytes": N})
- `monthly_total_gb(bandwidth, year, month)` は incoming + outgoing を GB に換算
  (1 GB = 1024**3 bytes)
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from youtube_automation.infrastructure.errors import YouTubeAPIError
from youtube_automation.utils.streaming import vultr_bandwidth

_BYTES_PER_GB = 1024**3


# ---------- fetch_bandwidth (HTTP boundary) ----------


def _fake_urlopen(payload: dict, status: int = 200):
    """urllib.request.urlopen のレスポンス mock."""

    class _Resp:
        def __init__(self, body: bytes):
            self._body = body
            self.status = status

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return _Resp(json.dumps(payload).encode("utf-8"))


def test_fetch_bandwidth_calls_vultr_api_with_bearer_token():
    """Given instance_id=ABC, api_key=KEY
    When fetch_bandwidth を呼ぶ
    Then https://api.vultr.com/v2/instances/ABC/bandwidth に Bearer KEY 付きで GET。
    """
    with patch("youtube_automation.utils.streaming.vultr_bandwidth.urllib.request.urlopen") as mock_open:
        mock_open.return_value = _fake_urlopen({"bandwidth": {}})
        vultr_bandwidth.fetch_bandwidth(instance_id="ABC", api_key="KEY")

    assert mock_open.call_count == 1
    request_arg = mock_open.call_args[0][0]
    assert "ABC" in request_arg.full_url
    assert request_arg.full_url.startswith("https://api.vultr.com/v2/instances/")
    assert request_arg.full_url.endswith("/bandwidth")
    # Authorization ヘッダ
    auth = request_arg.get_header("Authorization")
    assert auth == "Bearer KEY"


def test_fetch_bandwidth_returns_bandwidth_dict():
    """Given Vultr API レスポンス {"bandwidth": {...}}
    When fetch_bandwidth を呼ぶ
    Then 内側の bandwidth dict のみを返す (envelope を剥がす)。
    """
    payload = {
        "bandwidth": {
            "2026-04-01": {"incoming_bytes": 100, "outgoing_bytes": 200},
            "2026-04-02": {"incoming_bytes": 300, "outgoing_bytes": 400},
        }
    }
    with patch("youtube_automation.utils.streaming.vultr_bandwidth.urllib.request.urlopen") as mock_open:
        mock_open.return_value = _fake_urlopen(payload)
        got = vultr_bandwidth.fetch_bandwidth(instance_id="ABC", api_key="KEY")

    assert got == payload["bandwidth"]


def test_fetch_bandwidth_raises_on_http_error():
    """Given Vultr API が URLError
    When fetch_bandwidth を呼ぶ
    Then YouTubeAPIError or AutomationError 派生 (生 Exception を握り潰さない)。
    """
    import urllib.error

    with patch("youtube_automation.utils.streaming.vultr_bandwidth.urllib.request.urlopen") as mock_open:
        mock_open.side_effect = urllib.error.URLError("connection refused")
        with pytest.raises(YouTubeAPIError):
            vultr_bandwidth.fetch_bandwidth(instance_id="ABC", api_key="KEY")


def test_fetch_bandwidth_raises_when_response_missing_bandwidth_key():
    """Given Vultr が想定外のレスポンス (bandwidth キーなし)
    When fetch_bandwidth を呼ぶ
    Then YouTubeAPIError (フォールバックで {} を返さないこと)。
    """
    with patch("youtube_automation.utils.streaming.vultr_bandwidth.urllib.request.urlopen") as mock_open:
        mock_open.return_value = _fake_urlopen({"unexpected": "shape"})
        with pytest.raises(YouTubeAPIError):
            vultr_bandwidth.fetch_bandwidth(instance_id="ABC", api_key="KEY")


# ---------- url-injection defense (Issue #167): URL path encoding ----------


def test_fetch_bandwidth_percent_encodes_slash_in_instance_id():
    """Given instance_id に `/` を含む値 ("A/B")
    When fetch_bandwidth を呼ぶ
    Then `/` が `%2F` にエンコードされ、URL path segment を勝手に拡張できない
    (`safe=''` 必須の根拠: デフォルト `safe='/'` だと `/` が透過する)。
    """
    with patch("youtube_automation.utils.streaming.vultr_bandwidth.urllib.request.urlopen") as mock_open:
        mock_open.return_value = _fake_urlopen({"bandwidth": {}})
        vultr_bandwidth.fetch_bandwidth(instance_id="A/B", api_key="KEY")

    request_arg = mock_open.call_args[0][0]
    assert request_arg.full_url == "https://api.vultr.com/v2/instances/A%2FB/bandwidth"


def test_fetch_bandwidth_percent_encodes_traversal_payload_in_instance_id():
    """Given instance_id に path traversal payload ("../etc/passwd")
    When fetch_bandwidth を呼ぶ
    Then `/` を `%2F` に展開し、raw な `/etc/passwd` が URL に現れない
    (url-injection defense の意図を adversarial input で固定)。
    """
    from urllib.parse import quote

    with patch("youtube_automation.utils.streaming.vultr_bandwidth.urllib.request.urlopen") as mock_open:
        mock_open.return_value = _fake_urlopen({"bandwidth": {}})
        vultr_bandwidth.fetch_bandwidth(instance_id="../etc/passwd", api_key="KEY")

    request_arg = mock_open.call_args[0][0]
    expected_segment = quote("../etc/passwd", safe="")
    assert request_arg.full_url == f"https://api.vultr.com/v2/instances/{expected_segment}/bandwidth"
    assert "/etc/passwd" not in request_arg.full_url


# ---------- monthly_total_gb (pure) ----------


def test_monthly_total_gb_sums_incoming_and_outgoing():
    """Given 2026-04 内に 2 日分のデータ
    When monthly_total_gb(2026, 4) を呼ぶ
    Then (incoming + outgoing) の合計を GB 換算。
    """
    bandwidth = {
        "2026-04-01": {"incoming_bytes": _BYTES_PER_GB, "outgoing_bytes": _BYTES_PER_GB * 2},
        "2026-04-02": {"incoming_bytes": _BYTES_PER_GB * 3, "outgoing_bytes": _BYTES_PER_GB * 4},
    }
    got = vultr_bandwidth.monthly_total_gb(bandwidth, year=2026, month=4)
    assert got == pytest.approx(1.0 + 2.0 + 3.0 + 4.0)


def test_monthly_total_gb_filters_by_month():
    """Given 2026-04 と 2026-05 が混在
    When monthly_total_gb(2026, 4) を呼ぶ
    Then 4 月分のみを集計し 5 月分は除外する。
    """
    bandwidth = {
        "2026-04-30": {"incoming_bytes": _BYTES_PER_GB * 10, "outgoing_bytes": 0},
        "2026-05-01": {"incoming_bytes": _BYTES_PER_GB * 999, "outgoing_bytes": 0},
    }
    got = vultr_bandwidth.monthly_total_gb(bandwidth, year=2026, month=4)
    assert got == pytest.approx(10.0)


def test_monthly_total_gb_returns_zero_when_month_absent():
    """Given 該当月のデータが 1 日も無い
    When monthly_total_gb を呼ぶ
    Then 0.0 (境界値、空集合の集計は 0)。
    """
    bandwidth = {
        "2026-03-15": {"incoming_bytes": _BYTES_PER_GB, "outgoing_bytes": 0},
    }
    assert vultr_bandwidth.monthly_total_gb(bandwidth, year=2026, month=4) == 0.0


def test_monthly_total_gb_handles_february_with_31day_query():
    """Given 2026-02 のデータ
    When monthly_total_gb(2026, 2) を呼ぶ
    Then 2 月分のみ集計 (うるう年判定不要、文字列前方一致で十分)。
    """
    bandwidth = {
        "2026-02-28": {"incoming_bytes": _BYTES_PER_GB * 5, "outgoing_bytes": 0},
        "2026-03-01": {"incoming_bytes": _BYTES_PER_GB * 5, "outgoing_bytes": 0},
    }
    assert vultr_bandwidth.monthly_total_gb(bandwidth, year=2026, month=2) == pytest.approx(5.0)


def test_monthly_total_gb_zero_padded_month_match():
    """Given month=4 (int)
    When キーが "2026-04-..." のとき
    Then ゼロパディングを考慮してヒットさせる (month=4 → "04")。
    """
    bandwidth = {
        "2026-04-01": {"incoming_bytes": _BYTES_PER_GB, "outgoing_bytes": 0},
    }
    assert vultr_bandwidth.monthly_total_gb(bandwidth, year=2026, month=4) == pytest.approx(1.0)
