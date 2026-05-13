#!/usr/bin/env python3
"""コレクションの個別音声 (MP3 / WAV) をクロスフェード結合してマスター音源を生成する。

skill-config (`masterup.audio.crossfade_duration` / `bitrate`) を参照するため、
`metadata_generator` のタイムスタンプ計算と常に同じクロスフェード秒数で結合される。

入力ファイルの拡張子に追従して出力フォーマットが決まる:
- すべて `.mp3` → `master.mp3` (`libmp3lame -b:a {bitrate} -q:a 0`)
- すべて `.wav` → `master.wav` (`pcm_s16le`、ビットレートは無視)
MP3 と WAV が混在しているディレクトリは `ValidationError` で明示的に失敗させる
(出力フォーマットを一意に決められないため)。

Usage:
    yt-generate-master                   # CWD がコレクションディレクトリ
    yt-generate-master <collection-path>
"""

from __future__ import annotations

import argparse
import math
import random
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from youtube_automation.utils.collection_paths import (
    CollectionPaths,
    resolve_collection_dir,
)
from youtube_automation.utils.exceptions import ValidationError
from youtube_automation.utils.probe import probe_duration
from youtube_automation.utils.skill_config import load_skill_config

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

# skill-config (`masterup.audio.<KEY>`) のキー名。CLI フラグ未指定時に
# `--target-duration` 相当のデフォルトとして参照される。
_TARGET_DURATION_MIN_KEY = "target_duration_min"

# skill-config (`masterup.audio.<KEY>`) のキー名。CLI `--shuffle` / `--shuffle-seed`
# 未指定時のデフォルトとして参照される。
_SHUFFLE_KEY = "shuffle"
_SHUFFLE_SEED_KEY = "shuffle_seed"

# 自動生成 seed の上限（ログ・再現用に 32-bit unsigned 範囲）。
_AUTO_SEED_BOUND = 2**32

# 対応する入力音声フォーマット。拡張子 (lower, ドットなし) → ffmpeg コーデックオプション。
# 出力 `master.<ext>` の拡張子もここで決まる。
_AUDIO_FORMATS: dict[str, list[str]] = {
    "mp3": ["-c:a", "libmp3lame"],
    "wav": ["-c:a", "pcm_s16le"],
}


def build_filter(n: int, crossfade: float) -> str:
    """N 入力を acrossfade で直列結合する filter_complex を生成する。"""
    d = f"{crossfade:g}"
    if n == 2:
        return f"[0:a][1:a]acrossfade=d={d}:c1=tri:c2=tri[aout]"

    parts = [f"[0:a][1:a]acrossfade=d={d}:c1=tri:c2=tri[cf1]"]
    for i in range(2, n - 1):
        parts.append(f"[cf{i - 1}][{i}:a]acrossfade=d={d}:c1=tri:c2=tri[cf{i}]")
    parts.append(f"[cf{n - 2}][{n - 1}:a]acrossfade=d={d}:c1=tri:c2=tri[aout]")
    return ";".join(parts)


def _sum_track_duration(files: list[Path]) -> float:
    """個別トラックの尺を合算する。probe に失敗したファイルがあれば ValidationError。"""
    total = 0.0
    for f in files:
        dur = probe_duration(f)
        if dur is None:
            raise ValidationError(f"トラック尺の probe に失敗: {f}")
        total += dur
    return total


def _resolve_loop_count(
    explicit_loops: int | None,
    target_duration_min: int | None,
    single_loop_sec: float,
    crossfade: float,
) -> int:
    """--loop / --target-duration から最終ループ回数を算出する。

    M ループの理論尺は M 個のシングルループを末尾↔先頭 crossfade で連結するため:
        M * single_loop_sec - (M - 1) * crossfade
    これが target_sec 以上となる最小の M を返す。両オプション未指定なら 1。
    """
    if explicit_loops is not None:
        return explicit_loops
    if target_duration_min is not None:
        target_sec = target_duration_min * 60
        span = max(single_loop_sec - crossfade, 1e-6)
        loops = math.ceil((target_sec - crossfade) / span)
        return max(1, loops)
    return 1


def _format_duration(seconds: float) -> str:
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m:02d}m {s:02d}s"


def _format_size(num_bytes: int) -> str:
    for unit in ("B", "K", "M", "G"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f}{unit}"
        num_bytes /= 1024  # type: ignore[assignment]
    return f"{num_bytes:.1f}T"


def _spin(stop_event: threading.Event, start: float, segments: int) -> None:
    i = 0
    while not stop_event.wait(0.15):
        elapsed = int(time.monotonic() - start)
        m, s = divmod(elapsed, 60)
        sys.stderr.write(
            f"\r  {SPINNER_FRAMES[i % len(SPINNER_FRAMES)]} Generating... "
            f"({m}m{s:02d}s) [{segments} segments, {segments - 1} crossfades]  "
        )
        sys.stderr.flush()
        i += 1


