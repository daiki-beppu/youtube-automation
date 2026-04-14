"""サムネイル特徴量と CTR の相関分析"""

from __future__ import annotations

from typing import Dict, List

import pandas as pd


def compute_correlations(videos: List[Dict], min_samples: int = 3) -> Dict[str, Dict]:
    """各特徴量と CTR の Pearson 相関を計算する。

    Args:
        videos: [{video_id, ctr, features: {name: value, ...}}, ...]
        min_samples: 相関計算に必要な最小サンプル数

    Returns:
        {"<feature>_vs_ctr": {"pearson": r, "n": N, "interpretation": ..., "note": ...}}
    """
    rows = []
    for v in videos:
        if v.get("ctr") is None:
            continue
        feats = v.get("features") or {}
        rows.append({"ctr": v["ctr"], **feats})

    df = pd.DataFrame(rows)
    result = {}

    feature_names = set()
    for v in videos:
        feature_names.update((v.get("features") or {}).keys())

    for feat in sorted(feature_names):
        key = f"{feat}_vs_ctr"
        if feat not in df.columns or len(df) < min_samples:
            result[key] = {
                "pearson": None,
                "n": len(df) if feat in df.columns else 0,
                "note": "サンプル不足",
            }
            continue

        subset = df[[feat, "ctr"]].dropna()
        n = len(subset)
        if n < min_samples:
            result[key] = {"pearson": None, "n": n, "note": "サンプル不足"}
            continue

        r = subset[feat].corr(subset["ctr"])
        result[key] = {
            "pearson": round(float(r), 3) if pd.notna(r) else None,
            "n": n,
            "interpretation": _interpret(r),
        }
    return result


def _interpret(r: float) -> str:
    """Pearson 相関係数を日本語で解釈する。"""
    if pd.isna(r):
        return "計算不可"
    abs_r = abs(r)
    direction = "正" if r > 0 else "負"
    if abs_r >= 0.7:
        strength = "強い"
    elif abs_r >= 0.4:
        strength = "中程度の"
    elif abs_r >= 0.2:
        strength = "弱い"
    else:
        strength = "ほぼ無"
    return f"{strength}{direction}の相関"
