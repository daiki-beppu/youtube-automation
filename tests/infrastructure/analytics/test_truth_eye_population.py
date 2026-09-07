from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from youtube_automation.core.errors import ChannelRegistryError, ConfigError
from youtube_automation.infrastructure.analytics.truth_eye_population import load_truth_eye_population

SHARED_COMPETITOR = "UC-shared"
SIBLING_ONLY_COMPETITOR = "UC-sibling-only"
UNRELATED_COMPETITOR = "UC-unrelated"
REGISTRY_ATTRIBUTE = "youtube_automation.infrastructure.analytics.truth_eye_population.DEFAULT_CHANNEL_REGISTRY"


def _write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _scanned_channel(competitor_id: str, slug: str, *, old_shape: bool) -> dict:
    video = {
        "video_id": f"{slug}-video",
        "title": f"{slug} video",
        "published_at": "2026-08-01",
        "views": 1000,
        "duration_iso": "PT10M",
        "thumbnail_url": f"https://example.invalid/{slug}.jpg",
    }
    if old_shape:
        del video["video_id"]
    return {
        "channel_id": competitor_id,
        "slug": slug,
        "name": f"{slug} channel",
        "upload_scan": {"videos": [video]},
    }


def _repository(
    root: Path,
    name: str,
    competitors: list[tuple[str, str]],
    *,
    collected_on: date | None = None,
    old_shape_slug: str | None = None,
    with_benchmark_json: bool = True,
) -> Path:
    repository = root / name
    channels = [{"id": competitor_id, "slug": slug} for competitor_id, slug in competitors]
    _write_json(repository / "config" / "channel" / "analytics.json", {"benchmark": {"channels": channels}})
    if with_benchmark_json:
        collected = collected_on or date.today()
        scans = [
            _scanned_channel(competitor_id, slug, old_shape=slug == old_shape_slug)
            for competitor_id, slug in competitors
        ]
        _write_json(repository / "data" / f"benchmark_{collected:%Y%m%d}.json", {"channels": scans})
    return repository


def _registry(root: Path, repositories: list[Path], monkeypatch) -> None:
    path = root / "channels.json"
    _write_json(path, [str(repository) for repository in repositories])
    monkeypatch.setattr(REGISTRY_ATTRIBUTE, path)


def _without_registry(root: Path, monkeypatch) -> None:
    monkeypatch.setattr(REGISTRY_ATTRIBUTE, root / "missing" / "channels.json")


def _training_record(path: Path, channel: str, winner: str, loser: str) -> None:
    frontmatter = {
        "schema_version": 1,
        "menu": "thumbnail",
        "channel": channel,
        "pair": {"winner": {"video_id": winner}, "loser": {"video_id": loser}},
        "next_try": None,
    }
    body = "\n".join(f"## Phase {number}\n" for number in range(6))
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = json.dumps(frontmatter, ensure_ascii=False)
    path.write_text(f"---\n{metadata}\n---\n\n{body}", encoding="utf-8")


def test_sibling_joins_population_only_when_a_competitor_id_is_shared(tmp_path, monkeypatch):
    own = _repository(tmp_path, "self", [(SHARED_COMPETITOR, "shared")])
    sibling_competitors = [(SHARED_COMPETITOR, "shared-in-sibling"), (SIBLING_ONLY_COMPETITOR, "solo")]
    sibling = _repository(tmp_path, "sibling", sibling_competitors)
    unrelated = _repository(tmp_path, "unrelated", [(UNRELATED_COMPETITOR, "unrelated")])
    _registry(tmp_path, [own, sibling, unrelated], monkeypatch)

    competitors, used_ids, warnings = load_truth_eye_population(own, freshness_days=3)

    assert [(competitor["id"], competitor["source"]) for competitor in competitors] == [
        (SHARED_COMPETITOR, "self"),
        (SIBLING_ONLY_COMPETITOR, "sibling"),
    ]
    assert competitors[0]["slug"] == "shared"
    assert competitors[1]["thumbnails_dir"] == sibling.resolve() / "docs" / "benchmarks" / "thumbnails"
    assert used_ids == set()
    assert warnings == []


