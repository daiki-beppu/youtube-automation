from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
import yaml

from youtube_automation.core.errors import ConfigError, ValidationError
from youtube_automation.domains.analytics.truth_eye import (
    TRAINING_RECORD_SCHEMA_VERSION,
    VIEWPOINTS,
    collect_training_status,
    read_training_record,
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
    assert metadata["schema_version"] == TRAINING_RECORD_SCHEMA_VERSION
    assert read_training_record(record).metadata == metadata
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


def _record(*, next_try=None, phases=None) -> str:
    metadata = {
        "schema_version": TRAINING_RECORD_SCHEMA_VERSION,
        "menu": "thumbnail",
        "channel": "reference",
        "pair": {"winner": {"video_id": "win"}, "loser": {"video_id": "lose"}},
        "sealed": {"path": "record.sealed.md", "sha256": "abc", "sealed_at": "2026-09-01T00:00:00Z"},
        "next_try": next_try,
    }
    contents = phases or {}
    body = "\n\n".join(f"## Phase {number}\n\n{contents.get(number, '')}" for number in range(6))
    return f"---\n{yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False)}---\n\n{body}\n"


def test_status_finds_resume_phase_and_phase_two_turns(tmp_path):
    training = tmp_path / "docs/benchmarks/training"
    training.mkdir(parents=True)
    phase_one_table = (
        "| 観点 ID | 観点名 | 伸びた側 | 伸びなかった側 |\n"
        "|---|---|---|---|\n"
        "| V01 | 主役と占有率 | large subject | small subject |"
    )
    (training / "20260901-thumbnail-reference-a.md").write_text(_record(phases={0: "prepared"}), encoding="utf-8")
    (training / "20260902-thumbnail-reference-b.md").write_text(
        _record(phases={0: "prepared", 1: phase_one_table}), encoding="utf-8"
    )
    (training / "20260903-thumbnail-reference-c.md").write_text(
        _record(
            phases={
                0: "prepared",
                1: phase_one_table,
                2: "Q: first\nA: one\n\nQ: second\nA: two\n\nQ: third\nA: three",
            }
        ),
        encoding="utf-8",
    )
    (training / "20260904-thumbnail-reference-d.md").write_text(
        _record(phases={number: f"phase {number}" for number in range(6)}), encoding="utf-8"
    )

    status = collect_training_status(tmp_path)

    assert [(item.record.name, item.resume_phase, item.phase2_turns) for item in status.incomplete] == [
        ("20260901-thumbnail-reference-a.md", 1, 0),
        ("20260902-thumbnail-reference-b.md", 2, 0),
        ("20260903-thumbnail-reference-c.md", 3, 3),
        ("20260904-thumbnail-reference-d.md", 5, 0),
    ]


def test_status_stops_on_unknown_schema_version(tmp_path):
    training = tmp_path / "docs/benchmarks/training"
    training.mkdir(parents=True)
    unknown = TRAINING_RECORD_SCHEMA_VERSION + 1
    record = training / "20260901-thumbnail-reference-a.md"
    record.write_text(
        _record(phases={0: "prepared"}).replace(
            f"schema_version: {TRAINING_RECORD_SCHEMA_VERSION}", f"schema_version: {unknown}"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match=f"schema_version.*{unknown}"):
        read_training_record(record)
    with pytest.raises(ConfigError, match="schema_version"):
        collect_training_status(tmp_path)


def test_status_returns_latest_next_try_and_recurring_ai_only_names_only(tmp_path):
    training = tmp_path / "docs/benchmarks/training"
    training.mkdir(parents=True)
    table = (
        "| 観点 ID | 区分 | 人間の記述 | AI の記述 |\n"
        "|---|---|---|---|\n"
        "| V03 | AI だけ | human | secret-ai-description |\n"
        "| V09 | 対立 | human | another-secret |"
    )
    for day in range(1, 7):
        next_try = {"viewpoint": "V03", "text": f"try-{day}"}
        phase4 = table if day >= 3 else "| V01 | 一致 | x | y |"
        (training / f"2026090{day}-thumbnail-reference-{day}.md").write_text(
            _record(next_try=next_try, phases={4: phase4}), encoding="utf-8"
        )
    (training / "20260907-thumbnail-reference-incomplete.md").write_text(
        _record(phases={4: table.replace("V03", "V09").replace("対立", "AI だけ")}), encoding="utf-8"
    )
    (training / "20260908-thumbnail-reference-ignore.sealed.md").write_text(
        _record(next_try={"viewpoint": "V01", "text": "sealed"}, phases={4: table}), encoding="utf-8"
    )
    sibling = tmp_path / "../sibling/docs/benchmarks/training"
    sibling.mkdir(parents=True)
    (sibling / "20260909-thumbnail-reference-sibling.md").write_text(
        _record(next_try={"viewpoint": "V01", "text": "sibling"}, phases={4: table}), encoding="utf-8"
    )

    status = collect_training_status(tmp_path)

    assert status.completed_count == 6
    assert status.incomplete_count == 1
    assert status.last_next_try == {"viewpoint": "V03", "text": "try-6"}
    assert status.recurring_ai_only_viewpoints == ({"viewpoint_id": "V03", "name": "配色", "count": 4},)
    assert "secret" not in repr(status.recurring_ai_only_viewpoints)
