#!/usr/bin/env python3
"""Lyria 3 で N セグメント生成 → クロスフェード結合してマスター音源を作る統合 CLI。

Lyria 3 `interactions` API は 1 リクエスト最大約 184 秒の MP3 を返す。
コレクション尺 (30 分〜数時間) のマスター音源を作るには複数セグメントが必要なため、
本 CLI は以下を逐次実行する:

1. `audio.target_duration_min` + 余裕分から呼び出し回数 N を自動算出
2. `lyria_client.generate_music()` を N 回呼び、MP3 バイト列を ffmpeg で WAV (PCM s16le,
   48 kHz stereo) に変換して `02-Individual-music/{NN}_{name}.wav` に保存
3. 失敗時は最大 `--max-retries` 回リトライ (`generate_music_dj._generate_one_segment` 流儀)
4. 既存セグメントがあれば skip (resume 可能)
5. 全セグメント揃ったら `generate_master.generate_master()` を呼び、
   `01-master/master.wav` を出力 (`yt-generate-master` の WAV 経路を再利用)

Usage:
    yt-generate-lyria-master --prompt "<prompt>" --name <slug>
    yt-generate-lyria-master --prompt ... --name ... --target-duration 90 --bpm 72

設計判断:
- Lyria 3 API は MP3 を返すが、保存形式は `generate_music_dj` の慣例に合わせ WAV (PCM)。
  クロスフェード結合段で再エンコードロスを避けるため。
- `generate_master.generate_master()` を Python 関数として呼び、`build_filter` /
  `_resolve_loop_count` を流用する (DRY)。WAV 入力経路は #277 で同時実装。
- セグメント間のフェーズ展開 (DJ 的なプロンプト切り替え) は本 CLI の責務外
  (Issue #279 scope 外、別 issue 待ち)。同一プロンプトの N 回呼び出しに留める。
"""

from __future__ import annotations

import argparse
import math
import subprocess
import sys
import time
from pathlib import Path
from typing import cast

from youtube_automation.scripts import generate_master
from youtube_automation.utils import cost_tracker, lyria_client
from youtube_automation.utils.collection_paths import (
    CollectionPaths,
    resolve_collection_dir,
)
from youtube_automation.utils.config import load_config
from youtube_automation.utils.exceptions import ConfigError, ValidationError
from youtube_automation.utils.lyria_client import Intensity, Mode
from youtube_automation.utils.skill_config import load_skill_config

# Lyria 3 Pro は 1 リクエスト最大約 184 秒の音源を返すため、コレクション尺から
# 必要呼び出し回数を割り出す基準として使う。short 化や引き伸ばしのトリミングは行わない。
_LYRIA_SEGMENT_SEC = 184

# `generate_music_dj._save_audio_as_wav` と揃える (ffmpeg 経由で PCM s16le に正規化する設定)。
_WAV_SAMPLE_RATE = 48000
_WAV_CHANNELS = 2

# skill-config key names — 1 箇所に集約しておいてキー名のタイポを検出可能にする。
_SKILL_LYRIA = "lyria"
_SKILL_MASTERUP = "masterup"
_KEY_DURATION_PADDING_MIN = "duration_padding_min"
_KEY_MODEL = "model"
_KEY_CROSSFADE_DURATION = "crossfade_duration"
_KEY_BITRATE = "bitrate"


def _resolve_segment_count(target_min: float, padding_min: float) -> int:
    """target + 余裕分から必要セグメント数 N を算出する。

    `(target_min + padding_min) * 60 / 184` を切り上げ。
    `target_min > 0` を validate するため戻り値は必ず 1 以上になる。
    """
    if target_min <= 0:
        raise ValidationError(f"--target-duration は 1 以上を指定してください (got {target_min})")
    if padding_min < 0:
        raise ValidationError(f"--padding-min は 0 以上を指定してください (got {padding_min})")
    total_sec = (target_min + padding_min) * 60
    return math.ceil(total_sec / _LYRIA_SEGMENT_SEC)


