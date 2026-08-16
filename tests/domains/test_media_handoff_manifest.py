from __future__ import annotations

import json

import pytest

from youtube_automation.core.errors import MediaStoreError
from youtube_automation.domains.media_handoff_manifest import (
    MANIFEST_SCHEMA_VERSION,
    HandoffFile,
    HandoffIdentity,
    HandoffManifest,
)


def _manifest() -> HandoffManifest:
    return HandoffManifest.build(
        HandoffIdentity("ambient-lab", "rain-night", "video-upload"),
        (
            HandoffFile("video/Master.mp4", 11, "a" * 64),
            HandoffFile("audio/master.wav", 7, "b" * 64),
        ),
    )


def test_manifest_builds_a_canonical_file_list_and_stable_root_checksum() -> None:
    manifest = _manifest()

    assert manifest.schema_version == MANIFEST_SCHEMA_VERSION
    assert [entry.path for entry in manifest.files] == ["audio/master.wav", "video/Master.mp4"]
    assert len(manifest.root_sha256) == 64
    assert HandoffManifest.from_json_bytes(manifest.to_json_bytes()) == manifest


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda value: value.update(schema_version=2), "schema_version"),
        (lambda value: value.update(channel="../escape"), "channel"),
        (lambda value: value["files"][0].update(path="../escape.mp4"), "path"),
        (lambda value: value["files"][0].update(size=-1), "size"),
        (lambda value: value["files"][0].update(size=True), "size"),
        (lambda value: value["files"][0].update(sha256="not-a-checksum"), "sha256"),
        (lambda value: value["files"].append(dict(value["files"][0])), "duplicate"),
        (lambda value: value.update(files=None), "files"),
        (lambda value: value.update(files={}), "files"),
        (lambda value: value.update(root_sha256="0" * 64), "root"),
    ],
)
def test_manifest_parser_rejects_invalid_schema_paths_duplicates_and_checksums(mutation, match: str) -> None:
    value = json.loads(_manifest().to_json_bytes())
    mutation(value)

    with pytest.raises(MediaStoreError, match=match):
        HandoffManifest.from_json_bytes(json.dumps(value).encode())


def test_manifest_parser_rejects_unknown_fields() -> None:
    value = json.loads(_manifest().to_json_bytes())
    value["unexpected"] = True

    with pytest.raises(MediaStoreError, match="field"):
        HandoffManifest.from_json_bytes(json.dumps(value).encode())


def test_manifest_parser_rejects_unknown_file_fields() -> None:
    value = json.loads(_manifest().to_json_bytes())
    value["files"][0]["unexpected"] = True

    with pytest.raises(MediaStoreError, match="file field"):
        HandoffManifest.from_json_bytes(json.dumps(value).encode())
