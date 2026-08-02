"""Compatibility facade for the setup-directory contract."""

from youtube_automation.infrastructure.collections.setup_directory_contract import *  # noqa: F403
from youtube_automation.infrastructure.collections.setup_directory_contract import (
    SETUP_DIRECTORIES,
    validate_existing_setup_directories,
    validate_setup_directory_target,
)

__all__ = [
    "SETUP_DIRECTORIES",
    "validate_existing_setup_directories",
    "validate_setup_directory_target",
]
