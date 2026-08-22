from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from youtube_automation.application import thumbnail_review
from youtube_automation.core.errors import ReviewError, ValidationError

NOW = datetime(2026, 8, 16, tzinfo=UTC)


def _candidate(
    collection: Path,
    name: str,
    *,
    candidate_id: str,
    artifact: str,
    pattern: str | None = None,
    summary: str = "all checks passed",
) -> Path:
    assets = collection / "10-assets"
    assets.mkdir(parents=True, exist_ok=True)
    image = assets / name
    Image.new("RGB", (1280, 720), "#123456").save(image)
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    qa = {
        "schema_version": 1,
        "candidate_id": candidate_id,
        "artifact": artifact,
        "pattern": pattern,
        "image_sha256": digest,
        "thumbnail_check": {"status": "passed", "summary": summary},
        "comparison_qa": {"status": "passed", "summary": "320px readable"},
        "metadata": {"attempt": 1, "provider": "fixture"},
        "evidence": ["benchmark layout retained"],
        "constraints": ["no logo", "16:9"],
    }
    image.with_suffix(f"{image.suffix}.review.json").write_text(json.dumps(qa), encoding="utf-8")
    return image


def test_snapshot_lists_all_candidates_with_dimensions_qa_and_stable_scope(tmp_path: Path) -> None:
    collection = tmp_path / "collection"
    _candidate(collection, "thumbnail-v1.jpg", candidate_id="thumbnail-v1", artifact="thumbnail")
    _candidate(collection, "thumbnail-v2.jpg", candidate_id="thumbnail-v2", artifact="thumbnail")
    _candidate(collection, "main-v1.png", candidate_id="main-v1", artifact="main")

    snapshot = thumbnail_review.build_thumbnail_review_snapshot(collection, "thumbnail", pattern=None, now=NOW)

    assert [item.candidate_id for item in snapshot.candidates] == ["thumbnail-v1", "thumbnail-v2"]
    details = dict(snapshot.manifest.candidates[0].details)
    assert details["確認目的"] == "文字付きthumbnail"
    assert details["画像寸法"] == "1280 × 720px"
    assert details["yt-thumbnail-check"] == "passed: all checks passed"
    assert details["比較QA"] == "passed: 320px readable"
    assert details["候補metadata"] == '{"attempt":1,"provider":"fixture"}'
    assert details["根拠"] == "benchmark layout retained"
    assert details["制約"] == "no logo / 16:9"


@pytest.mark.parametrize(
    ("name", "artifact", "pattern", "target_name"),
    [
        ("thumbnail-v1.jpg", "thumbnail", None, "thumbnail.jpg"),
        ("thumbnail-night-v1.jpg", "thumbnail", "night", "thumbnail-night.jpg"),
        ("main-v1.png", "main", None, "main.png"),
    ],
)
def test_finalizer_updates_only_artifact_pattern_target_after_digest_revalidation(
    tmp_path: Path,
    name: str,
    artifact: str,
    pattern: str | None,
    target_name: str,
) -> None:
    collection = tmp_path / "collection"
    image = _candidate(
        collection,
        name,
        candidate_id="choice-1",
        artifact=artifact,
        pattern=pattern,
    )
    snapshot = thumbnail_review.build_thumbnail_review_snapshot(collection, artifact, pattern=pattern, now=NOW)

    target = thumbnail_review.finalize_thumbnail_review_selection(
        collection,
        artifact=artifact,
        pattern=pattern,
        candidate_id="choice-1",
        source="terminal",
        expected_artifact_digest=snapshot.manifest.artifact_digest,
    )

    assert target.name == target_name
    assert target.read_bytes() == image.read_bytes()
    state = json.loads((collection / "workflow-state.json").read_text())
    assert state["thumbnail_review_selection"]["source"] == "terminal"
    assert state["thumbnail_review_selection"]["pattern"] == pattern
    assert "thumbnail" not in state.get("assets", {})


