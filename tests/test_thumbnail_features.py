from PIL import Image

from youtube_automation.utils.thumbnail_features import extract_features


def _solid_image(color, size=(100, 100)):
    return Image.new("RGB", size, color)


def test_extract_features_pure_black():
    img = _solid_image((0, 0, 0))
    f = extract_features(img)
    assert f["brightness"] == 0
    assert f["saturation"] == 0
    assert f["contrast"] == 0


def test_extract_features_pure_white():
    img = _solid_image((255, 255, 255))
    f = extract_features(img)
    assert f["brightness"] == 255
    assert f["saturation"] == 0
    assert f["contrast"] == 0


def test_extract_features_pure_red():
    img = _solid_image((255, 0, 0))
    f = extract_features(img)
    assert f["brightness"] == 255
    assert f["saturation"] == 255
    # Red hue は 0 または 255 周辺
    assert f["dominant_hue"] in range(0, 10) or f["dominant_hue"] >= 245


def test_extract_features_half_black_half_white_has_contrast():
    img = Image.new("RGB", (100, 100), (0, 0, 0))
    # 右半分を白に塗る
    white_half = Image.new("RGB", (50, 100), (255, 255, 255))
    img.paste(white_half, (50, 0))
    f = extract_features(img)
    # 半々なら std ≈ 127.5
    assert 120 < f["contrast"] < 130


def test_extract_features_contains_all_keys():
    img = _solid_image((128, 64, 200))
    f = extract_features(img)
    expected = {"brightness", "contrast", "saturation", "dominant_hue", "colorfulness"}
    assert expected.issubset(f.keys())
