#!/usr/bin/env python3
"""Apply ffmpeg-based post-processing to Suno-downloaded source tracks."""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

from youtube_automation.configuration.skills import load_skill_config
from youtube_automation.core.errors import ConfigError, ValidationError
from youtube_automation.domains.media.audio_adjustments import (
    read_audio_adjustments,
    validate_cleanup_settings,
)
from youtube_automation.domains.media.audio_formats import AUDIO_EXTS
from youtube_automation.infrastructure.media.collection_paths import CollectionPaths, resolve_collection_dir
from youtube_automation.infrastructure.media.probe import probe_duration

_SKILL_NAME = "masterup"
_BACKUP_DIRNAME = "originals-pre-cleanup"
_SUPPORTED_EXTS = tuple(sorted(AUDIO_EXTS))
_DEFAULT_MAX_WORKERS = 2
_MAX_WORKERS_LIMIT = 8


@dataclass(frozen=True)
class CleanupConfig:
    enabled: bool = False
    backup_originals: bool = True
    trim_silence: bool = True
    trim_silence_trailing: bool = True
    silence_threshold_db: float = -50.0
    adaptive_eq: bool = True
    muddiness_freq_hz: int = 350
    muddiness_gain_db: float = -2.0
    harshness_freq_hz: int = 8000
    harshness_gain_db: float = -1.5
    volume_smoothing: bool = True
    limiter: bool = True
    limiter_limit: float = 0.95
    loudnorm: bool = True
    target_lufs: float = -14.0
    loudness_range: float = 11.0
    true_peak: float = -1.5
    tail_fade_guard: bool = True
    tail_fade_sec: float = 3.0
    bitrate: str = "192k"
    codec: str = "libmp3lame"


def _as_mapping(value: object, context: str) -> Mapping[str, object]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigError(f"skill-config の {context} は mapping である必要があります: {value!r}")
    return value


def resolve_cleanup_config(skill_cfg: Mapping[str, object]) -> CleanupConfig:
    post = _as_mapping(skill_cfg.get("post_processing"), "post_processing")
    raw = _as_mapping(post.get("suno_audio_cleanup"), "post_processing.suno_audio_cleanup")
    audio = _as_mapping(skill_cfg.get("audio"), "audio")

    loudnorm = _as_mapping(raw.get("loudnorm"), "post_processing.suno_audio_cleanup.loudnorm")
    eq = _as_mapping(raw.get("eq"), "post_processing.suno_audio_cleanup.eq")
    trim = _as_mapping(raw.get("trim_silence"), "post_processing.suno_audio_cleanup.trim_silence")
    limiter = _as_mapping(raw.get("limiter"), "post_processing.suno_audio_cleanup.limiter")
    tail = _as_mapping(raw.get("tail_fade_guard"), "post_processing.suno_audio_cleanup.tail_fade_guard")
    return CleanupConfig(
        enabled=bool(raw.get("enabled", False)),
        backup_originals=bool(raw.get("backup_originals", True)),
        trim_silence=bool(trim.get("enabled", True)),
        trim_silence_trailing=bool(trim.get("trailing", True)),
        silence_threshold_db=float(trim.get("threshold_db", -50.0)),
        adaptive_eq=bool(eq.get("enabled", True)),
        muddiness_freq_hz=int(eq.get("muddiness_freq_hz", 350)),
        muddiness_gain_db=float(eq.get("muddiness_gain_db", -2.0)),
        harshness_freq_hz=int(eq.get("harshness_freq_hz", 8000)),
        harshness_gain_db=float(eq.get("harshness_gain_db", -1.5)),
        volume_smoothing=bool(raw.get("volume_smoothing", True)),
        limiter=bool(limiter.get("enabled", True)),
        limiter_limit=float(limiter.get("limit", 0.95)),
        loudnorm=bool(loudnorm.get("enabled", True)),
        target_lufs=float(loudnorm.get("I", -14.0)),
        loudness_range=float(loudnorm.get("LRA", 11.0)),
        true_peak=float(loudnorm.get("TP", -1.5)),
        tail_fade_guard=bool(tail.get("enabled", True)),
        tail_fade_sec=float(tail.get("fade_sec", 3.0)),
        bitrate=str(raw.get("bitrate") or audio.get("bitrate") or "192k"),
        codec=str(raw.get("codec") or "libmp3lame"),
    )


