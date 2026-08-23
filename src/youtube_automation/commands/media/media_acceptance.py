"""R2 pull 後の個別音源を曲数・尺・音量で受入検証する。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from youtube_automation.application.media_acceptance import validate_collection_audio
from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.configuration import load_config
from youtube_automation.configuration.skills import load_skill_config
from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.collections.workflow_state import read as read_workflow_state
from youtube_automation.domains.media.acceptance import MediaAcceptancePolicy, MediaAcceptanceReport
from youtube_automation.domains.media.loudness_receipt import resolve_max_deviation_lu
from youtube_automation.domains.suno.prompts import read_suno_duration_filter
from youtube_automation.infrastructure.media.audio_acceptance import FFmpegAudioInspector
from youtube_automation.infrastructure.media.collection_paths import CollectionPaths
from youtube_automation.infrastructure.notifications.discord import create_discord_notification_sink

_MINIMUM_INTEGRATED_LUFS = -40.0
_MAXIMUM_INTEGRATED_LUFS = -5.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection", type=Path, help="R2 pull 済みの collection directory")
    parser.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="検証結果の出力形式 (default: text)",
    )
    return parser


def build_media_acceptance_policy(collection: Path) -> MediaAcceptancePolicy:
    paths = CollectionPaths(collection)
    state = read_workflow_state(paths.workflow_state_path)
    planning = state.planning
    music = planning.music if planning is not None else None
    expected = music.expected_file_count if music is not None else None
    if expected is None or expected <= 0:
        raise ValidationError("workflow-state.json::planning.music.expected_file_count は1以上が必要です")
    try:
        duration_filter = read_suno_duration_filter(collection)
    except ValueError as error:
        raise ValidationError(str(error)) from error
    maximum_deviation = resolve_max_deviation_lu(load_skill_config("masterup"))
    return MediaAcceptancePolicy(
        expected_track_count=expected,
        minimum_duration_seconds=duration_filter.minimum_seconds,
        maximum_duration_seconds=duration_filter.maximum_seconds,
        minimum_integrated_lufs=_MINIMUM_INTEGRATED_LUFS,
        maximum_integrated_lufs=_MAXIMUM_INTEGRATED_LUFS,
        maximum_loudness_deviation_lu=maximum_deviation,
    )


def _print_text(report: MediaAcceptanceReport) -> None:
    print(
        f"PASS: tracks={len(report.measurements)}/{report.policy.expected_track_count}, "
        f"duration={report.policy.minimum_duration_seconds:g}..{report.policy.maximum_duration_seconds:g}s, "
        f"loudness={report.policy.minimum_integrated_lufs:g}..{report.policy.maximum_integrated_lufs:g} LUFS"
    )
    for measurement in report.measurements:
        print(f"- {measurement.path.name}: {measurement.duration_seconds:.3f}s, {measurement.integrated_lufs:.3f} LUFS")


def run(args: argparse.Namespace) -> int:
    collection = args.collection.resolve()
    policy = build_media_acceptance_policy(collection)
    notifications = create_discord_notification_sink()
    report = validate_collection_audio(
        collection,
        policy,
        FFmpegAudioInspector(),
        channel=load_config().meta.channel_short,
        on_event=notifications.notify,
    )
    if args.output == "json":
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        _print_text(report)
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_cli(
        build_parser,
        run,
        argv,
        failure_message="media acceptance rejected",
        failure_exit_code=2,
    )


if __name__ == "__main__":
    raise SystemExit(main())
