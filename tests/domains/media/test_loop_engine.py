import pytest

from youtube_automation.core.errors import ConfigError
from youtube_automation.domains.media.loop_engine import LoopEngine, LoopEngineConfig


def test_loop_engine_defaults_to_veo() -> None:
    assert LoopEngineConfig.from_mapping({}).engine is LoopEngine.VEO


@pytest.mark.parametrize("value", ["veo", "fal", "omni", "h3"])
def test_loop_engine_accepts_supported_values(value: str) -> None:
    assert LoopEngineConfig.from_mapping({"engine": value}).engine.value == value


def test_loop_engine_rejects_unknown_value() -> None:
    with pytest.raises(ConfigError, match="loop.engine must be one of"):
        LoopEngineConfig.from_mapping({"engine": "unknown"})
