from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from youtube_automation.commands.analytics import win_pattern as cli
from youtube_automation.core.errors import ValidationError
from youtube_automation.infrastructure.analytics.win_pattern import (
    VISUAL_ATTRIBUTES,
    aggregate_patterns,
    build_automatic_attributes,
    build_win_pattern_result,
    evaluate_pattern,
    load_annotations,
    validate_ranking,
)


def _item(video_id: str, title: str = "Focus Mix", published_at: str = "2026-08-10T12:00:00Z") -> dict:
    return {
        "video_id": video_id,
        "title": title,
        "published_at": published_at,
        "cumulative_views": 100,
        "days_since_publish": 10,
        "vpd": 10.0,
    }


def _ranking(top: list[dict], middle: list[dict], bottom: list[dict]) -> dict:
    ordered = [*top, *middle, *bottom]
    k = len(top)
    return {
        "n": len(ordered),
        "k": k,
        "min_age_days": 7,
        "excluded_count": 0,
        "ranking": ordered,
        "groups": {
            "top": {"count": k, "items": top},
            "middle": {"count": len(middle), "items": middle},
            "bottom": {"count": len(bottom), "items": bottom},
        },
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda result: result.update(n=5),
        lambda result: result.update(k=2),
        lambda result: result["groups"]["bottom"]["items"].append(result["groups"]["top"]["items"][0]),
        lambda result: result["groups"]["middle"]["items"].clear(),
    ],
)
def test_ranking_inconsistency_overlap_or_gap_fails_closed(mutate) -> None:
    result = _ranking([_item("top")], [_item("middle")], [_item("bottom")])
    mutate(result)

    with pytest.raises(ValidationError, match="ranking|group|n|k"):
        validate_ranking(result)


def test_automatic_attributes_use_theme_first_regex_duration_and_utc_publish_bins() -> None:
    videos = [
        _item("a", "Night Focus Question?", "2026-08-10T23:30:00-05:00"),
        _item("b", "Other", "2026-08-10T05:59:00Z"),
    ]
    details = {"a": {"duration": "PT59S"}, "b": {"duration": "PT1H"}}

    result = build_automatic_attributes(
        videos,
        details=details,
        theme_keywords={"focus": ["night"]},
        title_patterns=[{"name": "question", "regex": r"[?？]"}],
    )

    assert result["theme"] == {"a": "focus", "b": "other"}
    assert result["title_pattern"] == {"a": "question", "b": "other"}
    assert result["duration"] == {"a": "under_60_seconds", "b": "3600_seconds_or_more"}
    assert result["publish_weekday"] == {"a": "Tuesday", "b": "Monday"}
    assert result["publish_time"] == {"a": "00:00-05:59", "b": "00:00-05:59"}


@pytest.mark.parametrize(
    ("duration", "expected"),
    [
        ("PT59S", "under_60_seconds"),
        ("PT1M", "60_to_599_seconds"),
        ("PT9M59S", "60_to_599_seconds"),
        ("PT10M", "600_to_3599_seconds"),
        ("PT59M59S", "600_to_3599_seconds"),
        ("PT1H", "3600_seconds_or_more"),
    ],
)
def test_duration_bins_have_explicit_inclusive_boundaries(duration: str, expected: str) -> None:
    result = build_automatic_attributes(
        [_item("a")],
        details={"a": {"duration": duration}},
        theme_keywords={},
        title_patterns=[],
    )

    assert result["duration"]["a"] == expected


@pytest.mark.parametrize(
    "patterns",
    [
        [{"name": "broken", "regex": "("}],
        [{"name": "", "regex": "x"}],
        [{"name": "x"}],
        {"name": "x", "regex": "x"},
    ],
)
def test_invalid_title_pattern_config_fails_loud(patterns: object) -> None:
    with pytest.raises(ValidationError, match="title_patterns"):
        build_automatic_attributes(
            [_item("a")],
            details={"a": {"duration": "PT1M"}},
            theme_keywords={},
            title_patterns=patterns,
        )


def test_annotations_are_strict_and_missing_values_are_undetermined(tmp_path: Path) -> None:
    path = tmp_path / "annotations.json"
    path.write_text(
        json.dumps({"videos": [{"video_id": "a", "composition": "centered", "color": None}]}),
        encoding="utf-8",
    )

    result = load_annotations(path, known_video_ids={"a", "b"})

    assert result["composition"] == {"a": "centered", "b": "undetermined"}
    assert result["color"] == {"a": "undetermined", "b": "undetermined"}
    assert set(result) == set(VISUAL_ATTRIBUTES)
    assert all(result[name]["b"] == "undetermined" for name in VISUAL_ATTRIBUTES)