def cleanup_config_settings(cfg: CleanupConfig) -> dict[str, object]:
    """Expose the adjustable cleanup subset in the Audio Studio document shape."""
    return {
        "eq": {
            "enabled": cfg.adaptive_eq,
            "muddiness_freq_hz": cfg.muddiness_freq_hz,
            "muddiness_gain_db": cfg.muddiness_gain_db,
            "harshness_freq_hz": cfg.harshness_freq_hz,
            "harshness_gain_db": cfg.harshness_gain_db,
        },
        "loudnorm": {
            "enabled": cfg.loudnorm,
            "I": cfg.target_lufs,
            "LRA": cfg.loudness_range,
            "TP": cfg.true_peak,
        },
        "limiter": {"enabled": cfg.limiter, "limit": cfg.limiter_limit},
        "trim_silence": {
            "enabled": cfg.trim_silence,
            "trailing": cfg.trim_silence_trailing,
            "threshold_db": cfg.silence_threshold_db,
        },
        "tail_fade_guard": {"enabled": cfg.tail_fade_guard, "fade_sec": cfg.tail_fade_sec},
        "volume_smoothing": cfg.volume_smoothing,
    }


def apply_cleanup_overrides(cfg: CleanupConfig, overrides: object) -> CleanupConfig:
    """Overlay one track's validated persisted values on the channel defaults."""
    validated = validate_cleanup_settings(overrides, partial=True)
    eq = cast(dict[str, object], validated.get("eq", {}))
    loudnorm = cast(dict[str, object], validated.get("loudnorm", {}))
    limiter = cast(dict[str, object], validated.get("limiter", {}))
    trim = cast(dict[str, object], validated.get("trim_silence", {}))
    tail = cast(dict[str, object], validated.get("tail_fade_guard", {}))
    return replace(
        cfg,
        adaptive_eq=cast(bool, eq.get("enabled", cfg.adaptive_eq)),
        muddiness_freq_hz=cast(int, eq.get("muddiness_freq_hz", cfg.muddiness_freq_hz)),
        muddiness_gain_db=cast(float, eq.get("muddiness_gain_db", cfg.muddiness_gain_db)),
        harshness_freq_hz=cast(int, eq.get("harshness_freq_hz", cfg.harshness_freq_hz)),
        harshness_gain_db=cast(float, eq.get("harshness_gain_db", cfg.harshness_gain_db)),
        loudnorm=cast(bool, loudnorm.get("enabled", cfg.loudnorm)),
        target_lufs=cast(float, loudnorm.get("I", cfg.target_lufs)),
        loudness_range=cast(float, loudnorm.get("LRA", cfg.loudness_range)),
        true_peak=cast(float, loudnorm.get("TP", cfg.true_peak)),
        limiter=cast(bool, limiter.get("enabled", cfg.limiter)),
        limiter_limit=cast(float, limiter.get("limit", cfg.limiter_limit)),
        trim_silence=cast(bool, trim.get("enabled", cfg.trim_silence)),
        trim_silence_trailing=cast(bool, trim.get("trailing", cfg.trim_silence_trailing)),
        silence_threshold_db=cast(float, trim.get("threshold_db", cfg.silence_threshold_db)),
        tail_fade_guard=cast(bool, tail.get("enabled", cfg.tail_fade_guard)),
        tail_fade_sec=cast(float, tail.get("fade_sec", cfg.tail_fade_sec)),
        volume_smoothing=cast(bool, validated.get("volume_smoothing", cfg.volume_smoothing)),
    )


