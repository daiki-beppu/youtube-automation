"""
流入源・デバイス分析
収集済み analytics_data スナップショット群から流入源シェア推移・デバイス別集計・
検索語トップ N を計算する純粋関数群（API 呼び出しなし）
"""

from __future__ import annotations

from typing import Dict, List


def _share_map(entries: Dict, total_key: str = "views") -> Dict[str, float]:
    """{name: {views: N, ...}} からシェア (%) マップを計算する"""
    total = sum(e.get(total_key, 0) for e in entries.values())
    if total <= 0:
        return {name: 0.0 for name in entries}
    return {name: round((e.get(total_key, 0) / total) * 100, 1) for name, e in entries.items()}


def _snapshot_end_date(snapshot: Dict) -> str | None:
    period = snapshot.get("collection_period") or {}
    return period.get("end_date")


def analyze_traffic_trend(snapshots: List[Dict], top_search: int = 10) -> Dict:
    """
    スナップショット群から流入源シェア推移とデバイス別集計を計算する

    Args:
        snapshots (List[Dict]): analytics_data_*.json の中身（時系列昇順）
        top_search (int): 検索語トップ N の件数

    Returns:
        Dict: latest / share_trend / summary を含む分析結果
    """
    usable = [s for s in snapshots if (s.get("traffic_sources") or {}).get("sources")]

    share_trend = []
    for snapshot in usable:
        sources = snapshot["traffic_sources"]["sources"]
        devices = ((snapshot.get("audience") or {}).get("by_device") or {}).get("devices") or {}
        share_trend.append(
            {
                "end_date": _snapshot_end_date(snapshot),
                "collected_at": (snapshot.get("collection_period") or {}).get("collected_at"),
                "source_share": _share_map(sources),
                "device_share": _share_map(devices),
            }
        )

    if not usable:
        return {
            "snapshots_analyzed": 0,
            "latest": None,
            "share_trend": [],
            "summary": {"top_source": None, "top_device": None, "share_delta": {}},
        }

    latest_snapshot = usable[-1]
    traffic = latest_snapshot["traffic_sources"]
    sources = traffic["sources"]
    device_block = (latest_snapshot.get("audience") or {}).get("by_device") or {}
    devices = device_block.get("devices") or {}
    search_terms = sorted(
        traffic.get("search_terms") or [],
        key=lambda t: t.get("views", 0),
        reverse=True,
    )[:top_search]

    latest = {
        "period": latest_snapshot.get("collection_period") or {},
        "sources": sources,
        "total_views": traffic.get("total_views", 0),
        "devices": devices,
        "device_total_views": device_block.get("total_views", 0),
        "search_terms": search_terms,
    }

    source_share = share_trend[-1]["source_share"]
    device_share = share_trend[-1]["device_share"]
    top_source = max(source_share, key=source_share.get) if source_share else None
    top_device = max(device_share, key=device_share.get) if device_share else None

    share_delta: Dict[str, float] = {}
    if len(share_trend) >= 2:
        previous = share_trend[-2]["source_share"]
        for name, share in source_share.items():
            share_delta[name] = round(share - previous.get(name, 0.0), 1)

    summary = {
        "top_source": top_source,
        "top_source_share_percent": source_share.get(top_source, 0.0) if top_source else None,
        "top_device": top_device,
        "top_device_share_percent": device_share.get(top_device, 0.0) if top_device else None,
        "top_search_terms": [t.get("detail") for t in search_terms[:5]],
        "share_delta": share_delta,
    }

    return {
        "snapshots_analyzed": len(usable),
        "latest": latest,
        "share_trend": share_trend,
        "summary": summary,
    }