@pytest.mark.parametrize(
    "payload",
    [
        {"videos": [{"video_id": "unknown", "composition": "centered"}]},
        {"videos": [{"video_id": "a", "composition": 1}]},
        {"videos": [{"video_id": "a", "unknown_axis": "x"}]},
        {"videos": [{"video_id": "a"}, {"video_id": "a"}]},
        {"videos": {}},
    ],
)
def test_invalid_annotation_or_unknown_video_id_fails_loud(tmp_path: Path, payload: object) -> None:
    path = tmp_path / "annotations.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError, match="annotation"):
        load_annotations(path, known_video_ids={"a"})


def test_visual_attributes_exist_as_undetermined_without_annotation_file() -> None:
    result = load_annotations(None, known_video_ids={"a", "b"})

    assert set(result) == set(VISUAL_ATTRIBUTES)
    assert all(set(values.values()) == {"undetermined"} for values in result.values())


def test_automatic_and_annotation_attributes_share_known_denominator_aggregator() -> None:
    ranking = _ranking(
        [_item(f"t{i}") for i in range(5)],
        [],
        [_item(f"b{i}") for i in range(5)],
    )
    values = {
        **{f"t{i}": "x" if i < 3 else "y" for i in range(5)},
        **{f"b{i}": "x" if i < 2 else "y" for i in range(5)},
    }

    automatic = aggregate_patterns(ranking, {"theme": values})
    annotation = aggregate_patterns(ranking, {"composition": values})

    assert automatic["theme"]["values"]["x"] == annotation["composition"]["values"]["x"]
    assert automatic["theme"]["values"]["x"]["classification"] == "win"
    assert automatic["theme"]["values"]["x"]["top_percentage"] == 60.0
    assert automatic["theme"]["values"]["x"]["bottom_percentage"] == 40.0
    assert automatic["theme"]["values"]["x"]["pp_difference"] == 20.0


def test_thresholds_are_inclusive_but_decisions_use_unrounded_ratios() -> None:
    assert evaluate_pattern(top_count=3, top_known=5, bottom_count=2, bottom_known=5) == "win"
    assert evaluate_pattern(top_count=2, top_known=5, bottom_count=3, bottom_known=5) == "loss"
    assert evaluate_pattern(top_count=60000, top_known=100000, bottom_count=40001, bottom_known=100000) == "hold"
    assert evaluate_pattern(top_count=0, top_known=0, bottom_count=0, bottom_known=1) == "hold"


def test_representative_ids_are_deterministic_and_output_has_correlation_disclaimer() -> None:
    ranking = _ranking([_item("z"), _item("a")], [], [_item("y"), _item("b")])
    attributes = {"theme": {video_id: "focus" for video_id in ("z", "a", "y", "b")}}

    result = build_win_pattern_result(ranking, attributes)

    record = result["attributes"]["theme"]["values"]["focus"]
    assert record["representative_video_ids"] == ["a", "b", "y", "z"]
    assert "correlation" in result["disclaimer"].lower()
    assert "causation" in result["disclaimer"].lower()


def test_json_and_text_render_the_same_result(monkeypatch, capsys) -> None:
    result = build_win_pattern_result(
        _ranking([_item("top")], [], [_item("bottom")]),
        {"theme": {"top": "focus", "bottom": "other"}},
    )
    monkeypatch.setattr(cli, "_load_result", lambda **_kwargs: result)

    assert cli.main([]) == 0
    json_result = json.loads(capsys.readouterr().out)
    assert cli.main(["--text"]) == 0
    text = capsys.readouterr().out

    assert json_result == result
    assert result["disclaimer"] in text
    assert "focus" in text


def test_offline_ranking_never_calls_live_loader(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "ranking.json"
    path.write_text(json.dumps(_ranking([_item("top")], [], [_item("bottom")])), encoding="utf-8")
    calls = 0

    def live_loader(**_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("offline mode must not load live ranking")

    monkeypatch.setattr(cli.vpd_rank, "_load_ranking", live_loader)
    monkeypatch.setattr(cli, "load_config", lambda: _config())
    monkeypatch.setattr(cli, "load_skill_config", lambda _name: {"win_pattern": {"title_patterns": []}})

    result = cli._load_result(ranking_path=path, annotations_path=None, min_age_days=7, top_count=None)

    assert result["n"] == 2
    assert calls == 0


def test_default_mode_calls_live_loader_exactly_once(monkeypatch) -> None:
    calls = 0

    def live_loader(**_kwargs):
        nonlocal calls
        calls += 1
        return _ranking([_item("top")], [], [_item("bottom")])

    monkeypatch.setattr(cli.vpd_rank, "_load_ranking", live_loader)
    monkeypatch.setattr(cli, "_load_live_details", lambda _ids: {})
    monkeypatch.setattr(cli, "load_config", lambda: _config())
    monkeypatch.setattr(cli, "load_skill_config", lambda _name: {"win_pattern": {"title_patterns": []}})

    result = cli._load_result(ranking_path=None, annotations_path=None, min_age_days=7, top_count=None)

    assert result["n"] == 2
    assert calls == 1


def _config():
    return SimpleNamespace(content=SimpleNamespace(tags=SimpleNamespace(themes={"focus": ["focus"]})))
