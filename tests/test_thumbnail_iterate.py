"""Contract tests for the /thumbnail-iterate state helper (issue #1969)."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / ".claude/skills/thumbnail-iterate/references/thumbnail-iterate-state.py"


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def _candidate(repo: Path, name: str, body: bytes) -> tuple[str, str]:
    relative = f"collections/planning/demo/10-assets/{name}"
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return relative, hashlib.sha256(body).hexdigest()


def _plan(repo: Path, *, video_id: str = "video-1", element: str = "color") -> Path:
    control, _ = _candidate(repo, "thumbnail.jpg", b"control")
    variant, _ = _candidate(repo, "thumbnail-v2.jpg", b"variant")
    payload = {
        "video_id": video_id,
        "collection": "collections/planning/demo",
        "target_ctr": 6.0,
        "channel_average_ctr": 4.0,
        "browse_share": 35.0,
        "suggested_share": 25.0,
        "hypotheses": [element],
        "round_type": "controlled",
        "candidates": [
            {"id": "A", "file": control, "changed_elements": []},
            {"id": "B", "file": variant, "changed_elements": [element]},
        ],
    }
    path = repo / "plan.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _history(repo: Path, plan: dict, winner: str | None) -> Path:
    candidates = []
    for candidate in plan["candidates"]:
        candidates.append(
            {
                "id": candidate["id"],
                "file": candidate["file"],
                "sha256": candidate["sha256"],
                "watch_time_share": 60 if candidate["id"] == winner else 40,
            }
        )
    status = "winner" if winner else "performed_same"
    history = {
        "schema_version": 1,
        "entries": [
            {
                "video_id": plan["video_id"],
                "completed_at": "2026-07-18T00:00:00Z",
                "result": {
                    "studio_label": "Winner" if winner else "Performed Same",
                    "status": status,
                    "result_candidate_id": winner,
                },
                "candidates": candidates,
            }
        ],
    }
    path = repo / plan["collection"] / "20-documentation/thumbnail-test-history.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history), encoding="utf-8")
    return path


def test_plan_records_supported_attribution_and_content_hashes(tmp_path: Path) -> None:
    source = _plan(tmp_path)

    result = _run("plan", "--repo", str(tmp_path), "--input", str(source), cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    run = json.loads((tmp_path / "data/thumbnail-iterate/runs/video-1.json").read_text())
    assert run["attribution"] == {
        "target_ctr": 6.0,
        "channel_average_ctr": 4.0,
        "ctr_ratio": 1.5,
        "browse_suggested_share": 60.0,
        "verdict": "thumbnail_supported",
    }
    assert all(len(candidate["sha256"]) == 64 for candidate in run["candidates"])


def test_plan_stops_when_thumbnail_causality_is_not_supported(tmp_path: Path) -> None:
    source = _plan(tmp_path)
    payload = json.loads(source.read_text())
    payload["target_ctr"] = 4.1
    source.write_text(json.dumps(payload))

    result = _run("plan", "--repo", str(tmp_path), "--input", str(source), cwd=tmp_path)

    assert result.returncode == 2
    run = json.loads((tmp_path / "data/thumbnail-iterate/runs/video-1.json").read_text())
    assert run["status"] == "stopped"
    assert run["attribution"]["verdict"] == "thumbnail_not_supported"


def test_plan_rejects_multi_element_variant_and_symlink(tmp_path: Path) -> None:
    source = _plan(tmp_path)
    payload = json.loads(source.read_text())
    payload["candidates"][1]["changed_elements"] = ["color", "text"]
    source.write_text(json.dumps(payload))
    result = _run("plan", "--repo", str(tmp_path), "--input", str(source), cwd=tmp_path)
    assert result.returncode == 1
    assert "exactly one" in result.stderr

    source = _plan(tmp_path)
    payload = json.loads(source.read_text())
    target = tmp_path / payload["candidates"][1]["file"]
    target.unlink()
    target.symlink_to(tmp_path / payload["candidates"][0]["file"])
    result = _run("plan", "--repo", str(tmp_path), "--input", str(source), cwd=tmp_path)
    assert result.returncode == 1
    assert "symlink" in result.stderr


def test_promote_winner_then_requires_coherent_synthesis_for_second_element(
    tmp_path: Path,
) -> None:
    source = _plan(tmp_path, video_id="video-1", element="color")
    assert _run("plan", "--repo", str(tmp_path), "--input", str(source), cwd=tmp_path).returncode == 0
    run = json.loads((tmp_path / "data/thumbnail-iterate/runs/video-1.json").read_text())
    history = _history(tmp_path, run, "B")
    first = _run("promote", "--repo", str(tmp_path), "--video-id", "video-1", "--history", str(history), cwd=tmp_path)
    assert first.returncode == 0, first.stderr
    champion_path = tmp_path / "data/thumbnail-iterate/champion.json"
    champion = json.loads(champion_path.read_text())
    assert champion["file"].startswith("data/thumbnail-iterate/champions/")
    assert champion["file"].endswith(".jpg")
    assert champion["validated_elements"] == ["color"]

    source = _plan(tmp_path, video_id="video-2", element="composition")
    assert _run("plan", "--repo", str(tmp_path), "--input", str(source), cwd=tmp_path).returncode == 0
    run = json.loads((tmp_path / "data/thumbnail-iterate/runs/video-2.json").read_text())
    history = _history(tmp_path, run, "B")
    second = _run("promote", "--repo", str(tmp_path), "--video-id", "video-2", "--history", str(history), cwd=tmp_path)
    assert second.returncode == 3
    unchanged = json.loads(champion_path.read_text())
    assert unchanged["video_id"] == "video-1"
    pending = json.loads((tmp_path / "data/thumbnail-iterate/synthesis-required.json").read_text())
    assert pending["elements"] == ["color", "composition"]


def test_promote_rejects_candidate_changed_after_studio_history(tmp_path: Path) -> None:
    source = _plan(tmp_path)
    assert _run("plan", "--repo", str(tmp_path), "--input", str(source), cwd=tmp_path).returncode == 0
    run = json.loads((tmp_path / "data/thumbnail-iterate/runs/video-1.json").read_text())
    history = _history(tmp_path, run, "B")
    (tmp_path / run["candidates"][1]["file"]).write_bytes(b"changed-after-result")

    result = _run(
        "promote",
        "--repo",
        str(tmp_path),
        "--video-id",
        "video-1",
        "--history",
        str(history),
        cwd=tmp_path,
    )

    assert result.returncode == 1
    assert "current content hash" in result.stderr
    assert not (tmp_path / "data/thumbnail-iterate/champion.json").exists()


def test_coherent_synthesis_requires_current_champion_as_control(tmp_path: Path) -> None:
    champion_body = b"current-champion"
    champion_hash = hashlib.sha256(champion_body).hexdigest()
    snapshot = tmp_path / f"data/thumbnail-iterate/champions/{champion_hash}.jpg"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_bytes(champion_body)
    (tmp_path / "data/thumbnail-iterate/champion.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "video_id": "older-video",
                "file": str(snapshot.relative_to(tmp_path)),
                "sha256": champion_hash,
                "validated_elements": ["color"],
            }
        )
    )
    (tmp_path / "data/thumbnail-iterate/synthesis-required.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "coherent_synthesis_required",
                "elements": ["color", "composition"],
                "control": {"file": str(snapshot.relative_to(tmp_path)), "sha256": champion_hash},
                "evidence_video_ids": ["older-video", "newer-video"],
            }
        )
    )
    control, _ = _candidate(tmp_path, "thumbnail.jpg", b"wrong-control")
    variant, _ = _candidate(tmp_path, "thumbnail-v2.jpg", b"coherent-result")
    payload = {
        "video_id": "final-video",
        "collection": "collections/planning/demo",
        "target_ctr": 6.0,
        "channel_average_ctr": 4.0,
        "browse_share": 35.0,
        "suggested_share": 25.0,
        "hypotheses": ["color", "composition"],
        "round_type": "coherent_synthesis",
        "candidates": [
            {"id": "A", "file": control, "changed_elements": []},
            {
                "id": "B",
                "file": variant,
                "changed_elements": ["color", "composition"],
            },
        ],
    }
    source = tmp_path / "synthesis-plan.json"
    source.write_text(json.dumps(payload))

    result = _run("plan", "--repo", str(tmp_path), "--input", str(source), cwd=tmp_path)

    assert result.returncode == 1
    assert "current champion" in result.stderr


def test_skill_docs_define_routing_thresholds_and_champion_contract() -> None:
    iterate = (ROOT / ".claude/skills/thumbnail-iterate/SKILL.md").read_text()
    thumbnail = (ROOT / ".claude/skills/thumbnail/SKILL.md").read_text()
    thumbnail_test = (ROOT / ".claude/skills/thumbnail-test/SKILL.md").read_text()

    for phrase in (
        "1.20",
        "50%",
        "/thumbnail-test",
        "最大 3",
        "champion.json",
        "機械的に合成",
        "yt-generate-image",
        "codex-image.sh",
    ):
        assert phrase in iterate
    assert "/thumbnail-iterate" in thumbnail
    assert "champion.json" in thumbnail
    assert "/thumbnail-iterate" in thumbnail_test
