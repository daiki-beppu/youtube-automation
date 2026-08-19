#!/usr/bin/env python3
"""Apply persisted Audio Studio EQ, loudnorm, and limiter settings to master.mp3."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.configuration.skills import load_skill_config
from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.media.audio_adjustments import read_audio_adjustments, validate_master_settings
from youtube_automation.infrastructure.file_lock import file_lock
from youtube_automation.infrastructure.media.collection_paths import CollectionPaths, resolve_collection_dir

_SKILL_NAME = "masterup"
_DEFAULT_BITRATE = "192k"


def _channel_dir_for_collection(collection_dir: Path) -> Path:
    for candidate in (collection_dir, *collection_dir.parents):
        if (candidate / "config/channel").is_dir():
            return candidate
    return collection_dir


def build_filter(settings: object) -> str:
    """Build the deterministic ffmpeg chain for validated master settings."""
    validated = validate_master_settings(settings)
    eq = cast(Mapping[str, object], validated["eq"])
    loudnorm = cast(Mapping[str, object], validated["loudnorm"])
    limiter = cast(Mapping[str, object], validated["limiter"])
    filters: list[str] = []
    if cast(bool, eq["enabled"]):
        filters.extend(
            [
                f"equalizer=f={cast(int, eq['muddiness_freq_hz'])}:t=q:w=1:g={cast(float, eq['muddiness_gain_db']):g}",
                f"equalizer=f={cast(int, eq['harshness_freq_hz'])}:t=q:w=1:g={cast(float, eq['harshness_gain_db']):g}",
            ]
        )
    if cast(bool, loudnorm["enabled"]):
        filters.append(
            f"loudnorm=I={cast(float, loudnorm['I']):g}"
            f":LRA={cast(float, loudnorm['LRA']):g}"
            f":TP={cast(float, loudnorm['TP']):g}"
        )
    if cast(bool, limiter["enabled"]):
        filters.append(f"alimiter=limit={cast(float, limiter['limit']):g}")
    return ",".join(filters) if filters else "anull"


def build_ffmpeg_cmd(source: Path, output: Path, settings: object, bitrate: str) -> list[str]:
    return [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-af",
        build_filter(settings),
        "-c:a",
        "libmp3lame",
        "-b:a",
        bitrate,
        str(output),
    ]


def _adjust_master_unlocked(collection_dir: Path, *, quiet: bool = False) -> Path:
    """Rebuild master.mp3 from the immutable pre-adjust backup without cumulative effects."""
    paths = CollectionPaths(collection_dir)
    master = paths.master_audio_path
    backup = paths.master_adjustment_backup_path
    collection_root = collection_dir.resolve()
    for candidate, label in ((master, "master"), (backup, "master 調整原本")):
        if not candidate.parent.resolve().is_relative_to(collection_root):
            raise ValidationError(f"{label} の保存先が collection 外を指しています: {candidate}")
    if not master.is_file() or master.is_symlink():
        raise ValidationError(f"マスター音源が見つかりません: {master}")
    if backup.exists() and (not backup.is_file() or backup.is_symlink()):
        raise ValidationError(f"master 調整原本は通常ファイルである必要があります: {backup}")
    if shutil.which("ffmpeg") is None:
        raise ValidationError("ffmpeg が見つかりません (brew install ffmpeg など)")

    document = read_audio_adjustments(paths.audio_adjustments_path)
    if document.master is None:
        raise ValidationError("audio-adjustments.json に master 調整値がありません")
    skill_config = load_skill_config(
        _SKILL_NAME,
        channel_dir=_channel_dir_for_collection(collection_dir),
    )
    audio = skill_config.get("audio", {})
    bitrate = str(audio.get("bitrate", _DEFAULT_BITRATE)) if isinstance(audio, Mapping) else _DEFAULT_BITRATE
    source = backup if backup.exists() else master
    temporary = master.with_name("master.tmp.mp3")
    temporary.unlink(missing_ok=True)
    completed = subprocess.run(
        build_ffmpeg_cmd(source, temporary, document.master, bitrate),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        temporary.unlink(missing_ok=True)
        detail = completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else "stderr なし"
        raise ValidationError(f"master 調整の ffmpeg が失敗しました (rc={completed.returncode}): {detail}")
    if not temporary.is_file():
        raise ValidationError("master 調整の一時出力が生成されませんでした")

    backup_created = False
    try:
        if not backup.exists():
            backup.parent.mkdir(parents=True, exist_ok=True)
            os.replace(master, backup)
            backup_created = True
        os.replace(temporary, master)
    except OSError as error:
        if backup_created and backup.exists() and not master.exists():
            os.replace(backup, master)
        temporary.unlink(missing_ok=True)
        raise ValidationError(f"master 調整結果を置換できません: {error}") from error

    if not quiet:
        print(f"Adjusted: {master}")
        print(f"Original: {backup}")
    return master


def adjust_master(collection_dir: Path, *, quiet: bool = False) -> Path:
    """Serialize CLI and UI adjustment so backup creation and replacement cannot race."""
    with file_lock(CollectionPaths(collection_dir).master_audio_path):
        return _adjust_master_unlocked(collection_dir, quiet=quiet)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="保存済み Audio Studio 設定を master.mp3 全体へ適用")
    parser.add_argument("collection", nargs="?", help="コレクションディレクトリ (省略時は CWD)")
    parser.add_argument("--quiet", action="store_true", help="完了表示を抑制")
    return parser


def run(args: argparse.Namespace) -> int:
    adjust_master(resolve_collection_dir(args.collection), quiet=args.quiet)
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_cli(build_parser, run, argv, failure_message="master 調整に失敗しました")


if __name__ == "__main__":
    raise SystemExit(main())