def resolve_max_workers(cli_jobs: int | None, skill_cfg: Mapping[str, object]) -> int:
    if cli_jobs is None:
        post = _as_mapping(skill_cfg.get("post_processing"), "post_processing")
        raw = _as_mapping(post.get("suno_audio_cleanup"), "post_processing.suno_audio_cleanup")
        config_value = raw.get("max_workers", _DEFAULT_MAX_WORKERS)
        if (
            isinstance(config_value, bool)
            or not isinstance(config_value, int)
            or not 1 <= config_value <= _MAX_WORKERS_LIMIT
        ):
            raise ConfigError(
                "skill-config の post_processing.suno_audio_cleanup.max_workers は "
                f"1 以上 {_MAX_WORKERS_LIMIT} 以下の整数である必要があります: "
                f"{config_value!r}"
            )
        return config_value
    if isinstance(cli_jobs, bool) or not isinstance(cli_jobs, int) or not 1 <= cli_jobs <= _MAX_WORKERS_LIMIT:
        raise ValidationError(f"jobs は 1 以上 {_MAX_WORKERS_LIMIT} 以下の整数である必要があります: {cli_jobs!r}")
    return cli_jobs


def _positive_jobs(value: str) -> int:
    try:
        jobs = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"--jobs は 1 以上 {_MAX_WORKERS_LIMIT} 以下の整数を指定してください"
        ) from error
    if not 1 <= jobs <= _MAX_WORKERS_LIMIT:
        raise argparse.ArgumentTypeError(f"--jobs は 1 以上 {_MAX_WORKERS_LIMIT} 以下の整数を指定してください")
    return jobs


def _output_codec_for(path: Path, cfg: CleanupConfig) -> str:
    match path.suffix.lower():
        case ".m4a":
            return "aac"
        case ".wav":
            return "pcm_s16le"
        case _:
            return cfg.codec


def _codec_uses_bitrate(codec: str) -> bool:
    return codec in {"aac", "libmp3lame"}


def build_filter(cfg: CleanupConfig, *, duration_sec: float | None = None) -> str:
    filters: list[str] = []
    if cfg.trim_silence:
        # 末尾は areverse で挟み、同じ silenceremove を「冒頭」として適用する
        silence_step = (
            f"silenceremove=start_periods=1:start_duration=0.2:start_threshold={cfg.silence_threshold_db:g}dB"
        )
        filters.append(silence_step)
        if cfg.trim_silence_trailing:
            filters.extend(["areverse", silence_step, "areverse"])
    if cfg.adaptive_eq:
        filters.append(f"equalizer=f={cfg.muddiness_freq_hz}:t=q:w=1:g={cfg.muddiness_gain_db:g}")
        filters.append(f"equalizer=f={cfg.harshness_freq_hz}:t=q:w=1:g={cfg.harshness_gain_db:g}")
    if cfg.volume_smoothing:
        filters.append("dynaudnorm=f=150:g=15:p=0.95")
    if cfg.limiter:
        filters.append(f"alimiter=limit={cfg.limiter_limit:g}")
    if cfg.loudnorm:
        filters.append(f"loudnorm=I={cfg.target_lufs:g}:LRA={cfg.loudness_range:g}:TP={cfg.true_peak:g}")
    if cfg.tail_fade_guard and duration_sec and duration_sec > cfg.tail_fade_sec:
        start = max(0.0, duration_sec - cfg.tail_fade_sec)
        filters.append(f"afade=t=out:st={start:g}:d={cfg.tail_fade_sec:g}")
    return ",".join(filters) if filters else "anull"


