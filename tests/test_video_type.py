"""動画タイプ共通契約と generator hook のテスト。"""

from __future__ import annotations

import pytest

from youtube_automation.utils import veo_generator
from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.veo_generator import generate_video, register_video_generator
from youtube_automation.utils.video_type import VideoType, VideoTypeConfig


def test_video_type_config_defaults_to_loop() -> None:
    assert VideoTypeConfig.from_mapping({}).video_type is VideoType.LOOP


def test_video_type_config_parses_explicit_static() -> None:
    assert VideoTypeConfig.from_mapping({"video_type": "static"}).video_type is VideoType.STATIC


def test_video_type_config_rejects_unknown_value() -> None:
    with pytest.raises(ConfigError, match="loop, static"):
        VideoTypeConfig.from_mapping({"video_type": "multi_scene"})


def test_generate_video_dispatches_to_registered_hook() -> None:
    calls: list[tuple[object, str]] = []

    def generator(client: object, *, output: str) -> bool:
        calls.append((client, output))
        return True

    original_registry = dict(veo_generator._VIDEO_TYPE_GENERATORS)
    try:
        register_video_generator(VideoType.STATIC, generator)
        client = object()
        assert generate_video("static", client, output="result.mp4") is True
        assert calls == [(client, "result.mp4")]
    finally:
        # static は生成不要な背景タイプなので registry の標準状態へ戻す。
        veo_generator._VIDEO_TYPE_GENERATORS.clear()
        veo_generator._VIDEO_TYPE_GENERATORS.update(original_registry)
