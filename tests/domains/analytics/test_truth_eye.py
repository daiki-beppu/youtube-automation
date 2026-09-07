from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
import yaml

from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.analytics.truth_eye import (
    VIEWPOINTS,
    seal_training_record,
    validate_sealed_draft,
    verify_training_record,
)


def _draft() -> str:
    rows = ["| 観点 ID | 伸びた側 | 伸びなかった側 |", "|---|---|---|"]
    rows.extend(f"| {viewpoint.id} | winner {viewpoint.id} | loser {viewpoint.id} |" for viewpoint in VIEWPOINTS)
    return "\n".join(rows) + "\n\n## 抽象化\ncontrast principle\n\n## 再生数差への寄与順位\n1. V03\n2. V01\n3. V06\n"


def _pair() -> dict:
    video = {
        "video_id": "winner-id",
        "title": "Video title",
        "views": 12345,
        "published_at": "2026-09-01",
        "duration": "PT10M",
        "thumbnail_path": "/tmp/thumb.jpg",
    }
    return {"channel": "competitor", "winner": video, "loser": {**video, "video_id": "loser-id"}}


def test_viewpoints_are_single_ordered_source_for_required_phase_one_rows():
    assert [(item.id, item.name, item.required) for item in VIEWPOINTS] == [
        ("V01", "主役と占有率", True),
        ("V02", "構図・視線の流れ", True),
        ("V03", "配色", True),
        ("V04", "文字", True),
        ("V05", "表情・感情", True),
        ("V06", "縮小耐性", True),
        ("V07", "小道具・状況", False),
        ("V08", "季節感・時間帯", False),
        ("V09", "余白", False),
        ("V10", "シリーズ性", False),
        ("V11", "サムネ外の要因", False),
        ("V12", "刺激している欲求", False),
    ]


def test_seal_writes_record_and_sealed_pair(tmp_path):
    draft = tmp_path / "draft.md"
    draft.write_text(_draft(), encoding="utf-8")

    result = seal_training_record(_pair(), draft, tmp_path, now=datetime(2026, 9, 6, 12, 34, tzinfo=UTC))

    record = tmp_path / "docs/benchmarks/training/20260906-thumbnail-competitor-winner-id.md"
    sealed = record.with_suffix(".sealed.md")
    assert result.record == record
    assert result.sealed == sealed
    assert not draft.exists()
    assert sealed.read_text(encoding="utf-8") == _draft()
    text = record.read_text(encoding="utf-8")
    metadata = yaml.safe_load(text.split("---", 2)[1])
    assert set(metadata) == {"schema_version", "menu", "channel", "pair", "sealed", "next_try"}
    assert metadata["next_try"] is None
    assert metadata["sealed"]["sha256"] == hashlib.sha256(sealed.read_bytes()).hexdigest()
    assert metadata["sealed"]["path"] == sealed.name
    assert [line.split("|")[1].strip() for line in text.splitlines() if line.startswith("| V")] == [
        item.id for item in VIEWPOINTS if item.required
    ]
    assert [line for line in text.splitlines() if line.startswith("## Phase ")] == [
        f"## Phase {number}" for number in range(6)
    ]


@pytest.mark.parametrize(
    ("draft", "missing"),
    [
        (_draft().replace("| V12 | winner V12 | loser V12 |\n", ""), "V12"),
        (_draft().replace("2. V01\n3. V06\n", ""), "contribution_rank_top_3"),
        (_draft().replace("| V04 | winner V04 | loser V04 |", "| V04 | winner V04 | |"), "V04:loser"),
    ],
)
def test_validate_sealed_draft_reports_missing_parts(draft, missing):
    assert missing in validate_sealed_draft(draft)


def test_seal_rejects_malformed_draft_without_outputs(tmp_path):
    draft = tmp_path / "draft.md"
    draft.write_text(_draft().replace("| V12 | winner V12 | loser V12 |\n", ""), encoding="utf-8")

    with pytest.raises(ValidationError, match="V12"):
        seal_training_record(_pair(), draft, tmp_path, now=datetime(2026, 9, 6, tzinfo=UTC))

    assert draft.exists()
    assert not (tmp_path / "docs/benchmarks/training").exists()


def test_seal_refuses_to_overwrite_existing_stem(tmp_path):
    training = tmp_path / "docs/benchmarks/training"
    training.mkdir(parents=True)
    record = training / "20260906-thumbnail-competitor-winner-id.md"
    record.write_text("original", encoding="utf-8")
    draft = tmp_path / "draft.md"
    draft.write_text(_draft(), encoding="utf-8")

    with pytest.raises(ValidationError, match="既に存在"):
        seal_training_record(_pair(), draft, tmp_path, now=datetime(2026, 9, 6, tzinfo=UTC))

    assert record.read_text(encoding="utf-8") == "original"
    assert draft.exists()


def test_verify_detects_tampering(tmp_path):
    draft = tmp_path / "draft.md"
    draft.write_text(_draft(), encoding="utf-8")
    result = seal_training_record(_pair(), draft, tmp_path, now=datetime(2026, 9, 6, tzinfo=UTC))
    result.sealed.write_text(_draft() + "tampered", encoding="utf-8")

    verification = verify_training_record(result.record)

    assert verification.ok is False
    assert verification.expected != verification.actual