def test_population_works_alone_without_registry_and_workspace(tmp_path, monkeypatch):
    own = _repository(tmp_path, "self", [(SHARED_COMPETITOR, "shared")])
    _without_registry(tmp_path, monkeypatch)

    competitors, used_ids, warnings = load_truth_eye_population(own, freshness_days=3)

    assert [competitor["source"] for competitor in competitors] == ["self"]
    assert used_ids == set()
    assert warnings == []


def test_old_shape_in_sibling_stops_with_repository_and_recollect_command(tmp_path, monkeypatch):
    own = _repository(tmp_path, "self", [(SHARED_COMPETITOR, "shared")])
    sibling_competitors = [(SHARED_COMPETITOR, "shared-in-sibling"), (SIBLING_ONLY_COMPETITOR, "solo")]
    sibling = _repository(tmp_path, "sibling", sibling_competitors, old_shape_slug="solo")
    _registry(tmp_path, [own, sibling], monkeypatch)

    with pytest.raises(ConfigError) as error:
        load_truth_eye_population(own, freshness_days=3)

    assert "sibling" in str(error.value)
    assert "yt-benchmark-collect --force -y" in str(error.value)


def test_stale_benchmark_json_warns_and_keeps_going(tmp_path, monkeypatch):
    stale = date.today() - timedelta(days=10)
    own = _repository(tmp_path, "self", [(SHARED_COMPETITOR, "shared")], collected_on=stale)
    _without_registry(tmp_path, monkeypatch)

    competitors, _, warnings = load_truth_eye_population(own, freshness_days=3)

    assert len(competitors) == 1
    assert len(warnings) == 1
    assert "10 日前" in warnings[0]
    assert "channel-research --benchmark" in warnings[0]


def test_training_history_collects_used_video_ids_and_session_counts(tmp_path, monkeypatch):
    own = _repository(tmp_path, "self", [(SHARED_COMPETITOR, "shared")])
    training = own / "docs" / "benchmarks" / "training"
    _training_record(training / "20260901-thumbnail-shared-w1.md", "shared", "w1", "l1")
    _training_record(training / "20260902-thumbnail-shared-w2.md", "shared", "w2", "l2")
    (training / "20260902-thumbnail-shared-w2.sealed.md").write_text("封印分析", encoding="utf-8")
    _without_registry(tmp_path, monkeypatch)

    competitors, used_ids, _ = load_truth_eye_population(own, freshness_days=3)

    assert used_ids == {"w1", "l1", "w2", "l2"}
    assert competitors[0]["past_sessions"] == 2


def test_missing_benchmark_json_stops_with_collect_guidance(tmp_path, monkeypatch):
    own = _repository(tmp_path, "self", [(SHARED_COMPETITOR, "shared")], with_benchmark_json=False)
    _without_registry(tmp_path, monkeypatch)

    with pytest.raises(ConfigError, match="channel-research --benchmark"):
        load_truth_eye_population(own, freshness_days=3)


def test_empty_benchmark_channels_stops(tmp_path, monkeypatch):
    own = _repository(tmp_path, "self", [])
    _without_registry(tmp_path, monkeypatch)

    with pytest.raises(ConfigError, match="benchmark.channels が空"):
        load_truth_eye_population(own, freshness_days=3)


@pytest.mark.parametrize("channel", [{"slug": "missing-id"}, {"id": "", "slug": "empty-id"}, "invalid"])
def test_malformed_benchmark_channel_stops_with_config_error(tmp_path, monkeypatch, channel):
    own = _repository(tmp_path, "self", [(SHARED_COMPETITOR, "shared")])
    _write_json(own / "config" / "channel" / "analytics.json", {"benchmark": {"channels": [channel]}})
    _without_registry(tmp_path, monkeypatch)

    with pytest.raises(ConfigError, match=r"benchmark\.channels\[0\]"):
        load_truth_eye_population(own, freshness_days=3)


def test_broken_registry_is_not_degraded_into_a_sibling_less_run(tmp_path, monkeypatch):
    own = _repository(tmp_path, "self", [(SHARED_COMPETITOR, "shared")])
    registry = tmp_path / "channels.json"
    registry.write_text("{", encoding="utf-8")
    monkeypatch.setattr(REGISTRY_ATTRIBUTE, registry)

    with pytest.raises(ChannelRegistryError):
        load_truth_eye_population(own, freshness_days=3)