def probe_trimmed_duration(path: Path, cfg: CleanupConfig) -> float:
    """Measure the duration after the same leading/trailing silence trim used by cleanup."""
    trim_only = replace(
        cfg,
        adaptive_eq=False,
        volume_smoothing=False,
        limiter=False,
        loudnorm=False,
        tail_fade_guard=False,
    )
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-i",
        str(path),
        "-af",
        build_filter(trim_only),
        "-progress",
        "pipe:1",
        "-nostats",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg trim duration probe failed ({path.name}, rc={proc.returncode}):\n{proc.stderr}")
    durations = [
        int(line.removeprefix("out_time_us=")) / 1_000_000
        for line in proc.stdout.splitlines()
        if line.startswith("out_time_us=") and line.removeprefix("out_time_us=").isdigit()
    ]
    if not durations:
        raise RuntimeError(f"ffmpeg trim duration probe returned no duration: {path.name}")
    return max(durations)


def collect_audio_files(collection_dir: Path) -> list[Path]:
    music_dir = CollectionPaths(collection_dir).music_dir
    if not music_dir.is_dir():
        raise ValidationError(f"ディレクトリが見つかりません: {music_dir}")
    files = sorted(p for p in music_dir.iterdir() if p.suffix.lower() in _SUPPORTED_EXTS and p.is_file())
    return [p for p in files if p.parent.name != _BACKUP_DIRNAME]


def build_ffmpeg_cmd(
    input_path: Path,
    output_path: Path,
    cfg: CleanupConfig,
    *,
    duration_sec: float | None,
) -> list[str]:
    codec = _output_codec_for(output_path, cfg)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-af",
        build_filter(cfg, duration_sec=duration_sec),
        "-c:a",
        codec,
    ]
    if _codec_uses_bitrate(codec):
        cmd.extend(["-b:a", cfg.bitrate])
    cmd.append(str(output_path))
    return cmd


def _tmp_output_for(path: Path) -> Path:
    return path.with_name(f".{path.stem}.cleanup-tmp{path.suffix}")


def _backup_path_for(path: Path) -> Path:
    return path.parent / _BACKUP_DIRNAME / path.name


def process_file(path: Path, cfg: CleanupConfig, *, apply: bool, force: bool, quiet: bool = False) -> bool:
    backup = _backup_path_for(path)
    if backup.exists() and not force:
        if not quiet:
            print(f"skip already cleaned: {path.name} (backup exists)")
        return False

    if apply and cfg.trim_silence and cfg.trim_silence_trailing and cfg.tail_fade_guard:
        duration = probe_trimmed_duration(path, cfg)
    else:
        duration = probe_duration(path)
    tmp = _tmp_output_for(path)
    cmd = build_ffmpeg_cmd(path, tmp, cfg, duration_sec=duration)

    if not apply:
        print(" ".join(cmd))
        return False

    if shutil.which("ffmpeg") is None:
        raise ValidationError("ffmpeg が見つかりません (brew install ffmpeg など)")

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        if tmp.exists():
            tmp.unlink()
        raise RuntimeError(f"ffmpeg cleanup failed ({path.name}, rc={proc.returncode}):\n{proc.stderr}")

    backup_created = False
    try:
        if cfg.backup_originals:
            backup.parent.mkdir(parents=True, exist_ok=True)
            os.replace(path, backup)
            backup_created = True
        os.replace(tmp, path)
    except OSError:
        if backup_created and backup.exists() and not path.exists():
            os.replace(backup, path)
        if tmp.exists():
            tmp.unlink()
        raise
    if not quiet:
        print(f"cleaned: {path.name}")
    return True


