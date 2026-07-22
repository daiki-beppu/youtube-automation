"""Metadata generation public API."""

from typing import TYPE_CHECKING

from youtube_automation.domains.metadata.descriptions import build_short_description
from youtube_automation.domains.metadata.localizations import (
    LOCALIZED_TITLE_PLACEHOLDERS,
    SceneTitleViolation,
    build_short_localizations,
    format_scene_title_violations,
    validate_localizations_title_templates,
    validate_scene_phrases,
)
from youtube_automation.domains.metadata.titles import format_title_template

if TYPE_CHECKING:
    from youtube_automation.domains.metadata.service import BAHMetadataGenerator


def __getattr__(name: str):
    if name == "BAHMetadataGenerator":
        from youtube_automation.domains.metadata.service import BAHMetadataGenerator

        return BAHMetadataGenerator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [  # noqa: RUF022 - public API order is part of the B2 contract
    "BAHMetadataGenerator",
    "LOCALIZED_TITLE_PLACEHOLDERS",
    "SceneTitleViolation",
    "build_short_description",
    "build_short_localizations",
    "format_scene_title_violations",
    "format_title_template",
    "validate_localizations_title_templates",
    "validate_scene_phrases",
]
