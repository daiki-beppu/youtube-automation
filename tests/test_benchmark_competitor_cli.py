"""Issue #1948: benchmark CLI の competitor 語彙契約。"""

from __future__ import annotations

import pytest

from youtube_automation.scripts import benchmark_collector, compare_thumbnails


@pytest.mark.parametrize(
    "build_parser",
    [benchmark_collector._build_parser, compare_thumbnails._build_parser],
)
def test_parsers_accept_competitor(build_parser):
    args = build_parser().parse_args(["--competitor", "celtic-music"])

    assert args.competitor == "celtic-music"


@pytest.mark.parametrize(
    "build_parser",
    [benchmark_collector._build_parser, compare_thumbnails._build_parser],
)
def test_removed_channel_flag_names_competitor_replacement(build_parser, capsys):
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["--channel", "celtic-music"])

    assert exc_info.value.code == 2
    assert "--channel は --competitor に変わりました" in capsys.readouterr().err
