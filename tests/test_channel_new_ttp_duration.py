from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT_PATH = (
    Path(__file__).parents[1] / ".claude" / "skills" / "channel-new" / "references" / "derive_ttp_duration.py"
)
_SPEC = importlib.util.spec_from_file_location("derive_ttp_duration", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
duration = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(duration)


def _video(video_id: str, views: int, duration_iso: str) -> dict[str, object]:
    return {
        "video_id": video_id,
        "views": views,
        "duration_iso": duration_iso,
        "duration_display": duration_iso,
    }


def _benchmark(slug: str, videos: list[dict[str, object]]) -> dict[str, object]:
    return {"channels": [{"slug": slug, "name": slug.title(), "videos": videos}]}


def _approved(slug: str = "rival") -> list[dict[str, object]]:
    return [{"id": "UC123", "slug": slug, "name": "Rival", "relationship": "duration"}]


def test_derives_top_long_vod_range_and_records_short_and_live_exclusions() -> None:
    report = duration.derive_ttp_duration(
        _benchmark(
            "rival",
            [
                _video("LIVE", 100_000, "P0D"),
                _video("SHORT", 90_000, "PT4M59S"),
                _video("A", 80_000, "PT61M30S"),
                _video("B", 70_000, "PT2H0M1S"),
                _video("C", 60_000, "PT90M"),
                _video("D", 50_000, "PT75M"),
                _video("E", 40_000, "PT80M"),
                _video("F", 30_000, "PT3H"),
            ],
        ),
        _approved(),
    )

    assert report["status"] == "ok"
    assert report["target_duration_min"] == 61
    assert report["target_duration_max"] == 121
    channel = report["channels"][0]
    assert [video["video_id"] for video in channel["selected"]] == ["A", "B", "C", "D", "E"]
    assert [(video["video_id"], video["reason"]) for video in channel["excluded"]] == [
        ("LIVE", "live"),
        ("SHORT", "short"),
    ]


def test_combines_each_approved_channels_five_videos_for_outer_range() -> None:
    benchmark = {
        "channels": [
            {
                "slug": "first",
                "videos": [_video(f"A{i}", 100 - i, f"PT{60 + i}M") for i in range(5)],
            },
            {
                "slug": "second",
                "videos": [_video(f"B{i}", 100 - i, f"PT{120 + i}M30S") for i in range(5)],
            },
        ]
    }

    report = duration.derive_ttp_duration(
        benchmark,
        [
            {"id": "UC1", "slug": "first", "name": "First"},
            {"id": "UC2", "slug": "second", "name": "Second"},
        ],
    )

    assert report["status"] == "ok"
    assert report["target_duration_min"] == 60
    assert report["target_duration_max"] == 125
    assert [len(channel["selected"]) for channel in report["channels"]] == [5, 5]


def test_insufficient_channel_fails_without_recommendation() -> None:
    report = duration.derive_ttp_duration(
        _benchmark("rival", [_video("A", 10, "PT1H")]),
        _approved(),
    )

    assert report["status"] == "insufficient"
    assert report["errors"] == ["rival: 有効な Long VOD が不足 (1/5)"]
    assert "target_duration_min" not in report
    assert "target_duration_max" not in report


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("PT1H2M3S", 3723),
        ("P1DT2H", 93_600),
        ("P0D", 0),
        ("invalid", None),
        ("", None),
    ],
)
def test_parse_duration_seconds(value: str, expected: int | None) -> None:
    assert duration.parse_duration_seconds(value) == expected


def test_apply_updates_only_audio_duration_fields(tmp_path: Path) -> None:
    audio_path = tmp_path / "config" / "channel" / "audio.json"
    audio_path.parent.mkdir(parents=True)
    audio_path.write_text(
        json.dumps({"audio": {"target_duration_min": None, "target_duration_max": None, "bitrate": 320}}),
        encoding="utf-8",
    )

    result = duration.apply_duration_recommendation(
        tmp_path,
        {"status": "ok", "target_duration_min": 61, "target_duration_max": 121},
    )

    assert result == audio_path
    assert json.loads(audio_path.read_text(encoding="utf-8")) == {
        "audio": {"target_duration_min": 61.0, "target_duration_max": 121.0, "bitrate": 320}
    }


def test_skill_documents_dry_run_approval_apply_and_exception_contract() -> None:
    skill = (_SCRIPT_PATH.parent.parent / "SKILL.md").read_text(encoding="utf-8")

    assert "### Step 5.5: TTP Long VOD から動画尺を導出・承認" in skill
    assert "derive_ttp_duration.py" in skill
    assert "--apply" in skill
    assert "duration selected video" in skill
    assert "ユーザー承認済み例外: duration" in skill
    assert "/benchmark" in skill
