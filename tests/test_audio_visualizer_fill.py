"""audio visualizer fill の実行時生成テスト。"""

from pathlib import Path

import pytest
from PIL import Image

from youtube_automation.commands.media import audio_visualizer_fill as cli
from youtube_automation.infrastructure.media.audio_visualizer_fill import (
    create_fill_asset,
    normalize_ffmpeg_color,
    parse_color,
    parse_size,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1x1", (1, 1)),
        ("1920x1080", (1920, 1080)),
    ],
)
def test_parse_size_accepts_positive_width_and_height(value: str, expected: tuple[int, int]) -> None:
    assert parse_size(value) == expected


@pytest.mark.parametrize("value", ["", "0x1", "1x0", "-1x2", "1X2", "1.5x2", " 1x2 "])
def test_parse_size_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError, match="invalid visualizer size"):
        parse_size(value)


@pytest.mark.parametrize(
    ("value", "allow_named", "expected"),
    [
        ("0xFF0080", False, (255, 0, 128)),
        ("#00ff80", False, (0, 255, 128)),
        ("112233", False, (17, 34, 51)),
        ("11223344", False, (17, 34, 51)),
        ("WHITE", True, (255, 255, 255)),
    ],
)
def test_parse_color_accepts_supported_formats(value: str, allow_named: bool, expected: tuple[int, int, int]) -> None:
    assert parse_color(value, allow_named=allow_named) == expected


@pytest.mark.parametrize(
    ("value", "allow_named"),
    [
        ("white", False),
        ("transparent", True),
        ("#12345", False),
        ("0xGG0000", False),
    ],
)
def test_parse_color_rejects_unsupported_formats(value: str, allow_named: bool) -> None:
    with pytest.raises(ValueError, match="invalid fill color"):
        parse_color(value, allow_named=allow_named)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("#abcdef", "0xABCDEF"),
        ("abcdef80", "0xABCDEF"),
        ("WHITE", "white"),
    ],
)
def test_normalize_ffmpeg_color_returns_canonical_value(value: str, expected: str) -> None:
    assert normalize_ffmpeg_color(value) == expected


def test_normalize_ffmpeg_color_rejects_unknown_name() -> None:
    with pytest.raises(ValueError, match="invalid fill color"):
        normalize_ffmpeg_color("orange")


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


def test_valid_solid_returns_solid_without_creating_asset(tmp_path: Path) -> None:
    output = tmp_path / "solid.png"

    assert create_fill_asset("solid", "4x4", output, color="#abcdef") == "solid"
    assert not output.exists()


def test_rainbow_asset_contains_multiple_hues(tmp_path: Path) -> None:
    output = tmp_path / "rainbow.png"

    effective = create_fill_asset("rainbow", "9x9", output)

    image = Image.open(output)
    assert effective == "rainbow"
    assert len({image.getpixel((0, 4)), image.getpixel((8, 4)), image.getpixel((4, 0))}) == 3


def test_conical_asset_maps_angle_to_hue(tmp_path: Path) -> None:
    output = tmp_path / "conical.png"

    effective = create_fill_asset("conical", "9x9", output)

    image = Image.open(output)
    assert effective == "conical"
    assert len({image.getpixel((0, 4)), image.getpixel((8, 4)), image.getpixel((4, 0))}) == 3


@pytest.mark.parametrize(("fill_type", "color"), [("plasma", "white"), ("solid", "oops")])
def test_invalid_fill_fails_loudly(tmp_path: Path, fill_type: str, color: str) -> None:
    with pytest.raises(ValueError, match="invalid fill"):
        create_fill_asset(fill_type, "4x4", tmp_path / "fill.png", color=color)


def test_cli_forwards_all_arguments_and_prints_effective_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "fill.png"
    calls = []

    def _create_fill_asset(fill_type, size, output_path, *, color, top, bottom):
        calls.append((fill_type, size, output_path, color, top, bottom))
        return "gradient"

    monkeypatch.setattr(cli, "create_fill_asset", _create_fill_asset)
    monkeypatch.setattr(
        "sys.argv",
        [
            "yt-audio-visualizer-fill",
            "--type",
            "gradient",
            "--size",
            "640x360",
            "--output",
            str(output),
            "--color",
            "#112233",
            "--top",
            "#445566",
            "--bottom",
            "#778899",
        ],
    )

    assert cli.main() is None
    assert calls == [("gradient", "640x360", output, "#112233", "#445566", "#778899")]
    assert capsys.readouterr().out == "gradient\n"


def test_cli_converts_value_error_to_usage_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _fail(*args, **kwargs):
        raise ValueError("invalid visualizer size")

    monkeypatch.setattr(cli, "create_fill_asset", _fail)
    monkeypatch.setattr(
        "sys.argv",
        [
            "yt-audio-visualizer-fill",
            "--type",
            "solid",
            "--size",
            "invalid",
            "--output",
            "fill.png",
        ],
    )

    with pytest.raises(SystemExit) as error:
        cli.main()

    assert error.value.code == 2
    stderr = capsys.readouterr().err
    assert "usage: yt-audio-visualizer-fill" in stderr
    assert "invalid visualizer size" in stderr