def _save_audio_as_wav(data: bytes, path: Path) -> None:
    """Lyria の MP3 バイト列を PCM s16le 48 kHz stereo WAV に変換して保存する。

    `generate_music_dj._save_audio_as_wav` と同じ変換ロジック。クロスフェード結合段で
    再エンコードロスを避けるため、個別セグメントは可逆フォーマットで保持する。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_bytes(data)
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(tmp_path),
                "-ar",
                str(_WAV_SAMPLE_RATE),
                "-ac",
                str(_WAV_CHANNELS),
                "-sample_fmt",
                "s16",
                "-f",
                "wav",
                str(path),
            ],
            capture_output=True,
            check=True,
        )
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def _segment_path(music_dir: Path, index: int, name: str) -> Path:
    """`02-Individual-music/{NN}_{name}.wav` のパスを構築する (1-origin、ゼロ埋め 2 桁)。"""
    return music_dir / f"{index:02d}_{name}.wav"


def _generate_one_segment(
    *,
    index: int,
    seg_path: Path,
    prompt: str,
    model: str,
    reference_image: Path | None,
    bpm: int | None,
    intensity: str | None,
    mode: str | None,
    lyrics: str | None,
    max_retries: int,
) -> bool:
    """1 セグメントを生成して WAV 保存する。既存ファイルは skip、失敗は最大 max_retries 回リトライ。"""
    label = f"seg_{index:02d}"

    if seg_path.exists():
        print(f"  [skip] {label} — 既に存在 ({seg_path.name})")
        return True

    print(f"\n  [{label}] 生成中 → {seg_path.name}")

    for attempt in range(max_retries + 1):
        if attempt > 0:
            wait_sec = min(30, 10 * attempt)
            print(f"    [{label}] retry {attempt}/{max_retries} ({wait_sec}s 待機)")
            time.sleep(wait_sec)

        audio_bytes = lyria_client.generate_music(
            prompt,
            model,
            reference_image=reference_image,
            bpm=bpm,
            # argparse の `choices` で値域は保証済みだが型は str のため、
            # Literal 型へ narrow する (`type: ignore` を残さない)。
            intensity=cast(Intensity | None, intensity),
            mode=cast(Mode | None, mode),
            lyrics=lyrics,
        )
        if audio_bytes is None:
            continue

        _save_audio_as_wav(audio_bytes, seg_path)
        size_kb = seg_path.stat().st_size / 1024
        print(f"  [{label}] 完了 ({size_kb:.0f} KB)")
        metadata: dict = {
            "segment": label,
            "output_file": cost_tracker.relative_to_channel_dir(seg_path),
        }
        if bpm is not None:
            metadata["bpm"] = bpm
        if intensity:
            metadata["intensity"] = intensity
        if mode:
            metadata["mode"] = mode
        if reference_image is not None:
            metadata["reference_image"] = str(reference_image)
        if lyrics:
            metadata["has_lyrics"] = True
        cost_tracker.log_generation("audio", model=model, quantity=1, metadata=metadata)
        return True

    print(f"  [{label}] {max_retries + 1} 回失敗")
    return False


def _resolve_reference_image(ref: str | None, collection_dir: Path) -> Path | None:
    """`--reference-image` をコレクションルート基点で解決する。指定無しは None。"""
    if ref is None:
        return None
    p = Path(ref)
    if not p.is_absolute():
        p = (collection_dir / p).resolve()
    if not p.exists():
        raise ConfigError(f"参照画像が存在しません: {p}")
    return p


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Lyria 3 で N セグメント生成 → クロスフェード結合してマスター音源を作る",
    )
    parser.add_argument("--prompt", required=True, help="Lyria 3 に渡すプロンプト本文 (必須)")
    parser.add_argument(
        "--name",
        required=True,
        help="セグメントファイル名スラグ (例: rain-against-glass → 02-Individual-music/01_rain-against-glass.wav)",
    )
    parser.add_argument(
        "--collection",
        help="コレクションディレクトリ (省略時は CWD)",
    )
    parser.add_argument("--model", help=f"Lyria モデル名 (省略時は skill-config lyria.{_KEY_MODEL})")
    parser.add_argument(
        "--target-duration",
        type=float,
        dest="target_duration",
        help="目標尺 (分)。省略時は config/channel/audio.json の audio.target_duration_min を使用",
    )
    parser.add_argument(
        "--padding-min",
        type=float,
        dest="padding_min",
        help=f"target に上乗せする余裕分 (分)。省略時は skill-config lyria.{_KEY_DURATION_PADDING_MIN}",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        dest="max_retries",
        help="1 セグメントあたりの失敗時リトライ回数 (default: 3)",
    )
    parser.add_argument("--bpm", type=int, help="BPM (60-180 目安、プロンプトに自動合成)")
    parser.add_argument(
        "--intensity",
        choices=("low", "medium", "high"),
        help="強度 (プロンプトに自然言語化して埋め込む)",
    )
    parser.add_argument(
        "--mode",
        choices=("instrumental", "vocal"),
        help="楽器のみ / 歌入り",
    )
    parser.add_argument(
        "--reference-image",
        dest="reference_image",
        help="参照画像パス (コレクション相対 or 絶対)。例: 10-assets/main.png",
    )
    parser.add_argument("--lyrics", help="歌詞テキスト (mode=vocal 時に使う)")
    return parser


def _resolve_target_duration(args_target: float | None) -> float:
    """`--target-duration` > config/channel/audio.json の優先順位で目標尺を解決する。"""
    if args_target is not None:
        return args_target
    cfg_target = load_config().audio.target_duration_min
    if cfg_target is None:
        raise ValidationError(
            "目標尺が決まりません。--target-duration を指定するか、"
            "config/channel/audio.json の audio.target_duration_min を設定してください"
        )
    return float(cfg_target)


def _resolve_padding_min(args_padding: float | None, lyria_cfg: dict) -> float:
    """`--padding-min` > skill-config の優先順位で余裕分を解決する。

    `duration_padding_min` は config.default.yaml に必ず存在するため、欠落時は
    skill-config 側の不整合を示す ConfigError として扱う (Fail Fast)。
    """
    if args_padding is not None:
        return args_padding
    value = lyria_cfg.get(_KEY_DURATION_PADDING_MIN)
    if value is None:
        raise ConfigError(
            f"skill-config lyria.{_KEY_DURATION_PADDING_MIN} が未設定です "
            "(config.default.yaml が壊れている可能性があります)"
        )
    return float(value)


def _resolve_model(args_model: str | None, lyria_cfg: dict) -> str:
    """`--model` > skill-config の優先順位でモデル名を解決する。"""
    if args_model:
        return args_model
    model = lyria_cfg.get(_KEY_MODEL)
    if not model:
        raise ConfigError(
            f"skill-config lyria.{_KEY_MODEL} が未設定です (config.default.yaml が壊れている可能性があります)"
        )
    return str(model)


def _resolve_masterup_audio(masterup_cfg: dict) -> tuple[float, str]:
    """masterup skill-config から `crossfade_duration` / `bitrate` を取り出す。

    両キーは `config.default.yaml` に必ず存在するため、欠落時は skill-config 側の
    不整合を示す ConfigError として扱う (`_resolve_padding_min` と同じ Fail Fast 方針)。
    """
    crossfade_raw = masterup_cfg.get(_KEY_CROSSFADE_DURATION)
    if crossfade_raw is None:
        raise ConfigError(
            f"skill-config masterup.audio.{_KEY_CROSSFADE_DURATION} が未設定です "
            "(config.default.yaml が壊れている可能性があります)"
        )
    bitrate_raw = masterup_cfg.get(_KEY_BITRATE)
    if bitrate_raw is None:
        raise ConfigError(
            f"skill-config masterup.audio.{_KEY_BITRATE} が未設定です "
            "(config.default.yaml が壊れている可能性があります)"
        )
    return float(crossfade_raw), str(bitrate_raw)


def main() -> int:
    try:
        from dotenv import find_dotenv, load_dotenv

        load_dotenv(find_dotenv())
    except ImportError:
        pass

    parser = _build_arg_parser()
    args = parser.parse_args()

    try:
        collection_dir = resolve_collection_dir(args.collection)
        paths = CollectionPaths(collection_dir)
        music_dir = paths.music_dir
        music_dir.mkdir(parents=True, exist_ok=True)

        lyria_cfg = load_skill_config(_SKILL_LYRIA)
        masterup_cfg = load_skill_config(_SKILL_MASTERUP).get("audio", {})

        target_min = _resolve_target_duration(args.target_duration)
        padding_min = _resolve_padding_min(args.padding_min, lyria_cfg)
        n = _resolve_segment_count(target_min, padding_min)
        model = _resolve_model(args.model, lyria_cfg)
        reference_image = _resolve_reference_image(args.reference_image, collection_dir)

        crossfade, bitrate = _resolve_masterup_audio(masterup_cfg)

        print()
        print("  yt-generate-lyria-master")
        print("  ──────────────────────────────────────────")
        print(f"  Collection : {collection_dir}")
        print(
            f"  Segments   : {n}  (target {target_min:g}min + padding {padding_min:g}min @ {_LYRIA_SEGMENT_SEC}s/seg)"
        )
        print(f"  Model      : {model}")
        if args.bpm is not None:
            print(f"  BPM        : {args.bpm}")
        if args.intensity:
            print(f"  Intensity  : {args.intensity}")
        if args.mode:
            print(f"  Mode       : {args.mode}")
        if reference_image is not None:
            print(f"  Reference  : {reference_image}")
        print()

        for i in range(1, n + 1):
            seg_path = _segment_path(music_dir, i, args.name)
            ok = _generate_one_segment(
                index=i,
                seg_path=seg_path,
                prompt=args.prompt,
                model=model,
                reference_image=reference_image,
                bpm=args.bpm,
                intensity=args.intensity,
                mode=args.mode,
                lyrics=args.lyrics,
                max_retries=args.max_retries,
            )
            if not ok:
                print()
                print("  成功済みセグメントは保持されています。再実行で続行できます。")
                return 1

        print()
        print(f"  === セグメント生成完了 ({n} segments) → クロスフェード結合 ===")
        master_path = generate_master.generate_master(
            collection_dir,
            crossfade,
            bitrate,
        )
        print()
        print(f"  Master audio: {master_path}")

        cost_tracker.print_last_report()

    except (ConfigError, ValidationError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
