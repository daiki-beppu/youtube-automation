from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from youtube_automation.scripts import benchmark_collector as mod
from youtube_automation.utils.config import reset as reset_config
from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.skill_config import reset as reset_skill_config


def _channel(index: int) -> dict:
    return {"id": f"UC_{index}", "name": f"Channel {index}", "slug": f"channel-{index}"}


def _install_scan_recent_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    scan_recent: int,
) -> None:
    source_channel_dir = Path(os.environ["CHANNEL_DIR"])
    channel_dir = tmp_path / "channel"
    shutil.copytree(source_channel_dir, channel_dir)
    skill_config_dir = channel_dir / "config" / "skills"
    skill_config_dir.mkdir(parents=True, exist_ok=True)
    (skill_config_dir / "benchmark.yaml").write_text(f"scan_recent: {scan_recent}\n", encoding="utf-8")
    analytics_path = channel_dir / "config" / "channel" / "analytics.json"
    analytics = json.loads(analytics_path.read_text(encoding="utf-8"))
    analytics["benchmark"]["channels"][0]["slug"] = "rival"
    analytics_path.write_text(json.dumps(analytics), encoding="utf-8")
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))
    reset_config()
    reset_skill_config("benchmark")


def _install_fake_collector(
    monkeypatch: pytest.MonkeyPatch,
    *,
    num_channels: int,
    scan_recent: int,
) -> MagicMock:
    collector = MagicMock()
    collector.config = SimpleNamespace(
        analytics=SimpleNamespace(
            benchmark=SimpleNamespace(channels=[_channel(index) for index in range(num_channels)]),
        ),
    )
    collector.benchmark_config = {
        "scan_recent": scan_recent,
        "freshness_days": 3,
        "gemini_thumbnail_analysis": False,
    }
    monkeypatch.setattr(mod, "BenchmarkCollector", MagicMock(return_value=collector))
    return collector


def test_collect_channel_rejects_scan_recent_above_limit_before_api_call():
    collector = mod.BenchmarkCollector()
    collector.youtube = MagicMock()
    collector.benchmark_config = {"scan_recent": 5000, "min_views": 10000}

    with pytest.raises(ConfigError, match=r"scan_recent.*200.*5000"):
        collector.collect_channel(_channel(0), {})

    collector.youtube.channels.assert_not_called()
    collector.youtube.playlistItems.assert_not_called()
    collector.youtube.videos.assert_not_called()


def test_collect_all_rejects_scan_recent_above_limit_before_channels_api_call():
    collector = mod.BenchmarkCollector()
    collector.youtube = MagicMock()
    collector.benchmark_config = {"scan_recent": 5000, "min_views": 10000}

    with pytest.raises(ConfigError, match=r"scan_recent.*200.*5000"):
        collector.collect_all(force=True)

    collector.youtube.channels.assert_not_called()
    collector.youtube.playlistItems.assert_not_called()
    collector.youtube.videos.assert_not_called()


def test_ensure_benchmark_fresh_rejects_before_channels_api_call(monkeypatch, tmp_path):
    _install_scan_recent_override(monkeypatch, tmp_path, 5000)
    youtube = MagicMock()
    monkeypatch.setattr(mod.BenchmarkCollector, "initialize", lambda self: setattr(self, "youtube", youtube))

    try:
        with pytest.raises(ConfigError, match=r"scan_recent.*200.*5000"):
            mod.ensure_benchmark_fresh(data_dir=tmp_path / "benchmark-data")
    finally:
        reset_skill_config("benchmark")

    youtube.channels.assert_not_called()
    youtube.playlistItems.assert_not_called()
    youtube.videos.assert_not_called()


@pytest.mark.parametrize(
    ("num_channels", "scan_recent", "expected"),
    [
        (1, 50, 3),
        (10, 50, 21),
        (50, 50, 101),
        (51, 50, 104),
        (1, 51, 5),
        (10, 200, 81),
    ],
)
def test_estimate_quota_units_uses_fifty_item_batches(num_channels, scan_recent, expected):
    assert mod._estimate_quota_units(num_channels, scan_recent) == expected


def test_main_prints_estimated_quota_for_single_channel(monkeypatch, capsys):
    collector = _install_fake_collector(monkeypatch, num_channels=10, scan_recent=50)
    collector.collect_all.return_value = {"skipped": True}
    monkeypatch.setattr(sys, "argv", ["yt-benchmark-collect", "--channel", "channel-0", "--yes"])

    with pytest.raises(SystemExit) as exc_info:
        mod.main()

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "対象チャンネル: 1 件" in output
    assert "推定 YouTube Data API quota: 最大 3 units" in output
    collector.initialize.assert_called_once_with()


def test_main_loads_scan_recent_override_and_rejects_before_authentication(monkeypatch, tmp_path):
    _install_scan_recent_override(monkeypatch, tmp_path, 5000)
    get_youtube = MagicMock()
    monkeypatch.setattr(mod, "get_youtube", get_youtube)
    monkeypatch.setattr(sys, "argv", ["yt-benchmark-collect", "--yes"])

    try:
        with pytest.raises(ConfigError, match=r"scan_recent.*200.*5000"):
            mod.main()
    finally:
        reset_skill_config("benchmark")

    get_youtube.assert_not_called()


def test_high_quota_force_cancellation_stops_before_authentication(monkeypatch, capsys):
    collector = _install_fake_collector(monkeypatch, num_channels=50, scan_recent=50)
    prompt = MagicMock(return_value="n")
    monkeypatch.setattr("builtins.input", prompt)
    monkeypatch.setattr(sys, "argv", ["yt-benchmark-collect", "--force"])

    with pytest.raises(SystemExit) as exc_info:
        mod.main()

    assert exc_info.value.code == 0
    prompt.assert_called_once_with("続行しますか？ [Y/n] ")
    output = capsys.readouterr().out
    assert "[WARNING] --force は推定最大 101 quota units" in output
    assert "キャンセルしました" in output
    collector.initialize.assert_not_called()
    collector.collect_all.assert_not_called()


def test_high_quota_force_yes_skips_confirmation(monkeypatch):
    collector = _install_fake_collector(monkeypatch, num_channels=50, scan_recent=50)
    collector.collect_all.return_value = {"skipped": True}
    prompt = MagicMock(side_effect=AssertionError("confirmation must be skipped"))
    monkeypatch.setattr("builtins.input", prompt)
    monkeypatch.setattr(sys, "argv", ["yt-benchmark-collect", "--force", "--yes"])

    with pytest.raises(SystemExit) as exc_info:
        mod.main()

    assert exc_info.value.code == 0
    prompt.assert_not_called()
    collector.initialize.assert_called_once_with()
    collector.collect_all.assert_called_once_with(force=True, channel_slug=None)


def test_force_at_quota_threshold_keeps_existing_no_prompt_behavior(monkeypatch):
    collector = _install_fake_collector(monkeypatch, num_channels=49, scan_recent=50)
    collector.collect_all.return_value = {"skipped": True}
    prompt = MagicMock(side_effect=AssertionError("confirmation must be skipped"))
    monkeypatch.setattr("builtins.input", prompt)
    monkeypatch.setattr(sys, "argv", ["yt-benchmark-collect", "--force"])

    with pytest.raises(SystemExit) as exc_info:
        mod.main()

    assert exc_info.value.code == 0
    assert mod._estimate_quota_units(49, 50) == 99
    assert mod._estimate_quota_units(49, 50) <= mod._HIGH_QUOTA_CONFIRM_THRESHOLD
    prompt.assert_not_called()
    collector.initialize.assert_called_once_with()
