"""サムネイル特徴量と CTR の相関分析"""

from __future__ import annotations

import math
from typing import Dict, List

import pandas as pd

MIN_SAMPLES_DEFAULT = 10
SIGNIFICANCE_LEVEL = 0.05
INSUFFICIENT_SAMPLES_NOTE = "サンプル不足で判定不能"


def compute_correlations(videos: List[Dict], min_samples: int = MIN_SAMPLES_DEFAULT) -> Dict[str, Dict]:
    """各特徴量と CTR の Pearson 相関を有意性検定つきで計算する。

    p 値は両側検定、多重比較補正は Benjamini-Hochberg (FDR)。
    補正後 p 値が有意水準以上の相関には significant: false を付け、
    断定的な解釈文を出さない。

    Args:
        videos: [{video_id, ctr, features: {name: value, ...}}, ...]
        min_samples: 相関計算に必要な最小サンプル数

    Returns:
        {"<feature>_vs_ctr": {"pearson": r, "p_value": p, "p_value_adjusted": p_adj,
                              "significant": bool, "n": N, "interpretation": ..., "note": ...}}
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

    computed = {}  # key -> (r, p, n)
    for feat in sorted(feature_names):
        key = f"{feat}_vs_ctr"
        if feat not in df.columns or len(df) < min_samples:
            result[key] = {
                "pearson": None,
                "n": len(df) if feat in df.columns else 0,
                "note": INSUFFICIENT_SAMPLES_NOTE,
            }
            continue

        subset = df[[feat, "ctr"]].dropna()
        n = len(subset)
        if n < min_samples:
            result[key] = {"pearson": None, "n": n, "note": INSUFFICIENT_SAMPLES_NOTE}
            continue

        r = subset[feat].corr(subset["ctr"])
        if pd.isna(r):
            result[key] = {"pearson": None, "n": n, "note": "計算不可（分散ゼロ等）"}
            continue
        computed[key] = (float(r), _pearson_p_value(float(r), n), n)

    adjusted = _benjamini_hochberg({k: p for k, (_, p, _) in computed.items()})
    for key, (r, p, n) in computed.items():
        p_adj = adjusted[key]
        significant = p_adj < SIGNIFICANCE_LEVEL
        result[key] = {
            "pearson": round(r, 3),
            "p_value": round(p, 4),
            "p_value_adjusted": round(p_adj, 4),
            "significant": significant,
            "n": n,
            "interpretation": _interpret(r) if significant else "有意でない（偶然の範囲の可能性）",
        }
    return result


def _pearson_p_value(r: float, n: int) -> float:
    """Pearson 相関係数の両側 p 値（t 分布近似）。"""
    if n < 3:
        return 1.0
    if abs(r) >= 1.0:
        return 0.0
    df = n - 2
    t_sq = r * r * df / (1.0 - r * r)
    # 両側 p 値 = I_{df/(df+t^2)}(df/2, 1/2)（正則化不完全ベータ関数）
    return _regularized_incomplete_beta(df / 2.0, 0.5, df / (df + t_sq))


def _benjamini_hochberg(p_values: Dict[str, float]) -> Dict[str, float]:
    """Benjamini-Hochberg 法で補正済み p 値（q 値）を返す。"""
    m = len(p_values)
    if m == 0:
        return {}
    ordered = sorted(p_values.items(), key=lambda kv: kv[1])
    adjusted = {}
    prev = 1.0
    for rank_from_last, (key, p) in enumerate(reversed(ordered)):
        rank = m - rank_from_last
        prev = min(prev, p * m / rank)
        adjusted[key] = prev
    return adjusted


def _regularized_incomplete_beta(a: float, b: float, x: float) -> float:
    """正則化不完全ベータ関数 I_x(a, b)。連分数展開（Numerical Recipes 準拠）。"""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_front = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1.0 - x)
    front = math.exp(ln_front)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _beta_continued_fraction(a, b, x) / a
    return 1.0 - front * _beta_continued_fraction(b, a, 1.0 - x) / b


def _beta_continued_fraction(a: float, b: float, x: float, max_iter: int = 200, eps: float = 3e-12) -> float:
    """不完全ベータ関数の連分数部（modified Lentz 法）。"""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


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
