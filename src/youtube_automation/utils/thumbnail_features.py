"""サムネイル画像の特徴量抽出 (Pillow のみ)

brightness/contrast/saturation/dominant_hue/colorfulness を返す。
CTR 相関分析と thumbnail 候補の自動選択 (#1370) の入力。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, Sequence

from PIL import Image

# dominant_hue は 0-255 スケールの循環値 (PIL HSV の H チャンネル)。
_HUE_PERIOD = 256

# 特徴量ごとの特性スケール。自動選択 (#1370) の距離計算で各特徴量を
# 同程度のレンジへ正規化するために使う。参照プール内の分散を使うと
# 参照画像同士が酷似する TTP プールで分散ゼロに退化するため固定値にする。
FEATURE_SCALES: Dict[str, float] = {
    "brightness": 255.0,
    "contrast": 128.0,
    "saturation": 255.0,
    "dominant_hue": _HUE_PERIOD / 2,
    "colorfulness": 100.0,
}

# 特徴量抽出は純 Python のピクセル走査のため、フルサイズ画像では遅い。
# 抽出前にこの辺の長さまで縮小する (色統計は縮小してもほぼ保存される)。
_FEATURE_EXTRACTION_MAX_DIMENSION = 256


def extract_features(img: Image.Image) -> Dict[str, float]:
    """RGB 画像から 5 つの特徴量を抽出する。"""
    img = img.convert("RGB")

    hsv = img.convert("HSV")
    h, s, v = hsv.split()

    brightness = _mean(v)
    saturation = _mean(s)

    # 支配色 Hue: H チャンネルのヒストグラム最頻値 (0-255 スケール)
    hist = h.histogram()
    dominant_hue = int(max(range(len(hist)), key=lambda i: hist[i]))

    # Contrast: グレースケールの標準偏差
    gray = img.convert("L")
    contrast = _stdev(gray)

    # Colorfulness (Hasler-Süsstrunk, 簡略版)
    r, g, b = img.split()
    rg = _abs_diff(r, g)
    yb = _abs_diff_half_sum(r, g, b)
    mean_rg, std_rg = _mean(rg), _stdev(rg)
    mean_yb, std_yb = _mean(yb), _stdev(yb)
    colorfulness = (std_rg**2 + std_yb**2) ** 0.5 + 0.3 * (mean_rg**2 + mean_yb**2) ** 0.5

    return {
        "brightness": round(brightness, 2),
        "contrast": round(contrast, 2),
        "saturation": round(saturation, 2),
        "dominant_hue": dominant_hue,
        "colorfulness": round(colorfulness, 2),
    }


def extract_features_from_path(
    path: str | Path, *, max_dimension: int = _FEATURE_EXTRACTION_MAX_DIMENSION
) -> Dict[str, float]:
    """画像ファイルから特徴量を抽出する。

    純 Python 集計の高速化のため、長辺が ``max_dimension`` を超える画像は
    アスペクト比を保ったまま縮小してから ``extract_features`` に渡す。
    """
    with Image.open(path) as img:
        rgb = img.convert("RGB")
    if max(rgb.size) > max_dimension:
        rgb.thumbnail((max_dimension, max_dimension))
    return extract_features(rgb)


def circular_hue_distance(a: float, b: float) -> float:
    """0-255 循環スケールの hue 距離を返す (最大 128)。"""
    diff = abs(a - b) % _HUE_PERIOD
    return min(diff, _HUE_PERIOD - diff)


def feature_centroid(features_list: Sequence[Dict[str, float]]) -> Dict[str, float]:
    """特徴量 dict の列から centroid を計算する。

    ``dominant_hue`` は循環値のため sin/cos 平均 (circular mean) を使う。
    それ以外は算術平均。
    """
    if not features_list:
        raise ValueError("特徴量リストが空です (参照画像が 1 枚も無い)")
    centroid: Dict[str, float] = {}
    for key in FEATURE_SCALES:
        values = [float(f[key]) for f in features_list]
        if key == "dominant_hue":
            centroid[key] = _circular_mean(values)
        else:
            centroid[key] = sum(values) / len(values)
    return centroid


def feature_distance(features: Dict[str, float], centroid: Dict[str, float]) -> float:
    """特徴量と centroid の正規化ユークリッド距離を返す (小さいほど近い)。

    各特徴量を ``FEATURE_SCALES`` で正規化して RMS を取る。
    ``dominant_hue`` は循環距離で比較する。
    """
    total = 0.0
    for key, scale in FEATURE_SCALES.items():
        if key == "dominant_hue":
            diff = circular_hue_distance(float(features[key]), float(centroid[key]))
        else:
            diff = float(features[key]) - float(centroid[key])
        total += (diff / scale) ** 2
    return math.sqrt(total / len(FEATURE_SCALES))


def _circular_mean(values: Sequence[float]) -> float:
    """0-255 循環スケールの circular mean を返す。

    値が対蹠に均等分散して平均ベクトルが消える場合は 0.0 を返す
    (deterministic なフォールバック)。
    """
    angles = [v / _HUE_PERIOD * 2 * math.pi for v in values]
    sin_mean = sum(math.sin(a) for a in angles) / len(angles)
    cos_mean = sum(math.cos(a) for a in angles) / len(angles)
    if abs(sin_mean) < 1e-12 and abs(cos_mean) < 1e-12:
        return 0.0
    return (math.atan2(sin_mean, cos_mean) / (2 * math.pi) * _HUE_PERIOD) % _HUE_PERIOD


def _mean(band: Image.Image) -> float:
    pixels = list(band.get_flattened_data())
    return sum(pixels) / len(pixels) if pixels else 0.0


def _stdev(band: Image.Image) -> float:
    pixels = list(band.get_flattened_data())
    if not pixels:
        return 0.0
    m = sum(pixels) / len(pixels)
    return (sum((p - m) ** 2 for p in pixels) / len(pixels)) ** 0.5


def _abs_diff(band_a: Image.Image, band_b: Image.Image) -> Image.Image:
    a = list(band_a.get_flattened_data())
    b = list(band_b.get_flattened_data())
    out = Image.new("L", band_a.size)
    out.putdata([abs(x - y) for x, y in zip(a, b)])
    return out


def _abs_diff_half_sum(r: Image.Image, g: Image.Image, b: Image.Image) -> Image.Image:
    """|0.5*(R+G) - B| を計算する (Hasler-Süsstrunk の yb)"""
    rp = list(r.get_flattened_data())
    gp = list(g.get_flattened_data())
    bp = list(b.get_flattened_data())
    out = Image.new("L", r.size)
    out.putdata([min(255, int(abs(0.5 * (rr + gg) - bb))) for rr, gg, bb in zip(rp, gp, bp)])
    return out
