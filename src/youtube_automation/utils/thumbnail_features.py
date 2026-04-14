"""サムネイル画像の特徴量抽出 (Pillow のみ)

brightness/contrast/saturation/dominant_hue/colorfulness を返す。
CTR 相関分析の入力。
"""

from __future__ import annotations

from typing import Dict

from PIL import Image


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


def _mean(band: Image.Image) -> float:
    pixels = list(band.getdata())
    return sum(pixels) / len(pixels) if pixels else 0.0


def _stdev(band: Image.Image) -> float:
    pixels = list(band.getdata())
    if not pixels:
        return 0.0
    m = sum(pixels) / len(pixels)
    return (sum((p - m) ** 2 for p in pixels) / len(pixels)) ** 0.5


def _abs_diff(band_a: Image.Image, band_b: Image.Image) -> Image.Image:
    a = list(band_a.getdata())
    b = list(band_b.getdata())
    out = Image.new("L", band_a.size)
    out.putdata([abs(x - y) for x, y in zip(a, b)])
    return out


def _abs_diff_half_sum(r: Image.Image, g: Image.Image, b: Image.Image) -> Image.Image:
    """|0.5*(R+G) - B| を計算する (Hasler-Süsstrunk の yb)"""
    rp = list(r.getdata())
    gp = list(g.getdata())
    bp = list(b.getdata())
    out = Image.new("L", r.size)
    out.putdata([min(255, int(abs(0.5 * (rr + gg) - bb))) for rr, gg, bb in zip(rp, gp, bp)])
    return out
