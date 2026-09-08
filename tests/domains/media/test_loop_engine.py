import pytest

from youtube_automation.core.errors import ConfigError
from youtube_automation.domains.media.loop_engine import LoopEngine, LoopEngineConfig
from youtube_automation.domains.media.video_type import VideoType


def test_loop_engine_defaults_to_veo() -> None:
    assert LoopEngineConfig.from_mapping({}).engine is LoopEngine.VEO


@pytest.mark.parametrize("value", ["veo", "fal", "omni"])
def test_loop_engine_accepts_supported_values(value: str) -> None:
    assert LoopEngineConfig.from_mapping({"engine": value}).engine.value == value


@pytest.mark.parametrize("value", ["h3", "unknown"])
def test_loop_engine_rejects_unknown_value(value: str) -> None:
    with pytest.raises(ConfigError, match="loop.engine must be one of"):
        LoopEngineConfig.from_mapping({"engine": value})


@pytest.mark.parametrize("enum_type,member", [(LoopEngine, LoopEngine.FAL), (VideoType, VideoType.STATIC)])
def test_media_choice_preserves_enum_identity_and_normalizes_text(enum_type, member) -> None:
    assert enum_type.parse(member) is member
    assert enum_type.parse(f"  {member.value.upper()}  ") is member


@pytest.mark.parametrize("enum_type,allowed", [(LoopEngine, "veo, fal, omni"), (VideoType, "loop, static")])
@pytest.mark.parametrize("value", [None, "", "unknown"])
def test_media_choice_error_retains_custom_path_input_and_allowed_values(enum_type, allowed, value) -> None:
    with pytest.raises(ConfigError) as caught:
        enum_type.parse(value, config_path="custom.choice")

    assert str(caught.value) == f"custom.choice must be one of: {allowed} (got: {value!r})"
    assert isinstance(caught.value.__cause__, ValueError)