def _process_files_parallel(
    files: list[Path],
    configs: Mapping[Path, CleanupConfig],
    *,
    max_workers: int,
    force: bool,
) -> tuple[dict[Path, bool], dict[Path, Exception]]:
    results: dict[Path, bool] = {}
    errors: dict[Path, Exception] = {}
    next_index = 0
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=min(max_workers, len(files)))
    pending: dict[concurrent.futures.Future[bool], Path] = {}

    def submit_next() -> None:
        nonlocal next_index
        path = files[next_index]
        next_index += 1
        future = executor.submit(process_file, path, configs[path], apply=True, force=force, quiet=True)
        pending[future] = path

    try:
        for _ in range(min(max_workers, len(files))):
            submit_next()
        while pending:
            done, _ = concurrent.futures.wait(pending, return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                path = pending.pop(future)
                try:
                    results[path] = future.result()
                except Exception as error:
                    errors[path] = error
            if errors:
                continue
            for _ in range(min(len(done), len(files) - next_index)):
                submit_next()
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
    return results, errors


def _process_files_sequential(
    files: list[Path],
    configs: Mapping[Path, CleanupConfig],
    *,
    force: bool,
    quiet: bool,
) -> int:
    changed = 0
    for path in files:
        if process_file(path, configs[path], apply=True, force=force, quiet=quiet):
            changed += 1
    return changed


def cleanup_collection(
    collection_dir: Path,
    *,
    apply: bool,
    jobs: int | None = None,
    force: bool = False,
    quiet: bool = False,
) -> int:
    skill_cfg = load_skill_config(_SKILL_NAME)
    cfg = resolve_cleanup_config(skill_cfg)
    if not cfg.enabled and not force:
        if not quiet:
            print("post_processing.suno_audio_cleanup.enabled=false のため何もしません")
        return 0

    max_workers = resolve_max_workers(jobs, skill_cfg) if apply else None

    files = collect_audio_files(collection_dir)
    if not files:
        music_dir = CollectionPaths(collection_dir).music_dir
        supported_exts = ", ".join(_SUPPORTED_EXTS)
        raise ValidationError(f"音声ファイル ({supported_exts}) が見つかりません: {music_dir}")

    adjustment_document = read_audio_adjustments(CollectionPaths(collection_dir).audio_adjustments_path)
    configs = {path: apply_cleanup_overrides(cfg, adjustment_document.tracks.get(path.name, {})) for path in files}

    if not apply:
        for path in files:
            process_file(path, configs[path], apply=False, force=force, quiet=quiet)
        if not quiet:
            print(f"planned: {len(files)} file(s), changed=0")
        return 0

    if max_workers == 1:
        changed = _process_files_sequential(files, configs, force=force, quiet=quiet)
        if not quiet:
            print(f"processed: {len(files)} file(s), changed={changed}")
        return 0

    results, errors = _process_files_parallel(files, configs, max_workers=cast(int, max_workers), force=force)
    if not quiet:
        for path in files:
            if path not in results:
                continue
            message = "cleaned" if results[path] else "skip already cleaned"
            suffix = " (backup exists)" if not results[path] else ""
            print(f"{message}: {path.name}{suffix}")
    if errors:
        details = "\n".join(f"{path.name}: {errors[path]}" for path in files if path in errors)
        raise RuntimeError(f"audio cleanup failed:\n{details}")

    if not quiet:
        changed = sum(results.values())
        print(f"processed: {len(files)} file(s), changed={changed}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Suno source-track audio cleanup")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "apply"):
        p = sub.add_parser(name)
        p.add_argument("collection", nargs="?", help="collection dir (default: CWD if it looks like a collection)")
        p.add_argument(
            "--force",
            action="store_true",
            help="run even when config is disabled; reprocess existing backups",
        )
        p.add_argument("--quiet", action="store_true")
        p.add_argument(
            "--jobs",
            type=_positive_jobs,
            help=(
                f"maximum concurrent files, 1-{_MAX_WORKERS_LIMIT} "
                "(default: post_processing.suno_audio_cleanup.max_workers, then 2)"
            ),
        )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    collection_dir = resolve_collection_dir(args.collection)
    return cleanup_collection(
        collection_dir,
        apply=args.command == "apply",
        jobs=args.jobs,
        force=args.force,
        quiet=args.quiet,
    )


if __name__ == "__main__":
    sys.exit(main())
