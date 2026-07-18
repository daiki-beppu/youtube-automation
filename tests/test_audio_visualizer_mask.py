"""Runtime-generated audio visualizer mask tests (#1684)."""

from pathlib import Path

import pytest
from PIL import Image

from youtube_automation.utils.audio_visualizer_mask import generate_mask, parse_size


def test_mirror_mask_uses_configured_size_and_bar_count(tmp_path: Path) -> None:
    output = generate_mask(tmp_path / "mirror.png", style="mirror-mountain", size="300x110", bars=16)

    with Image.open(output) as mask:
        assert mask.size == (300, 110)
        assert mask.mode == "L"
        transitions = sum(mask.getpixel((x, 55)) != mask.getpixel((x - 1, 55)) for x in range(1, 300))
        assert transitions == 32


@pytest.mark.parametrize("style", ["ring", "ring-line"])
def test_ring_masks_use_runtime_geometry_and_arc(tmp_path: Path, style: str) -> None:
    output = generate_mask(
        tmp_path / f"{style}.png",
        style=style,
        size="300x110",
        bars=12,
        inner_r=30,
        length=20,
        arc_deg=(30, 330),
    )

    with Image.open(output) as mask:
        assert mask.size == (100, 100)
        assert mask.getbbox() is not None
        assert mask.getpixel((50, 0)) == 0


def test_heart_mask_places_discrete_bars_on_cardioid(tmp_path: Path) -> None:
    output = generate_mask(tmp_path / "heart.png", style="heart", size="300x240", bars=24)

    with Image.open(output) as mask:
        assert mask.size == (300, 240)
        assert mask.mode == "L"
        assert mask.getbbox() is not None
        assert mask.getpixel((0, 0)) == 0
        # The cardioid point sits at the lower centre; the canvas corners remain clear.
        assert mask.getpixel((150, 158)) > 0


@pytest.mark.parametrize("value", ["300", "300X110", "0x110", "abcx110"])
def test_parse_size_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError, match="WIDTHxHEIGHT"):
        parse_size(value)
