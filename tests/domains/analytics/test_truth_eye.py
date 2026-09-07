from __future__ import annotations

import hashlib
from dataclasses import asdict
from datetime import UTC, date, datetime

import pytest
import yaml

from youtube_automation.core.errors import ConfigError, ValidationError
from youtube_automation.domains.analytics.truth_eye import (
    PAIR_THRESHOLDS,
    TRAINING_RECORD_SCHEMA_VERSION,
    VIEWPOINTS,
    collect_training_status,
    read_training_record,
    seal_training_record,
    select_pair_candidates,
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


def test_pair_thresholds_are_a_single_constant_table():
    assert asdict(PAIR_THRESHOLDS) == {
        "gap_days": (5, 14, 30),
        "maturity_days": 14,
        "min_ratio": 3,
        "min_loser_views": 100,
        "min_pool_size": 10,
        "max_rejections": 3,
    }


def test_pair_candidates_apply_thresholds_gap_tier_and_rotation(tmp_path):
    def competitor(slug, winner_date, loser_date, sessions=0):
        videos = [
            {
                "video_id": f"{slug}-w",
                "title": "Winner",
                "views": 3000,
                "published_at": winner_date,
                "duration_iso": "PT10M",
                "thumbnail_url": "w",
            },
            {
                "video_id": f"{slug}-l",
                "title": "Loser",
                "views": 100,
                "published_at": loser_date,
                "duration_iso": "PT10M",
                "thumbnail_url": "l",
            },
        ]
        videos.extend(
            {
                "video_id": f"{slug}-{index}",
                "title": "middle",
                "views": 500,
                "published_at": "2026-01-01",
                "duration_iso": "PT10M",
                "thumbnail_url": "m",
            }
            for index in range(8)
        )
        thumbs = tmp_path / slug
        thumbs.mkdir()
        for video in videos:
            (thumbs / f"{slug}_{video['video_id']}.jpg").write_bytes(b"jpg")
        return {
            "id": f"UC-{slug}",
            "slug": slug,
            "name": slug,
            "source": "self",
            "videos": videos,
            "thumbnails_dir": thumbs,
            "past_sessions": sessions,
        }

    result = select_pair_candidates(
        [competitor("a", "2026-08-01", "2026-07-20"), competitor("b", "2026-08-01", "2026-07-29", sessions=2)],
        used_video_ids=set(),
        rejected_video_ids=(),
        today=date(2026, 9, 6),
    )

    assert [candidate["competitor"]["slug"] for candidate in result["candidates"]] == ["b"]
    assert result["candidates"][0]["reason"]["gap_tier"] == 5
    assert result["candidates"][0]["winner"]["duration"] == "PT10M"


def test_pair_candidate_excludes_used_missing_image_and_three_rejections(tmp_path, monkeypatch):
    def never_download(*args, **kwargs):
        raise AssertionError("画像欠落の候補でネットワーク取得を呼んではいけません")

    monkeypatch.setattr("urllib.request.urlretrieve", never_download)
    monkeypatch.setattr("urllib.request.urlopen", never_download)
    videos = [
        {
            "video_id": "win",
            "title": "W",
            "views": 3000,
            "published_at": "2026-08-01",
            "duration_iso": "PT10M",
            "thumbnail_url": "w",
        },
        {
            "video_id": "lose",
            "title": "L",
            "views": 100,
            "published_at": "2026-07-30",
            "duration_iso": "PT10M",
            "thumbnail_url": "l",
        },
    ]
    videos += [
        {
            "video_id": f"m{i}",
            "title": "M",
            "views": 500,
            "published_at": "2026-01-01",
            "duration_iso": "PT10M",
            "thumbnail_url": "m",
        }
        for i in range(8)
    ]
    competitor = {
        "id": "UC",
        "slug": "ref",
        "name": "Ref",
        "source": "self",
        "videos": videos,
        "thumbnails_dir": tmp_path,
        "past_sessions": 0,
    }

    missing = select_pair_candidates([competitor], set(), (), date(2026, 9, 6))
    used = select_pair_candidates([competitor], {"win"}, (), date(2026, 9, 6))
    rejected = select_pair_candidates([competitor], set(), ("a", "b", "c"), date(2026, 9, 6))

    assert missing["candidates"] == []
    assert any(row["stage"] == "画像欠落除外後" for row in missing["funnel"])
    assert used["candidates"] == []
    assert rejected["candidates"] == []


_FILLER_VIEWS = (110, 120, 130, 140, 150, 160, 170, 180, 190)


def _pair_competitor(
    tmp_path,
    slug: str = "ref",
    *,
    filler_views: tuple[int, ...] = _FILLER_VIEWS,
    winner_views: int = 300,
    loser_views: int = 100,
    winner_duration: str = "PT10M",
    loser_published: str = "2026-07-30",
    past_sessions: int = 0,
    with_thumbnails: bool = True,
) -> dict:
    """走査プール中央値 150・比率ちょうど 3 倍・日差 2 日の基準競合を組み立てる。"""

    def video(video_id: str, views: int, published_at: str, duration_iso: str) -> dict:
        return {
            "video_id": video_id,
            "title": video_id,
            "views": views,
            "published_at": published_at,
            "duration_iso": duration_iso,
            "thumbnail_url": f"https://example.invalid/{video_id}.jpg",
        }

    videos = [
        video(f"{slug}-w", winner_views, "2026-08-01", winner_duration),
        video(f"{slug}-l", loser_views, loser_published, "PT10M"),
        *(video(f"{slug}-f{index}", views, "2026-01-01", "PT10M") for index, views in enumerate(filler_views)),
    ]
    thumbnails = tmp_path / f"thumbs-{slug}"
    thumbnails.mkdir()
    if with_thumbnails:
        for item in videos:
            (thumbnails / f"{slug}_{item['video_id']}.jpg").write_bytes(b"jpg")
    return {
        "id": f"UC-{slug}",
        "slug": slug,
        "name": slug,
        "source": "self",
        "videos": videos,
        "thumbnails_dir": thumbnails,
        "past_sessions": past_sessions,
    }


@pytest.mark.parametrize(
    ("case", "overrides", "today", "used_video_ids", "expected"),
    [
        ("基準", {}, date(2026, 9, 6), set(), 1),
        ("13 日経過", {}, date(2026, 8, 14), set(), 0),
        ("14 日経過", {}, date(2026, 8, 15), set(), 1),
        ("2.9 倍", {"winner_views": 290}, date(2026, 9, 6), set(), 0),
        ("3.0 倍", {"winner_views": 300}, date(2026, 9, 6), set(), 1),
        ("99 再生", {"loser_views": 99}, date(2026, 9, 6), set(), 0),
        ("伸びた側が中央値未満", {"filler_views": (500,) * 9, "winner_views": 400}, date(2026, 9, 6), set(), 0),
        (
            "伸びなかった側が中央値超",
            {"filler_views": (100,) * 9, "winner_views": 3000, "loser_views": 200},
            date(2026, 9, 6),
            set(),
            0,
        ),
        ("Shorts", {"winner_duration": "PT4M59S"}, date(2026, 9, 6), set(), 0),
        ("ライブ", {"winner_duration": "P0D"}, date(2026, 9, 6), set(), 0),
        ("走査プール 9 本", {"filler_views": _FILLER_VIEWS[:7]}, date(2026, 9, 6), set(), 0),
        ("走査プール 10 本", {"filler_views": _FILLER_VIEWS[:8]}, date(2026, 9, 6), set(), 1),
        ("既出", {}, date(2026, 9, 6), {"ref-w"}, 0),
        ("既出（伸びなかった側）", {}, date(2026, 9, 6), {"ref-l"}, 0),
        ("日差 31 日", {"loser_published": "2026-07-01"}, date(2026, 9, 6), set(), 0),
        ("日差 30 日", {"loser_published": "2026-07-02"}, date(2026, 9, 6), set(), 1),
    ],
)
def test_pair_candidate_boundaries_drop_pairs_that_just_miss_each_threshold(
    tmp_path, case, overrides, today, used_video_ids, expected
):
    result = select_pair_candidates([_pair_competitor(tmp_path, **overrides)], used_video_ids, (), today)

    assert len(result["candidates"]) == expected, case


def test_pair_order_prefers_gap_tier_then_fewest_sessions_then_ratio(tmp_path):
    competitors = [
        _pair_competitor(tmp_path, "veteran", winner_views=500, past_sessions=2),
        _pair_competitor(tmp_path, "low-ratio", winner_views=400),
        _pair_competitor(tmp_path, "high-ratio", winner_views=600),
        _pair_competitor(tmp_path, "wide-gap", winner_views=500, loser_published="2026-07-22"),
    ]

    result = select_pair_candidates(competitors, set(), (), date(2026, 9, 6))

    assert [candidate["competitor"]["slug"] for candidate in result["candidates"]] == [
        "high-ratio",
        "low-ratio",
        "veteran",
    ]
    assert [candidate["reason"]["ratio"] for candidate in result["candidates"]] == [6.0, 4.0, 5.0]
    assert result["funnel"] == [
        {"stage": "母集団", "count": 4},
        {"stage": "最小プール通過", "count": 4},
        {"stage": "5 日段", "count": 3},
        {"stage": "既出除外後", "count": 3},
        {"stage": "画像欠落除外後", "count": 3},
        {"stage": "却下後", "count": 3},
    ]


def test_pair_candidates_advance_gap_tier_when_nearer_pairs_are_used(tmp_path):
    competitors = [
        _pair_competitor(tmp_path, "used-near"),
        _pair_competitor(tmp_path, "unseen-wide", loser_published="2026-07-22"),
    ]

    result = select_pair_candidates(competitors, {"used-near-w"}, (), date(2026, 9, 6))

    assert [candidate["competitor"]["slug"] for candidate in result["candidates"]] == ["unseen-wide"]
    assert result["candidates"][0]["reason"]["gap_tier"] == 14


def test_bottleneck_advice_is_specific_to_the_stage_that_dropped_the_most(tmp_path):
    today = date(2026, 9, 6)
    no_image = [_pair_competitor(tmp_path, "no-image", with_thumbnails=False)]
    tiny_pool = [_pair_competitor(tmp_path, "tiny", filler_views=_FILLER_VIEWS[:7])]

    missing_image = select_pair_candidates(no_image, set(), (), today)
    seen = select_pair_candidates([_pair_competitor(tmp_path, "seen")], {"seen-w"}, (), today)
    rejected = select_pair_candidates([_pair_competitor(tmp_path, "rej")], set(), ("a", "b", "c"), today)
    small_pool = select_pair_candidates(tiny_pool, set(), (), today)
    results = (missing_image, seen, rejected, small_pool)

    assert missing_image["bottleneck"]["stage"] == "画像欠落除外後"
    assert "yt-benchmark-collect --force -y" in missing_image["bottleneck"]["advice"]
    assert seen["bottleneck"]["stage"] == "既出除外後"
    assert "兄弟チャンネル連携" in seen["bottleneck"]["advice"]
    assert rejected["funnel"][-1] == {"stage": "却下後", "count": 0}
    assert rejected["bottleneck"]["stage"] == "却下後"
    assert "次のセッション" in rejected["bottleneck"]["advice"]
    assert small_pool["bottleneck"]["stage"] == "最小プール通過"
    assert "channel-research --benchmark" in small_pool["bottleneck"]["advice"]
    assert len({result["bottleneck"]["advice"] for result in results}) == 4
