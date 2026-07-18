"""CLI for evaluating TTP channel health from the latest benchmark JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from youtube_automation.scripts.benchmark_collector import find_latest_benchmark_json
from youtube_automation.utils.config import channel_dir, load_config
from youtube_automation.utils.ttp_health import evaluate_ttp_health


def _unavailable(reason: str, detail: str) -> dict:
    return {"status": "unavailable", "reason": reason, "detail": detail, "channels": []}


def build_report(
    *,
    data_dir: Path,
    stale_days: int = 60,
    decline_ratio: float = 0.5,
    window_days: int = 90,
) -> dict:
    """Load the latest benchmark data and return the JSON-ready health report."""
    config_channels = load_config().analytics.benchmark.channels
    if not config_channels:
        return _unavailable(
            "no_benchmark_channels",
            "config/channel/analytics.json の benchmark.channels に対象がありません。",
        )

    benchmark_path = find_latest_benchmark_json(data_dir)
    if benchmark_path is None:
        return _unavailable(
            "no_benchmark_json",
            f"{data_dir} に benchmark_YYYYMMDD.json がありません。/benchmark を実行してください。",
        )

    benchmark_data = json.loads(benchmark_path.read_text(encoding="utf-8"))
    benchmark_data["source"] = benchmark_path.name
    return evaluate_ttp_health(
        config_channels,
        benchmark_data,
        stale_days=stale_days,
        decline_ratio=decline_ratio,
        window_days=window_days,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="benchmark.channels の TTP 健全性を JSON で出力")
    parser.add_argument("--stale-days", type=int, default=60)
    parser.add_argument("--decline-ratio", type=float, default=0.5)
    parser.add_argument("--window-days", type=int, default=90)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    report = build_report(
        data_dir=channel_dir() / "data",
        stale_days=args.stale_days,
        decline_ratio=args.decline_ratio,
        window_days=args.window_days,
    )
    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2 if args.pretty else None,
            separators=None if args.pretty else (",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
