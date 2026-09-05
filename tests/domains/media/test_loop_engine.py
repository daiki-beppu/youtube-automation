import pytest

from youtube_automation.core.errors import ConfigError
from youtube_automation.domains.media.loop_engine import LoopEngine, LoopEngineConfig


def test_loop_engine_defaults_to_veo() -> None:
    assert LoopEngineConfig.from_mapping({}).engine is LoopEngine.VEO


@pytest.mark.parametrize("value", ["veo", "fal", "omni"])
def test_loop_engine_accepts_supported_values(value: str) -> None:
    assert LoopEngineConfig.from_mapping({"engine": value}).engine.value == value


@pytest.mark.parametrize("value", ["h3", "unknown"])
def test_loop_engine_rejects_unknown_value(value: str) -> None:
    with pytest.raises(ConfigError, match="loop.engine must be one of"):
        LoopEngineConfig.from_mapping({"engine": value})