def test_single_candidate_web_view_has_original_and_320px_preview_and_escaped_qa(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    collection = tmp_path / "collection"
    _candidate(
        collection,
        "thumbnail-v1.jpg",
        candidate_id="choice-1",
        artifact="thumbnail",
        summary="<script>alert(1)</script>",
    )

    class FakeBroker:
        def __init__(self, manifest: object) -> None:
            self.manifest = manifest
            self.endpoint = f"http://127.0.0.1:32123/select/{manifest.token}"

        def __enter__(self) -> "FakeBroker":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def wait(self, *, timeout: float) -> object:
            del timeout
            return SimpleNamespace(candidate_id="choice-1", artifact_digest=self.manifest.artifact_digest)

    monkeypatch.setattr(thumbnail_review, "SelectionBroker", FakeBroker)
    monkeypatch.setattr(thumbnail_review, "open_local_file", lambda _path: True)

    result = thumbnail_review.run_thumbnail_review(collection, "thumbnail", now=NOW)
    html = (collection / "tmp/reviews/thumbnail-selection.html").read_text()

    assert result.status == "selected"
    assert html.count("file://") == 2
    assert 'class="review-320"' in html and 'width="320"' in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert "script-src 'none'" in html


def test_changed_qa_after_display_rejects_selection_before_canonical_or_state_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    collection = tmp_path / "collection"
    image = _candidate(collection, "thumbnail-v1.jpg", candidate_id="choice-1", artifact="thumbnail")
    target = collection / "10-assets/thumbnail.jpg"
    target.write_bytes(b"existing")

    class MutatingBroker:
        def __init__(self, manifest: object) -> None:
            self.manifest = manifest
            self.endpoint = f"http://127.0.0.1:32123/select/{manifest.token}"

        def __enter__(self) -> "MutatingBroker":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def wait(self, *, timeout: float) -> object:
            del timeout
            qa = image.with_suffix(f"{image.suffix}.review.json")
            qa.write_text(qa.read_text() + "\n", encoding="utf-8")
            return SimpleNamespace(candidate_id="choice-1", artifact_digest=self.manifest.artifact_digest)

    monkeypatch.setattr(thumbnail_review, "SelectionBroker", MutatingBroker)
    monkeypatch.setattr(thumbnail_review, "open_local_file", lambda _path: True)

    with pytest.raises(ReviewError, match="review中にartifactまたは候補実体が変わりました"):
        thumbnail_review.run_thumbnail_review(collection, "thumbnail", now=NOW)
    assert target.read_bytes() == b"existing"
    assert not (collection / "workflow-state.json").exists()


def test_missing_qa_symlink_and_artifact_pattern_mismatch_fail_closed(tmp_path: Path) -> None:
    collection = tmp_path / "collection"
    image = _candidate(
        collection,
        "thumbnail-night-v1.jpg",
        candidate_id="choice-1",
        artifact="thumbnail",
        pattern="night",
    )
    qa = image.with_suffix(f"{image.suffix}.review.json")
    qa.unlink()
    qa.symlink_to(tmp_path / "outside.json")

    with pytest.raises(ReviewError, match="QA結果がありません"):
        thumbnail_review.build_thumbnail_review_snapshot(collection, "thumbnail", pattern="night", now=NOW)
    with pytest.raises(ReviewError, match="AB pattern"):
        thumbnail_review.build_thumbnail_review_snapshot(collection, "main", pattern="night", now=NOW)


def test_finalizer_rejects_stale_digest_and_wrong_candidate_without_mutation(tmp_path: Path) -> None:
    collection = tmp_path / "collection"
    _candidate(collection, "thumbnail-v1.jpg", candidate_id="choice-1", artifact="thumbnail")
    target = collection / "10-assets/thumbnail.jpg"
    target.write_bytes(b"existing")

    with pytest.raises(ValidationError, match="digest"):
        thumbnail_review.finalize_thumbnail_review_selection(
            collection,
            artifact="thumbnail",
            pattern=None,
            candidate_id="choice-1",
            source="web",
            expected_artifact_digest="0" * 64,
        )
    assert target.read_bytes() == b"existing"
    assert not (collection / "workflow-state.json").exists()


def test_finalizer_rejects_canonical_symlink_without_reading_or_replacing_external_file(tmp_path: Path) -> None:
    collection = tmp_path / "collection"
    _candidate(collection, "thumbnail-v1.jpg", candidate_id="choice-1", artifact="thumbnail")
    snapshot = thumbnail_review.build_thumbnail_review_snapshot(collection, "thumbnail", pattern=None, now=NOW)
    external = tmp_path / "external.jpg"
    external.write_bytes(b"secret-external-content")
    (collection / "10-assets/thumbnail.jpg").symlink_to(external)

    with pytest.raises(ValidationError, match="通常file"):
        thumbnail_review.finalize_thumbnail_review_selection(
            collection,
            artifact="thumbnail",
            pattern=None,
            candidate_id="choice-1",
            source="web",
            expected_artifact_digest=snapshot.manifest.artifact_digest,
        )
    assert external.read_bytes() == b"secret-external-content"
    assert not (collection / "workflow-state.json").exists()