def _collect_audio_inputs(music_dir: Path) -> tuple[list[Path], str]:
    """`music_dir` から `_AUDIO_FORMATS` 対応の音声ファイルを列挙し、(files, ext) を返す。

    - すべて同一拡張子なら (sorted files, ext) を返す。
    - 2 種類以上の拡張子が混在していれば `ValidationError` (出力 master.<ext> を一意に決められない)。
    - 1 件も見つからなければ `ValidationError`。
    """
    matches_by_ext: dict[str, list[Path]] = {}
    for ext in _AUDIO_FORMATS:
        found = sorted(music_dir.glob(f"*.{ext}"))
        if found:
            matches_by_ext[ext] = found

    if not matches_by_ext:
        supported = ", ".join(f".{e}" for e in _AUDIO_FORMATS)
        raise ValidationError(f"音声ファイル ({supported}) が見つかりません: {music_dir}")
    if len(matches_by_ext) > 1:
        found_labels = ", ".join(f".{e}({len(v)})" for e, v in matches_by_ext.items())
        raise ValidationError(
            f"音声フォーマットが混在しています (出力フォーマットを一意に決められません): {music_dir} [{found_labels}]"
        )
    ext, files = next(iter(matches_by_ext.items()))
    return files, ext


def generate_master(
    collection_dir: Path,
    crossfade: float,
    bitrate: str,
    *,
    loops: int | None = None,
    target_duration_min: int | None = None,
    shuffle: bool = False,
    shuffle_seed: int | None = None,
    quiet: bool = False,
) -> Path:
    paths = CollectionPaths(collection_dir)
    music_dir = paths.music_dir
    master_dir = paths.master_dir

    if shutil.which("ffmpeg") is None:
        raise ValidationError("ffmpeg が見つかりません (brew install ffmpeg など)")
    if not music_dir.is_dir():
        raise ValidationError(f"ディレクトリが見つかりません: {music_dir}")

    files, audio_ext = _collect_audio_inputs(music_dir)
    n = len(files)

    # ループ展開前にシャッフルする (要件 8: 同一シャッフル順を N 回繰り返す)。
    # 再現性ログは quiet モードでも常に stdout に出す (要件 4)。
    if shuffle:
        effective_seed = shuffle_seed if shuffle_seed is not None else random.SystemRandom().randrange(_AUTO_SEED_BOUND)
        random.Random(effective_seed).shuffle(files)
        print(f"[Shuffle] seed={effective_seed}")

    single_loop_sec = _sum_track_duration(files) if target_duration_min is not None else 0.0
    effective_loops = _resolve_loop_count(loops, target_duration_min, single_loop_sec, crossfade)

    expanded = files * effective_loops
    n_effective = len(expanded)

    master_dir.mkdir(parents=True, exist_ok=True)
    output = master_dir / f"master.{audio_ext}"

    # WAV (PCM) は bitrate オプションを取らないため、表示と ffmpeg コマンドの両方で扱いを分ける。
    use_bitrate = audio_ext == "mp3"

    if not quiet:
        loop_note = f" × {effective_loops} loops = {n_effective} segments" if effective_loops > 1 else ""
        print()
        print("  yt-generate-master")
        print("  ──────────────────────────────────────────")
        print()
        print(f"  Input : {n} {audio_ext.upper()} files{loop_note}")
        print(f"  Output: {output.name}")
        print(f"  Crossfade: {crossfade:g}s (triangle curve)")
        if use_bitrate:
            print(f"  Bitrate  : {bitrate}")
        print()

    if n_effective == 1:
        shutil.copyfile(expanded[0], output)
        if not quiet:
            print("  Single file — copied directly.\n")
        return output

    cmd = ["ffmpeg", "-y"]
    for f in expanded:
        cmd.extend(["-i", str(f)])
    cmd.extend(
        [
            "-filter_complex",
            build_filter(n_effective, crossfade),
            "-map",
            "[aout]",
            *_AUDIO_FORMATS[audio_ext],
        ]
    )
    if use_bitrate:
        cmd.extend(["-b:a", bitrate, "-q:a", "0"])
    cmd.extend([str(output), "-loglevel", "error"])

    start = time.monotonic()
    stop_event = threading.Event()
    spinner_thread: threading.Thread | None = None
    if not quiet and sys.stderr.isatty():
        spinner_thread = threading.Thread(target=_spin, args=(stop_event, start, n_effective))
        spinner_thread.start()

    try:
        result = subprocess.run(cmd, check=False)
    finally:
        stop_event.set()
        if spinner_thread is not None:
            spinner_thread.join()
            sys.stderr.write("\r" + " " * 80 + "\r")
            sys.stderr.flush()

    elapsed = int(time.monotonic() - start)
    m, s = divmod(elapsed, 60)

    if result.returncode != 0:
        raise ValidationError(f"FFmpeg failed with exit code {result.returncode}")

    if not quiet:
        sys.stderr.write(
            f"\r  ✓ Generated    ({m}m{s:02d}s) [{n_effective} segments, {n_effective - 1} crossfades]      \n"
        )
        sys.stderr.flush()

        size = _format_size(output.stat().st_size)
        dur = probe_duration(output)
        dur_fmt = _format_duration(dur) if dur is not None else "?"

        print()
        print("  Master audio complete!")
        print()
        print(f"    File    : {output.name}")
        print(f"    Size    : {size}")
        print(f"    Duration: {dur_fmt}")
        print(f"    Time    : {m}m {s:02d}s")
        print()

    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="個別音声 (MP3 / WAV) をクロスフェード結合してマスター音源を生成",
    )
    parser.add_argument(
        "collection",
        nargs="?",
        help="コレクションディレクトリ (省略時は CWD)",
    )
    parser.add_argument("--quiet", action="store_true", help="進捗表示を抑制")
    loop_group = parser.add_mutually_exclusive_group()
    loop_group.add_argument(
        "--loop",
        type=int,
        metavar="N",
        help="ファイルリストを N 回繰り返して acrossfade 連結 (N>=1)",
    )
    loop_group.add_argument(
        "--target-duration",
        type=int,
        metavar="MIN",
        dest="target_duration",
        help="目標尺 (分) 以上になる最小のループ回数を自動算出",
    )
    parser.add_argument(
        "--shuffle",
        action="store_true",
        help="入力 MP3 リストをシャッフルしてから連結",
    )
    parser.add_argument(
        "--shuffle-seed",
        type=int,
        metavar="N",
        dest="shuffle_seed",
        help="シャッフルの再現性 seed (指定すると --shuffle を暗黙有効化)",
    )
    args = parser.parse_args()

    try:
        if args.loop is not None and args.loop < 1:
            raise ValidationError("--loop は 1 以上を指定してください")
        if args.target_duration is not None and args.target_duration < 1:
            raise ValidationError("--target-duration は 1 以上を指定してください")

        collection_dir = resolve_collection_dir(args.collection)
        cfg = load_skill_config("masterup")
        audio = cfg.get("audio", {})
        crossfade = float(audio.get("crossfade_duration", 1.0))
        bitrate = str(audio.get("bitrate", "192k"))

        # CLI フラグ (--loop / --target-duration) が両方未指定なら
        # skill-config の `audio.target_duration_min` をデフォルト値として採用する。
        # --loop 指定時は loops 指定が最優先のため skill-config 値を黙って無視する。
        target_duration: int | None = args.target_duration
        if args.loop is None and args.target_duration is None:
            skill_target = audio.get(_TARGET_DURATION_MIN_KEY)
            if skill_target is not None:
                target_duration = int(skill_target)
                if target_duration < 1:
                    raise ValidationError(
                        f"skill-config masterup.audio.{_TARGET_DURATION_MIN_KEY} は 1 以上を指定してください"
                    )

        # CLI > skill-config > デフォルト の優先順位で shuffle / shuffle_seed を解決。
        # CLI で --shuffle または --shuffle-seed のいずれかが指定されていれば CLI 優先。
        # skill-config 側は `audio.shuffle: true` が明示要求 (`shuffle_seed` 単独では有効化しない)。
        cli_shuffle_specified = args.shuffle or args.shuffle_seed is not None
        shuffle_enabled = cli_shuffle_specified or bool(audio.get(_SHUFFLE_KEY, False))

        shuffle_seed: int | None = args.shuffle_seed
        if shuffle_seed is None:
            skill_seed = audio.get(_SHUFFLE_SEED_KEY)
            if skill_seed is not None:
                # bool は int サブクラスのため明示的に除外する。
                if isinstance(skill_seed, bool) or not isinstance(skill_seed, int):
                    raise ValidationError(f"skill-config masterup.audio.{_SHUFFLE_SEED_KEY} は整数で指定してください")
                shuffle_seed = skill_seed

        generate_master(
            collection_dir,
            crossfade,
            bitrate,
            loops=args.loop,
            target_duration_min=target_duration,
            shuffle=shuffle_enabled,
            shuffle_seed=shuffle_seed,
            quiet=args.quiet,
        )
    except ValidationError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
