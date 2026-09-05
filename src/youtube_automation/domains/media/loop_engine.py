"""ループ動画生成エンジンの skill-config 契約。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from youtube_automation.core.errors import ConfigError


class LoopEngine(str, Enum):
    """利用可能なループ動画生成プロバイダ。"""

    VEO = "veo"
    FAL = "fal"
    OMNI = "omni"

    @classmethod
    def parse(cls, value: object, *, config_path: str = "loop.engine") -> "LoopEngine":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError as exc:
            allowed = ", ".join(item.value for item in cls)
            raise ConfigError(f"{config_path} must be one of: {allowed} (got: {value!r})") from exc


@dataclass(frozen=True)
class LoopEngineConfig:
    """実行経路を fail-fast で選ぶ最小の skill-config parser。"""

    engine: LoopEngine = LoopEngine.VEO

    @classmethod
    def from_mapping(cls, config: Mapping[str, object] | None) -> "LoopEngineConfig":
        raw_value = (config or {}).get("engine", LoopEngine.VEO.value)
        return cls(engine=LoopEngine.parse(raw_value))
