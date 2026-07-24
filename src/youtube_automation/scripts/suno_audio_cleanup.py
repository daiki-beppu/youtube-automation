#!/usr/bin/env python3
"""Apply ffmpeg-based post-processing to Suno-downloaded source tracks."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from youtube_automation.infrastructure.errors import ConfigError, ValidationError
from youtube_automation.utils.audio_formats import AUDIO_EXTS
from youtube_automation.utils.collection_paths import CollectionPaths, resolve_collection_dir
from youtube_automation.utils.probe import probe_duration
from youtube_automation.utils.skill_config import load_skill_config

_SKILL_NAME = "masterup"
_BACKUP_DIRNAME = "originals-pre-cleanup"
_SUPPORTED_EXTS = tuple(sorted(AUDIO_EXTS))


@dataclass(frozen=True)
class CleanupConfig:
    enabled: bool = False
    backup_originals: bool = True
    trim_silence: bool = True
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
        filters.append(
            f"silenceremove=start_periods=1:start_duration=0.2:start_threshold={cfg.silence_threshold_db:g}dB"
        )
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


def cleanup_collection(collection_dir: Path, *, apply: bool, force: bool = False, quiet: bool = False) -> int:
    cfg = resolve_cleanup_config(load_skill_config(_SKILL_NAME))
    if not cfg.enabled and not force:
        if not quiet:
            print("post_processing.suno_audio_cleanup.enabled=false のため何もしません")
        return 0

    files = collect_audio_files(collection_dir)
    if not files:
        music_dir = CollectionPaths(collection_dir).music_dir
        supported_exts = ", ".join(_SUPPORTED_EXTS)
        raise ValidationError(f"音声ファイル ({supported_exts}) が見つかりません: {music_dir}")

    changed = 0
    for path in files:
        if process_file(path, cfg, apply=apply, force=force, quiet=quiet):
            changed += 1

    if not quiet:
        action = "processed" if apply else "planned"
        print(f"{action}: {len(files)} file(s), changed={changed}")
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    collection_dir = resolve_collection_dir(args.collection)
    return cleanup_collection(
        collection_dir,
        apply=args.command == "apply",
        force=args.force,
        quiet=args.quiet,
    )


if __name__ == "__main__":
    sys.exit(main())
