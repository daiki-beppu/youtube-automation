"""Suno download 完了から cloud 所有への境界引き渡し。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from youtube_automation.application.media_handoff import (
    HandoffSource,
    push_handoff,
    read_handoff_manifest,
)
from youtube_automation.core.errors import MediaStoreError, WorkflowStateError
from youtube_automation.domains.collections.workflow_state import WorkflowState
from youtube_automation.domains.collections.workflow_state import read as read_workflow_state
from youtube_automation.domains.collections.workflow_state import update as update_workflow_state
from youtube_automation.domains.media_handoff_manifest import MANIFEST_NAME, HandoffIdentity, HandoffManifest
from youtube_automation.domains.media_store import MediaKey, MediaStore
from youtube_automation.domains.notifications import NotificationEvent, NotificationEventKind
from youtube_automation.domains.suno.downloaded.archive import list_audio_files
from youtube_automation.infrastructure.media.collection_paths import CollectionPaths

_HANDOFF_POINT = "suno_download"
_HANDOFF_KEY_SEGMENT = "suno-download"
_MUSIC_DIRECTORY = "02-Individual-music"


SunoDownloadHandoffEventSink = Callable[[NotificationEvent], None]


@dataclass(frozen=True, slots=True)
class SunoDownloadHandoffResult:
    manifest_key: str
    root_sha256: str
    already_completed: bool


class SunoDownloadHandoff:
    def __init__(
        self,
        *,
        store: MediaStore,
        channel: str,
        on_event: SunoDownloadHandoffEventSink | None = None,
    ) -> None:
        self._store = store
        self._channel = channel
        self._on_event = on_event

    def complete(self, collection_dir: Path) -> SunoDownloadHandoffResult:
        paths = CollectionPaths(collection_dir)
        identity = HandoffIdentity(self._channel, paths.root.name, _HANDOFF_KEY_SEGMENT)
        manifest_key = MediaKey(identity.channel, identity.collection, identity.handoff, MANIFEST_NAME).as_posix()
        state = read_workflow_state(paths.workflow_state_path)
        completed = self._completed_manifest(state, identity, manifest_key)
        if completed is not None:
            return SunoDownloadHandoffResult(manifest_key, completed.root_sha256, True)

        preview = WorkflowState(state.to_dict())
        preview.record_cloud_handoff(
            point=_HANDOFF_POINT,
            manifest_key=manifest_key,
            root_sha256="0" * 64,
        )
        sources = self._sources(paths.music_dir)
        manifest = push_handoff(self._store, identity, sources)
        update_workflow_state(
            paths.workflow_state_path,
            lambda current: current.record_cloud_handoff(
                point=_HANDOFF_POINT,
                manifest_key=manifest_key,
                root_sha256=manifest.root_sha256,
            ),
        )
        event = NotificationEvent(
            NotificationEventKind.HANDOFF_COMPLETED,
            identity.channel,
            identity.collection,
            "suno-download-handoff",
            f"manifest={manifest_key}, root_sha256={manifest.root_sha256}",
        )
        if self._on_event is not None:
            self._on_event(event)
        return SunoDownloadHandoffResult(manifest_key, manifest.root_sha256, False)

    def _completed_manifest(
        self,
        state: WorkflowState,
        identity: HandoffIdentity,
        manifest_key: str,
    ) -> HandoffManifest | None:
        if state.phase != "cloud_owned":
            return None
        handoff = state.handoff
        if (
            handoff is None
            or handoff.point != _HANDOFF_POINT
            or handoff.owner != "cloud"
            or handoff.manifest_key != manifest_key
            or handoff.root_sha256 is None
        ):
            raise WorkflowStateError("workflow-state cloud handoff reference is incomplete or conflicting")
        manifest = read_handoff_manifest(self._store, identity)
        if manifest.root_sha256 != handoff.root_sha256:
            raise MediaStoreError("受け渡し manifest root checksum が workflow-state と一致しません")
        return manifest

    @staticmethod
    def _sources(music_dir: Path) -> tuple[HandoffSource, ...]:
        audio_files = list_audio_files(music_dir)
        if not audio_files:
            raise MediaStoreError("Suno download 引き渡し対象の音声ファイルがありません")
        return tuple(HandoffSource(path, f"{_MUSIC_DIRECTORY}/{path.name}") for path in audio_files)
