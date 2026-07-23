"""Metadata generation public API."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from youtube_automation.domains.metadata.service import BAHMetadataGenerator


def __getattr__(name: str):
    exports = {
        "BAHMetadataGenerator": ("service", "BAHMetadataGenerator"),
        "LOCALIZED_TITLE_PLACEHOLDERS": ("localizations", "LOCALIZED_TITLE_PLACEHOLDERS"),
        "SceneTitleViolation": ("localizations", "SceneTitleViolation"),
        "build_short_description": ("descriptions", "build_short_description"),
        "build_short_localizations": ("localizations", "build_short_localizations"),
        "format_scene_title_violations": ("localizations", "format_scene_title_violations"),
        "format_title_template": ("titles", "format_title_template"),
        "validate_localizations_title_templates": (
            "localizations",
            "validate_localizations_title_templates",
        ),
        "validate_scene_phrases": ("localizations", "validate_scene_phrases"),
    }
    try:
        module_name, attribute_name = exports[name]
    except KeyError as error:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from error

    from importlib import import_module

    return getattr(import_module(f"{__name__}.{module_name}"), attribute_name)


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
