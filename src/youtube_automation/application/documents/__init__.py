"""Skill-generated operational document workflows."""

from youtube_automation.application.documents.channel_strategy import (
    validate_channel_strategy_document_type,
    validate_persona_scene_references,
    write_channel_strategy_document,
)
from youtube_automation.application.documents.collection_plan import write_collection_plan_document
from youtube_automation.application.documents.migration import (
    DocumentWriteResult,
    MarkdownMigrationDecision,
    write_operational_document,
)
from youtube_automation.application.documents.music_prompt import (
    finalize_music_prompt_review,
    music_prompt_artifact_digest,
    require_recorded_machine_verification,
    write_music_prompt_document,
)
from youtube_automation.application.documents.video_description import (
    read_video_description_metadata,
    write_video_description_document,
)

__all__ = [
    "DocumentWriteResult",
    "MarkdownMigrationDecision",
    "finalize_music_prompt_review",
    "music_prompt_artifact_digest",
    "read_video_description_metadata",
    "require_recorded_machine_verification",
    "validate_channel_strategy_document_type",
    "validate_persona_scene_references",
    "write_channel_strategy_document",
    "write_collection_plan_document",
    "write_music_prompt_document",
    "write_operational_document",
    "write_video_description_document",
]
