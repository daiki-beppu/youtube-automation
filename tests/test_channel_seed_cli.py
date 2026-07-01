"""yt-channel-seed CLI のユニットテスト."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from youtube_automation.scripts.channel_seed import _build_parser, main
from youtube_automation.utils.channel_seed import SeedChannel


@pytest.fixture(autouse=True)
def _reset_config(monkeypatch):
    monkeypatch.delenv("CHANNEL_DIR", raising=False)
    from youtube_automation.utils.config import reset

    reset()
    yield
    reset()


def _write_analytics(target: Path, channels: list[dict] | None = None) -> Path:
    path = target / "config" / "channel" / "analytics.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "analytics": {},
                "benchmark": {
                    "channels": list(channels or []),
                    "scan_recent": 10,
                    "min_views": 1000,
                    "freshness_days": 90,
                    "gemini_thumbnail_analysis": False,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _seed() -> SeedChannel:
    return SeedChannel(
        channel_id="UC_seed",
        handle="@seed",
        name="Seed Channel",
        subscribers=12_345,
        total_videos=67,
        uploads_playlist_id="UU_seed",
        recent_titles=("First Video", "Second Video"),
    )


def test_build_parser_has_expected_defaults():
    # Given
    parser = _build_parser()

    # When
    args = parser.parse_args(["https://www.youtube.com/@seed"])

    # Then
    assert args.url == "https://www.youtube.com/@seed"
    assert args.relationship == "seed"
    assert args.recent == 10
    assert args.write_benchmark is True
    assert args.json is False


def test_build_parser_accepts_explicit_options():
    # Given
    parser = _build_parser()

    # When
    args = parser.parse_args(
        [
            "https://www.youtube.com/@seed",
            "--target",
            "repo",
            "--relationship",
            "reference",
            "--recent",
            "5",
            "--no-write-benchmark",
            "--json",
        ]
    )

    # Then
    assert args.target == "repo"
    assert args.relationship == "reference"
    assert args.recent == 5
    assert args.write_benchmark is False
    assert args.json is True


def test_main_fetches_seed_and_writes_benchmark_entry(tmp_path, capsys):
    # Given
    analytics_path = _write_analytics(tmp_path)
    youtube = MagicMock()

    # When
    with (
        patch("youtube_automation.scripts.channel_seed.get_youtube", return_value=youtube) as get_youtube,
        patch("youtube_automation.scripts.channel_seed.fetch_channel_seed", return_value=_seed()) as fetch_seed,
    ):
        rc = main(["https://www.youtube.com/@seed", "--target", str(tmp_path)])

    # Then
    out = capsys.readouterr().out
    assert rc == 0
    get_youtube.assert_called_once_with()
    fetch_seed.assert_called_once_with(youtube, "https://www.youtube.com/@seed", recent=10)
    assert "Seed Channel" in out
    assert "12,345" in out
    assert "67" in out
    assert "First Video" in out
    assert "Second Video" in out

    analytics = json.loads(analytics_path.read_text(encoding="utf-8"))
    assert analytics["benchmark"]["channels"] == [
        {
            "id": "UC_seed",
            "slug": "seed",
            "name": "Seed Channel",
            "relationship": "seed",
        }
    ]


def test_main_does_not_write_analytics_when_no_write_benchmark(tmp_path):
    # Given
    analytics_path = _write_analytics(tmp_path)
    before = analytics_path.read_text(encoding="utf-8")

    # When
    with (
        patch("youtube_automation.scripts.channel_seed.get_youtube", return_value=MagicMock()),
        patch("youtube_automation.scripts.channel_seed.fetch_channel_seed", return_value=_seed()),
    ):
        rc = main(["https://www.youtube.com/@seed", "--target", str(tmp_path), "--no-write-benchmark"])

    # Then
    assert rc == 0
    assert analytics_path.read_text(encoding="utf-8") == before


def test_main_deduplicates_existing_benchmark_channel(tmp_path):
    # Given
    analytics_path = _write_analytics(
        tmp_path,
        channels=[
            {
                "id": "UC_seed",
                "slug": "old-seed",
                "name": "Old Name",
                "relationship": "seed",
            }
        ],
    )

    # When
    with (
        patch("youtube_automation.scripts.channel_seed.get_youtube", return_value=MagicMock()),
        patch("youtube_automation.scripts.channel_seed.fetch_channel_seed", return_value=_seed()),
    ):
        rc = main(["https://www.youtube.com/@seed", "--target", str(tmp_path)])

    # Then
    assert rc == 0
    analytics = json.loads(analytics_path.read_text(encoding="utf-8"))
    assert analytics["benchmark"]["channels"] == [
        {
            "id": "UC_seed",
            "slug": "old-seed",
            "name": "Old Name",
            "relationship": "seed",
        }
    ]


def test_pyproject_registers_yt_channel_seed_entry_point():
    # Given
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    # When
    scripts = data["project"]["scripts"]

    # Then
    assert scripts["yt-channel-seed"] == "youtube_automation.cli_entrypoints:yt_channel_seed"
