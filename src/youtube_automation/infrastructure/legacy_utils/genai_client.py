"""Compatibility facade for the historical GenAI client import path."""

from youtube_automation.infrastructure.media.genai_client import (
    GLOBAL_LOCATION,
    VEO_LOCATION,
    create_genai_client,
    create_global_genai_client,
    create_veo_genai_client,
)

__all__ = [
    "GLOBAL_LOCATION",
    "VEO_LOCATION",
    "create_genai_client",
    "create_global_genai_client",
    "create_veo_genai_client",
]
