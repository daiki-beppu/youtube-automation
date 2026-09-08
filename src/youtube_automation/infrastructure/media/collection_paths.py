"""Compatibility exports for the collection layout domain."""

from pathlib import Path

from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.collections.paths import REQUIRED_SUBDIRS, CollectionPaths, resolve_collection_dir

__all__ = ["REQUIRED_SUBDIRS", "CollectionPaths", "Path", "ValidationError", "resolve_collection_dir"]
