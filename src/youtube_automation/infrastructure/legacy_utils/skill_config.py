"""Compatibility facade for the canonical skill configuration module."""

from youtube_automation.configuration import skills as _canonical

_cache = _canonical._cache
_collect_deprecated_override_keys = _canonical._collect_deprecated_override_keys
_warn_deprecated_override_keys = _canonical._warn_deprecated_override_keys
_default_path = _canonical._default_path
_channel_override_path = _canonical._channel_override_path
_channel_override_candidates = _canonical._channel_override_candidates
_override_candidate_exists = _canonical._override_candidate_exists
_resolve_channel_override = _canonical._resolve_channel_override
_deep_merge = _canonical._deep_merge
_load_yaml = _canonical._load_yaml
_load_json = _canonical._load_json
_load_override = _canonical._load_override
THUMBNAIL_MODE_PARALLEL = _canonical.THUMBNAIL_MODE_PARALLEL
THUMBNAIL_MODE_SEQUENTIAL = _canonical.THUMBNAIL_MODE_SEQUENTIAL
load_skill_config = _canonical.load_skill_config
load_channel_override = _canonical.load_channel_override
get_collection_ideate_thumbnail_mode = _canonical.get_collection_ideate_thumbnail_mode
reset = _canonical.reset
