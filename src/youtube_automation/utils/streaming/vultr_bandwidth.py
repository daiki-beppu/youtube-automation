"""Vultr `/v2/instances/{id}/bandwidth` API クライアント（Issue #110 / R1, R2）。

設計:
- `fetch_bandwidth(instance_id, api_key)` は HTTP 境界。`bandwidth` envelope を剥がして
  日付 → {incoming_bytes, outgoing_bytes} の dict を返す。
- `monthly_total_gb(bandwidth, year, month)` は純粋関数。incoming + outgoing を
  GB (1024^3 bytes) に換算して合算。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from youtube_automation.utils.exceptions import YouTubeAPIError

_VULTR_API_BASE = "https://api.vultr.com/v2"
_HTTP_TIMEOUT_SEC = 30
_BYTES_PER_GB = 1024**3


def fetch_bandwidth(*, instance_id: str, api_key: str) -> dict[str, dict[str, int]]:
    """Vultr API から該当インスタンスの帯域使用量を取得する。

    Args:
        instance_id: Vultr インスタンス ID
        api_key: Vultr API キー (Bearer Token)

    Returns:
        日付 (YYYY-MM-DD) をキー、`{"incoming_bytes": int, "outgoing_bytes": int}` を値とする dict。
        Vultr API レスポンスの `bandwidth` envelope を剥がして返す。

    Raises:
        YouTubeAPIError: HTTP エラーまたはレスポンス形式が想定外の場合
    """
    url = f"{_VULTR_API_BASE}/instances/{instance_id}/bandwidth"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT_SEC) as resp:
            payload: Any = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        raise YouTubeAPIError(f"Vultr bandwidth API request failed: {e}") from e

    if not isinstance(payload, dict) or "bandwidth" not in payload:
        raise YouTubeAPIError(f"Vultr bandwidth API returned unexpected shape: {payload!r}")

    return payload["bandwidth"]


def monthly_total_gb(bandwidth: dict[str, dict[str, int]], *, year: int, month: int) -> float:
    """月単位で `incoming + outgoing` を合算し GB 換算する純粋関数。

    Args:
        bandwidth: `fetch_bandwidth` が返す dict (日付 → bytes)
        year: 集計対象の年
        month: 集計対象の月 (1-12)

    Returns:
        GB 換算した合計値 (1 GB = 1024^3 bytes)。該当月のデータが無ければ 0.0。
    """
    prefix = f"{year:04d}-{month:02d}-"
    total_bytes = 0
    for date_key, entry in bandwidth.items():
        if not date_key.startswith(prefix):
            continue
        total_bytes += entry["incoming_bytes"] + entry["outgoing_bytes"]
    return total_bytes / _BYTES_PER_GB
