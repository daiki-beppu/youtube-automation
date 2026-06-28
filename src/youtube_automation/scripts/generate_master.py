#!/usr/bin/env python3
"""コレクションの個別音声 (MP3 / M4A / WAV) をクロスフェード結合してマスター音源を生成する。

skill-config (`masterup.audio.crossfade_duration` / `bitrate`) を参照するため、
`metadata_generator` のタイムスタンプ計算と常に同じクロスフェード秒数で結合される。

入力は `.mp3` / `.m4a` / `.wav` を受け付け、出力は常に `master.mp3`
(`libmp3lame -b:a {bitrate} -q:a 0`) に統一する。

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

# skill-config (`masterup.audio.<KEY>`) のキー名。CLI `--pin-first` / `--pin-first-count`
# 未指定時のデフォルトとして参照される。
_PIN_FIRST_COUNT_KEY = "pin_first_count"

# 自動生成 seed の上限（ログ・再現用に 32-bit unsigned 範囲）。
_AUTO_SEED_BOUND = 2**32

# 対応する入力音声フォーマット。出力は常に MP3 に統一する。
_AUDIO_INPUT_EXTENSIONS = ("mp3", "m4a", "wav")
_OUTPUT_CODEC = ["-c:a", "libmp3lame"]


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


def _estimate_looped_duration(single_loop_sec: float, loops: int, crossfade: float) -> float:
    """ループ展開後の理論尺を秒で返す。"""
    return max(0.0, loops * single_loop_sec - max(0, loops - 1) * crossfade)


def _print_duration_preview(
    *,
    single_loop_sec: float,
    effective_loops: int,
    crossfade: float,
    target_duration_min: int | None,
    no_loop: bool,
) -> None:
    """目標尺とループ回数の事前見積もりを表示する。"""
    estimated = _estimate_looped_duration(single_loop_sec, effective_loops, crossfade)
    print("  Duration preview")
    print(f"    Track total : {_format_duration(single_loop_sec)}")
    if target_duration_min is not None:
        target_sec = target_duration_min * 60
        print(f"    Target      : {_format_duration(target_sec)}")
    elif no_loop:
        print("    Target      : disabled by --no-loop")
    print(f"    Loop count  : {effective_loops}")
    print(f"    Estimated   : {_format_duration(estimated)}")
    if no_loop and target_duration_min is not None and single_loop_sec < target_duration_min * 60:
        shortage = target_duration_min * 60 - single_loop_sec
        print(f"    Note        : 1 パスでは目標尺に {_format_duration(shortage)} 不足します")


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


def _collect_audio_inputs(music_dir: Path) -> list[Path]:
    """`music_dir` から対応音声ファイルを拡張子混在込みで列挙する。"""
    matches: list[Path] = []
    for ext in _AUDIO_INPUT_EXTENSIONS:
        matches.extend(music_dir.glob(f"*.{ext}"))

    if not matches:
        supported = ", ".join(f".{e}" for e in _AUDIO_INPUT_EXTENSIONS)
        raise ValidationError(f"音声ファイル ({supported}) が見つかりません: {music_dir}")
    return sorted(matches, key=lambda p: p.name)


def _apply_pin_first(
    files: list[Path],
    *,
    pin_first: list[str] | None,
    pin_first_count: int | None,
) -> tuple[list[Path], list[Path]]:
    """先頭固定を解決して (pinned, remaining) に分離する。

    - `pin_first` / `pin_first_count` 両方未指定（または 0） → ([], files) を返す（互換）
    - `pin_first` 指定 → 引数順に files から抽出して pinned に積む。未存在ファイルは
      `ValidationError`（要件 10: fail-loud）
    - `pin_first_count` 指定 → ソート済み先頭 N 件を pinned に積む。N が files 数を
      超える場合は `ValidationError`
    - 両方同時指定は呼び出し側で弾く前提（mutually exclusive）
    """
    if pin_first and pin_first_count:
        # 呼び出し側で argparse / main() が弾く前提だが防御として明示エラー化
        raise ValidationError("pin_first と pin_first_count は同時指定できません (mutually exclusive)")

    if pin_first:
        by_name = {p.name: p for p in files}
        pinned: list[Path] = []
        missing: list[str] = []
        for name in pin_first:
            target = by_name.get(name)
            if target is None:
                missing.append(name)
            else:
                pinned.append(target)
        if missing:
            available = ", ".join(p.name for p in files)
            raise ValidationError(f"--pin-first で指定したファイルが見つかりません: {missing} (利用可能: {available})")
        remaining = [p for p in files if p not in pinned]
        return pinned, remaining

    if pin_first_count and pin_first_count > 0:
        if pin_first_count > len(files):
            raise ValidationError(f"pin_first_count={pin_first_count} がトラック数 {len(files)} を超えています")
        pinned = files[:pin_first_count]
        remaining = files[pin_first_count:]
        return pinned, remaining

    return [], files


def generate_master(
    collection_dir: Path,
    crossfade: float,
    bitrate: str,
    *,
    loops: int | None = None,
    target_duration_min: int | None = None,
    no_loop: bool = False,
    shuffle: bool = False,
    shuffle_seed: int | None = None,
    pin_first: list[str] | None = None,
    pin_first_count: int | None = None,
    quiet: bool = False,
) -> Path:
    paths = CollectionPaths(collection_dir)
    music_dir = paths.music_dir
    master_dir = paths.master_dir

    if shutil.which("ffmpeg") is None:
        raise ValidationError("ffmpeg が見つかりません (brew install ffmpeg など)")
    if not music_dir.is_dir():
        raise ValidationError(f"ディレクトリが見つかりません: {music_dir}")

    files = _collect_audio_inputs(music_dir)
    n = len(files)

    # 先頭固定を解決 (要件 1-4, 10): pin された曲は順序固定、残りを shuffle 対象とする。
    pinned, remaining = _apply_pin_first(
        files,
        pin_first=pin_first,
        pin_first_count=pin_first_count,
    )

    # ループ展開前にシャッフルする (要件 8: 同一シャッフル順を N 回繰り返す)。
    # 再現性ログは quiet モードでも常に stdout に出す (要件 4)。
    # pin がある場合は pinned を順序固定したまま remaining のみ shuffle する。
    if shuffle:
        effective_seed = shuffle_seed if shuffle_seed is not None else random.SystemRandom().randrange(_AUTO_SEED_BOUND)
        random.Random(effective_seed).shuffle(remaining)
        print(f"[Shuffle] seed={effective_seed}")

    files = pinned + remaining
    if pinned:
        print(f"[Pin] first {len(pinned)} track(s) fixed: {[p.name for p in pinned]}")

    should_print_duration_preview = (not quiet) and (target_duration_min is not None or loops is not None or no_loop)
    needs_duration_probe = target_duration_min is not None or should_print_duration_preview
    single_loop_sec = _sum_track_duration(files) if needs_duration_probe else 0.0
    effective_loops = _resolve_loop_count(loops, target_duration_min, single_loop_sec, crossfade)

    expanded = files * effective_loops
    n_effective = len(expanded)

    master_dir.mkdir(parents=True, exist_ok=True)
    output = master_dir / "master.mp3"

    if not quiet:
        loop_note = f" × {effective_loops} loops = {n_effective} segments" if effective_loops > 1 else ""
        print()
        print("  yt-generate-master")
        print("  ──────────────────────────────────────────")
        print()
        input_exts = ", ".join(sorted({p.suffix.lstrip('.').upper() for p in files}))
        print(f"  Input : {n} audio files ({input_exts}){loop_note}")
        print(f"  Output: {output.name}")
        print(f"  Crossfade: {crossfade:g}s (triangle curve)")
        print(f"  Bitrate  : {bitrate}")
        if should_print_duration_preview:
            print()
            _print_duration_preview(
                single_loop_sec=single_loop_sec,
                effective_loops=effective_loops,
                crossfade=crossfade,
                target_duration_min=target_duration_min,
                no_loop=no_loop,
            )
        print()

    if n_effective == 1 and expanded[0].suffix.lower() == ".mp3":
        shutil.copyfile(expanded[0], output)
        if not quiet:
            print("  Single file — copied directly.\n")
        return output

    if n_effective == 1:
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(expanded[0]),
            *_OUTPUT_CODEC,
            "-b:a",
            bitrate,
            "-q:a",
            "0",
            str(output),
            "-loglevel",
            "error",
        ]
    else:
        cmd = ["ffmpeg", "-y"]
        for f in expanded:
            cmd.extend(["-i", str(f)])
        cmd.extend(
            [
                "-filter_complex",
                build_filter(n_effective, crossfade),
                "-map",
                "[aout]",
                *_OUTPUT_CODEC,
                "-b:a",
                bitrate,
                "-q:a",
                "0",
                str(output),
                "-loglevel",
                "error",
            ]
        )

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
        description="個別音声 (MP3 / M4A / WAV) をクロスフェード結合して master.mp3 を生成",
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
    loop_group.add_argument(
        "--no-loop",
        action="store_true",
        dest="no_loop",
        help="skill-config の target_duration_min を使わず 1 パスで生成する (--loop 1 相当)",
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
    pin_group = parser.add_mutually_exclusive_group()
    pin_group.add_argument(
        "--pin-first",
        nargs="+",
        metavar="FILE",
        dest="pin_first",
        help="先頭固定する MP3 ファイル名を順番指定 (--shuffle 併用可、引数順を保持)",
    )
    pin_group.add_argument(
        "--pin-first-count",
        type=int,
        metavar="N",
        dest="pin_first_count",
        help="ソート済み先頭 N 件を固定 (連番ファイル名運用と整合、--shuffle 併用可)",
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

        # CLI フラグ (--loop / --target-duration / --no-loop) がすべて未指定なら
        # skill-config の `audio.target_duration_min` をデフォルト値として採用する。
        # --loop 指定時は loops 指定が最優先のため skill-config 値を黙って無視する。
        target_duration: int | None = args.target_duration
        no_loop_target_duration: int | None = None
        if args.no_loop:
            skill_target = audio.get(_TARGET_DURATION_MIN_KEY)
            if skill_target is not None:
                no_loop_target_duration = int(skill_target)
                if no_loop_target_duration < 1:
                    raise ValidationError(
                        f"skill-config masterup.audio.{_TARGET_DURATION_MIN_KEY} は 1 以上を指定してください"
                    )
        elif args.loop is None and args.target_duration is None:
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

        # CLI > skill-config の優先順位で pin_first / pin_first_count を解決。
        # CLI で --pin-first または --pin-first-count のいずれかが指定されていれば
        # CLI 優先で skill-config の `audio.pin_first_count` は黙って無視する。
        pin_first: list[str] | None = args.pin_first
        pin_first_count: int | None = args.pin_first_count

        if args.pin_first_count is not None and args.pin_first_count < 0:
            raise ValidationError("--pin-first-count は 0 以上を指定してください")

        if pin_first is None and pin_first_count is None:
            skill_pin_count = audio.get(_PIN_FIRST_COUNT_KEY)
            if skill_pin_count is not None:
                # bool は int サブクラスのため明示的に除外する。
                if isinstance(skill_pin_count, bool) or not isinstance(skill_pin_count, int):
                    raise ValidationError(
                        f"skill-config masterup.audio.{_PIN_FIRST_COUNT_KEY} は整数で指定してください"
                    )
                if skill_pin_count < 0:
                    raise ValidationError(
                        f"skill-config masterup.audio.{_PIN_FIRST_COUNT_KEY} は 0 以上を指定してください"
                    )
                # 0 は「固定なし」として扱う (互換: 未設定と等価)
                if skill_pin_count > 0:
                    pin_first_count = skill_pin_count

        generate_master(
            collection_dir,
            crossfade,
            bitrate,
            loops=1 if args.no_loop else args.loop,
            target_duration_min=no_loop_target_duration if args.no_loop else target_duration,
            no_loop=args.no_loop,
            shuffle=shuffle_enabled,
            shuffle_seed=shuffle_seed,
            pin_first=pin_first,
            pin_first_count=pin_first_count,
            quiet=args.quiet,
        )
    except ValidationError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
