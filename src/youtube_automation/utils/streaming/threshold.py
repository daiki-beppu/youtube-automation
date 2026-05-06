"""帯域消費量の閾値判定（Issue #110 / R6）。

純粋関数のみを公開する。`MONTHLY_QUOTA_GB` などの定数は呼び出し側から渡す
（境界での解決原則）。下位モジュールが定数を直接参照しない設計。
"""

from __future__ import annotations


def threshold_gb(*, quota_gb: float, ratio: float) -> float:
    """閾値 (GB) を返す純粋関数。

    Args:
        quota_gb: 月間帯域クォータ (GB)
        ratio: 比率 (0.0 - 1.0)

    Returns:
        quota_gb * ratio
    """
    return quota_gb * ratio


def is_over_threshold(*, usage_gb: float, quota_gb: float, ratio: float) -> bool:
    """`usage_gb` が `quota_gb * ratio` 以上か判定する純粋関数。

    境界 (`usage_gb == quota_gb * ratio`) は True とする。
    """
    return usage_gb >= threshold_gb(quota_gb=quota_gb, ratio=ratio)
