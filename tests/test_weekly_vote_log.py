"""Weekly vote log domain のユニットテスト (#509)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from youtube_automation.domains.collections.weekly_vote_log import (
    WEEKLY_VOTE_LOG_SCHEMA_VERSION,
    AxisVote,
    WeeklyVoteEntry,
    WeeklyVoteLog,
    append_weekly_vote_entry,
    compute_vote_log_weights,
    load_weekly_vote_log,
    load_weekly_vote_log_schema,
    poll_deprecation_message,
    save_weekly_vote_log,
    validate_weekly_vote_log,
    warn_poll_deprecated,
)
from youtube_automation.utils.exceptions import ConfigError, ValidationError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_axes(*pairs: tuple[str, int]) -> list[AxisVote]:
    return [AxisVote(key=k, label=k.replace("_", " ").title(), votes=v) for k, v in pairs]


def _entry(week_start: str, *pairs: tuple[str, int]) -> WeeklyVoteEntry:
    axes = _make_axes(*pairs)
    top_axis = max(axes, key=lambda a: a.votes).key
    total = sum(a.votes for a in axes)
    return WeeklyVoteEntry(
        week_start=week_start,
        axes=tuple(axes),
        top_axis=top_axis,
        total_votes=total,
    )


# ---------------------------------------------------------------------------
# validate_weekly_vote_log
# ---------------------------------------------------------------------------


def test_validate_minimal_payload():
    payload = {
        "schema_version": 1,
        "entries": [
            {
                "week_start": "2026-05-04",
                "axes": [
                    {"key": "rain_window", "label": "Rain Window", "votes": 10},
                    {"key": "midnight_drive", "label": "Midnight Drive", "votes": 5},
                ],
                "top_axis": "rain_window",
            }
        ],
    }
    log = validate_weekly_vote_log(payload)
    assert log.schema_version == 1
    assert len(log.entries) == 1
    entry = log.entries[0]
    assert entry.top_axis == "rain_window"
    assert entry.total_votes == 15  # 自動補完


def test_validate_rejects_unknown_schema_version():
    with pytest.raises(ValidationError, match="schema_version"):
        validate_weekly_vote_log({"schema_version": 999, "entries": []})


def test_validate_rejects_total_votes_mismatch():
    payload = {
        "schema_version": 1,
        "entries": [
            {
                "week_start": "2026-05-04",
                "axes": [
                    {"key": "a", "label": "A", "votes": 10},
                    {"key": "b", "label": "B", "votes": 5},
                ],
                "top_axis": "a",
                "total_votes": 100,
            }
        ],
    }
    with pytest.raises(ValidationError, match="total_votes"):
        validate_weekly_vote_log(payload)


def test_validate_rejects_top_axis_not_in_axes():
    payload = {
        "schema_version": 1,
        "entries": [
            {
                "week_start": "2026-05-04",
                "axes": [{"key": "a", "label": "A", "votes": 10}],
                "top_axis": "missing",
            }
        ],
    }
    with pytest.raises(ValidationError, match="top_axis"):
        validate_weekly_vote_log(payload)


def test_validate_rejects_duplicate_axis_keys():
    payload = {
        "schema_version": 1,
        "entries": [
            {
                "week_start": "2026-05-04",
                "axes": [
                    {"key": "a", "label": "A", "votes": 1},
                    {"key": "a", "label": "A bis", "votes": 2},
                ],
                "top_axis": "a",
            }
        ],
    }
    with pytest.raises(ValidationError, match="重複"):
        validate_weekly_vote_log(payload)


def test_validate_rejects_duplicate_week_start():
    payload = {
        "schema_version": 1,
        "entries": [
            {
                "week_start": "2026-05-04",
                "axes": [{"key": "a", "label": "A", "votes": 1}],
                "top_axis": "a",
            },
            {
                "week_start": "2026-05-04",
                "axes": [{"key": "b", "label": "B", "votes": 2}],
                "top_axis": "b",
            },
        ],
    }
    with pytest.raises(ValidationError, match="week_start"):
        validate_weekly_vote_log(payload)


def test_validate_rejects_bad_date_format():
    payload = {
        "schema_version": 1,
        "entries": [
            {
                "week_start": "2026/05/04",  # 非 ISO
                "axes": [{"key": "a", "label": "A", "votes": 1}],
                "top_axis": "a",
            }
        ],
    }
    with pytest.raises(ValidationError, match="ISO 8601"):
        validate_weekly_vote_log(payload)


def test_validate_rejects_negative_votes():
    payload = {
        "schema_version": 1,
        "entries": [
            {
                "week_start": "2026-05-04",
                "axes": [{"key": "a", "label": "A", "votes": -1}],
                "top_axis": "a",
            }
        ],
    }
    with pytest.raises(ValidationError, match="votes"):
        validate_weekly_vote_log(payload)


# ---------------------------------------------------------------------------
# load / save
# ---------------------------------------------------------------------------


def test_load_missing_returns_empty_when_missing_ok(tmp_path: Path):
    log = load_weekly_vote_log(channel_dir=tmp_path, missing_ok=True)
    assert log.entries == ()
    assert log.schema_version == WEEKLY_VOTE_LOG_SCHEMA_VERSION


def test_load_missing_raises_config_error(tmp_path: Path):
    with pytest.raises(ConfigError, match="見つかりません"):
        load_weekly_vote_log(channel_dir=tmp_path, missing_ok=False)


def test_load_invalid_json_raises(tmp_path: Path):
    target = tmp_path / "data" / "community" / "weekly-vote-log.json"
    target.parent.mkdir(parents=True)
    target.write_text("{invalid", encoding="utf-8")
    with pytest.raises(ConfigError, match="JSON"):
        load_weekly_vote_log(channel_dir=tmp_path)


def test_save_then_load_roundtrip(tmp_path: Path):
    log = WeeklyVoteLog(
        entries=(_entry("2026-05-04", ("rain_window", 10), ("midnight_drive", 5)),),
    )
    saved = save_weekly_vote_log(log, channel_dir=tmp_path)
    assert saved.exists()
    reloaded = load_weekly_vote_log(channel_dir=tmp_path)
    assert reloaded.entries == log.entries


def test_load_supports_custom_path(tmp_path: Path):
    custom = tmp_path / "alt" / "log.json"
    log = WeeklyVoteLog(entries=(_entry("2026-05-04", ("a", 1)),))
    save_weekly_vote_log(log, channel_dir=tmp_path, path=custom)
    assert custom.exists()
    reloaded = load_weekly_vote_log(channel_dir=tmp_path, path=custom)
    assert reloaded.entries[0].top_axis == "a"


# ---------------------------------------------------------------------------
# append_weekly_vote_entry
# ---------------------------------------------------------------------------


def test_append_creates_file_when_missing(tmp_path: Path):
    log = append_weekly_vote_entry(
        channel_dir=tmp_path,
        week_start="2026-05-04",
        axes=[AxisVote("rain_window", "Rain Window", 12), AxisVote("midnight_drive", "Midnight Drive", 7)],
    )
    assert len(log.entries) == 1
    entry = log.entries[0]
    assert entry.top_axis == "rain_window"
    assert entry.total_votes == 19


def test_append_accepts_date_object(tmp_path: Path):
    log = append_weekly_vote_entry(
        channel_dir=tmp_path,
        week_start=date(2026, 5, 4),
        axes=[{"key": "a", "label": "A", "votes": 3}],
    )
    assert log.entries[0].week_start == "2026-05-04"


def test_append_collision_without_replace_raises(tmp_path: Path):
    append_weekly_vote_entry(
        channel_dir=tmp_path,
        week_start="2026-05-04",
        axes=[AxisVote("a", "A", 1)],
    )
    with pytest.raises(ValidationError, match="衝突"):
        append_weekly_vote_entry(
            channel_dir=tmp_path,
            week_start="2026-05-04",
            axes=[AxisVote("b", "B", 2)],
        )


def test_append_replace_overwrites(tmp_path: Path):
    append_weekly_vote_entry(
        channel_dir=tmp_path,
        week_start="2026-05-04",
        axes=[AxisVote("a", "A", 1)],
    )
    log = append_weekly_vote_entry(
        channel_dir=tmp_path,
        week_start="2026-05-04",
        axes=[AxisVote("b", "B", 5)],
        replace=True,
    )
    assert len(log.entries) == 1
    assert log.entries[0].top_axis == "b"


def test_append_empty_axes_raises(tmp_path: Path):
    with pytest.raises(ValidationError, match="axes"):
        append_weekly_vote_entry(
            channel_dir=tmp_path,
            week_start="2026-05-04",
            axes=[],
        )


def test_append_sorts_entries_by_week_start(tmp_path: Path):
    append_weekly_vote_entry(
        channel_dir=tmp_path,
        week_start="2026-05-11",
        axes=[AxisVote("b", "B", 4)],
    )
    log = append_weekly_vote_entry(
        channel_dir=tmp_path,
        week_start="2026-05-04",
        axes=[AxisVote("a", "A", 9)],
    )
    assert [e.week_start for e in log.entries] == ["2026-05-04", "2026-05-11"]


# ---------------------------------------------------------------------------
# compute_vote_log_weights
# ---------------------------------------------------------------------------


def test_weights_returns_decayed_sum():
    log = WeeklyVoteLog(
        entries=(
            _entry("2026-05-04", ("rain_window", 10), ("midnight_drive", 5)),  # top rain_window
            _entry("2026-05-11", ("rain_window", 8), ("midnight_drive", 12)),  # top midnight_drive
            _entry("2026-05-18", ("rain_window", 9), ("midnight_drive", 7)),  # top rain_window
        )
    )
    result = compute_vote_log_weights(log, recent_weeks=3, decay=0.5)
    # 最新 (idx0) は 2026-05-18 → rain_window weight=1.0
    # idx1 (2026-05-11) → midnight_drive weight=0.5
    # idx2 (2026-05-04) → rain_window weight=0.25
    assert result.considered_weeks == 3
    assert result.weights["rain_window"] == pytest.approx(1.25)
    assert result.weights["midnight_drive"] == pytest.approx(0.5)
    assert result.forced_axis is None  # 直近 2 週 (05-18, 05-11) は別軸


def test_weights_detects_forced_axis_on_two_week_streak():
    log = WeeklyVoteLog(
        entries=(
            _entry("2026-05-04", ("a", 1), ("b", 5)),  # top b
            _entry("2026-05-11", ("a", 9), ("b", 1)),  # top a
            _entry("2026-05-18", ("a", 12), ("b", 3)),  # top a (連続 2 週で a が top)
        )
    )
    result = compute_vote_log_weights(log, recent_weeks=3)
    assert result.forced_axis == "a"
    assert result.forced_streak == 2


def test_weights_detects_three_week_streak():
    log = WeeklyVoteLog(
        entries=(
            _entry("2026-05-04", ("a", 7), ("b", 3)),
            _entry("2026-05-11", ("a", 8), ("b", 2)),
            _entry("2026-05-18", ("a", 9), ("b", 1)),
        )
    )
    result = compute_vote_log_weights(log, recent_weeks=3)
    assert result.forced_axis == "a"
    assert result.forced_streak == 3


def test_weights_with_less_than_threshold_returns_no_forced():
    log = WeeklyVoteLog(
        entries=(_entry("2026-05-04", ("a", 5), ("b", 1)),)  # 1 週分のみ
    )
    result = compute_vote_log_weights(log, recent_weeks=4, forced_streak_threshold=2)
    assert result.forced_axis is None
    assert result.forced_streak == 0
    assert result.considered_weeks == 1


def test_weights_recent_weeks_bounds():
    log = WeeklyVoteLog(entries=(_entry("2026-05-04", ("a", 1)),))
    with pytest.raises(ValidationError):
        compute_vote_log_weights(log, recent_weeks=0)
    with pytest.raises(ValidationError):
        compute_vote_log_weights(log, recent_weeks=3, forced_streak_threshold=1)
    with pytest.raises(ValidationError):
        compute_vote_log_weights(log, recent_weeks=3, decay=0)
    with pytest.raises(ValidationError):
        compute_vote_log_weights(log, recent_weeks=3, decay=1.5)


def test_weights_no_entries():
    result = compute_vote_log_weights(WeeklyVoteLog(), recent_weeks=4)
    assert result.weights == {}
    assert result.forced_axis is None
    assert result.considered_weeks == 0


def test_recent_returns_in_descending_order():
    log = WeeklyVoteLog(
        entries=(
            _entry("2026-05-04", ("a", 1)),
            _entry("2026-05-11", ("a", 2)),
            _entry("2026-05-18", ("a", 3)),
        )
    )
    recent = log.recent(2)
    assert [e.week_start for e in recent] == ["2026-05-18", "2026-05-11"]


# ---------------------------------------------------------------------------
# schema / deprecation helpers
# ---------------------------------------------------------------------------


def test_load_weekly_vote_log_schema_returns_dict():
    schema = load_weekly_vote_log_schema()
    assert schema["title"] == "WeeklyVoteLog"
    assert schema["properties"]["schema_version"]["const"] == WEEKLY_VOTE_LOG_SCHEMA_VERSION


def test_poll_deprecation_message_is_actionable():
    msg = poll_deprecation_message()
    assert "DEPRECATED" in msg
    assert "/community-draft --batch" in msg
    assert "yt-vote-log append" in msg


def test_warn_poll_deprecated_emits_warning(caplog):
    import logging as _logging

    with caplog.at_level(_logging.WARNING):
        warn_poll_deprecated()
    assert any("DEPRECATED" in record.message for record in caplog.records)


def test_validate_via_schema_loaded_json_matches_validator(tmp_path: Path):
    # 別経路 (file roundtrip) でも schema_version=1 を維持して読めること
    log = WeeklyVoteLog(
        entries=(_entry("2026-05-04", ("a", 3), ("b", 2)),),
    )
    save_weekly_vote_log(log, channel_dir=tmp_path)
    raw = json.loads((tmp_path / "data" / "community" / "weekly-vote-log.json").read_text())
    assert raw["schema_version"] == WEEKLY_VOTE_LOG_SCHEMA_VERSION
    assert raw["entries"][0]["top_axis"] == "a"
