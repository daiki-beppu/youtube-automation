"""audio visualizer fill の実行時生成テスト。"""

from pathlib import Path

import pytest
from PIL import Image

from youtube_automation.utils.audio_visualizer_fill import create_fill_asset


def test_gradient_asset_interpolates_top_to_bottom(tmp_path: Path) -> None:
    output = tmp_path / "gradient.png"

    effective = create_fill_asset("gradient", "3x3", output, top="0xFF0000", bottom="0x0000FF")

    image = Image.open(output)
    assert effective == "gradient"
    assert image.size == (3, 3)
    assert image.getpixel((1, 0)) == (255, 0, 0)
    assert image.getpixel((1, 2)) == (0, 0, 255)


def test_equal_gradient_colors_collapse_to_solid_without_asset(tmp_path: Path) -> None:
    output = tmp_path / "gradient.png"

    effective = create_fill_asset("gradient", "4x2", output, top="#abcdef", bottom="0xABCDEF")

    assert effective == "solid"
    assert not output.exists()


def test_rainbow_asset_contains_multiple_hues(tmp_path: Path) -> None:
    output = tmp_path / "rainbow.png"

    effective = create_fill_asset("rainbow", "9x9", output)

    image = Image.open(output)
    assert effective == "rainbow"
    assert len({image.getpixel((0, 4)), image.getpixel((8, 4)), image.getpixel((4, 0))}) == 3


@pytest.mark.parametrize(("fill_type", "color"), [("plasma", "white"), ("solid", "oops")])
def test_invalid_fill_fails_loudly(tmp_path: Path, fill_type: str, color: str) -> None:
    with pytest.raises(ValueError, match="invalid fill"):
        create_fill_asset(fill_type, "4x4", tmp_path / "fill.png", color=color)
