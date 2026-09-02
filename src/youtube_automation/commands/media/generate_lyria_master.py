#!/usr/bin/env python3
"""Lyria 3 で N セグメント生成 → クロスフェード結合してマスター音源を作る統合 CLI。

Lyria 3 `interactions` API は 1 リクエスト最大約 184 秒の MP3 を返す。
コレクション尺 (30 分〜数時間) のマスター音源を作るには複数セグメントが必要なため、
本 CLI は以下を逐次実行する:

1. prompt document の entry ごとに目標尺 + 余裕分から呼び出し回数を自動算出
2. `lyria_client.generate_music()` を全文書合計 N 回呼び、MP3 バイト列を ffmpeg で WAV (PCM s16le,
   48 kHz stereo) に変換して `02-Individual-music/{NN}_{name}.wav` に保存
3. 失敗時は最大 `--max-retries` 回リトライ (`generate_music_dj._generate_one_segment` 流儀)
4. 既存セグメントがあれば skip (resume 可能)
5. entry 順の `audio-adjustments.json::order` を保存し、全セグメント揃ったら
   同じ order と `--loop` を渡して `generate_master.generate_master()` を 1 回だけ呼び、
   `01-master/master.mp3` を出力 (`yt-generate-master` の WAV 入力経路を再利用)

Usage:
    yt-generate-lyria-master --prompt "<prompt>" --name <slug>
    yt-generate-lyria-master --prompt ... --name ... --target-duration 90 --bpm 72

設計判断:
- Lyria 3 API は MP3 を返すが、保存形式は `generate_music_dj` の慣例に合わせ WAV (PCM)。
  クロスフェード結合段で再エンコードロスを避けるため。
- `generate_master.generate_master()` を Python 関数として呼び、`build_filter` /
  `_resolve_loop_count` を流用する (DRY)。WAV 入力経路は #277 で同時実装。
- prompt document の entry はパターンとして扱い、entry 内では同一プロンプトを繰り返す。
"""

from __future__ import annotations

import argparse
import math
import subprocess
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from youtube_automation.commands.media import generate_master
from youtube_automation.configuration import load_config
from youtube_automation.configuration.skills import load_skill_config
from youtube_automation.core.errors import ConfigError, ValidationError
from youtube_automation.domains.documents.published import read_published_json_document
from youtube_automation.domains.documents.schema_registry import RepositorySchema
from youtube_automation.domains.media.audio_adjustments import replace_track_order
from youtube_automation.domains.media.audio_units import unit_for_audio
from youtube_automation.infrastructure import cost_tracker
from youtube_automation.infrastructure.media import lyria_client
from youtube_automation.infrastructure.media.collection_paths import (
    CollectionPaths,
    resolve_collection_dir,
)
from youtube_automation.infrastructure.media.lyria_client import Intensity, Mode

# Lyria 3 Pro は 1 リクエスト最大約 184 秒の音源を返すため、コレクション尺から
# 必要呼び出し回数を割り出す基準として使う。short 化や引き伸ばしのトリミングは行わない。
_LYRIA_SEGMENT_SEC = 184

# セグメント数 (= Lyria API リクエスト数 = Vertex AI 課金回数) の hard cap。
# `target_duration_min` の桁ミスで数百リクエスト規模の課金が走るのを防ぐ。
_MAX_SEGMENT_COUNT = 60

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


@dataclass(frozen=True)
class _LyriaPromptInput:
    prompt: str
    name: str
    model: str | None
    target_duration: float | None
    padding_min: float | None
    bpm: int | None
    intensity: str | None
    mode: str | None
    reference_image: str | None
    lyrics: str | None


def _parse_lyria_prompt_entry(entry: object, index: int) -> _LyriaPromptInput:
    if not isinstance(entry, Mapping):
        raise ValidationError(f"Lyria prompt document entries[{index}] は object である必要があります")
    options = entry.get("options")
    if not isinstance(options, Mapping):
        raise ValidationError(f"Lyria prompt document entries[{index}].options は object である必要があります")

    def optional(key: str, expected: type):
        value = options.get(key)
        if value is not None and not isinstance(value, expected):
            raise ValidationError(f"Lyria prompt document entries[{index}].options.{key} の型が不正です")
        return value

    prompt = entry.get("style")
    name = entry.get("name")
    lyrics = entry.get("lyrics")
    if not isinstance(prompt, str) or not isinstance(name, str) or not isinstance(lyrics, str):
        raise ValidationError(f"Lyria prompt document entries[{index}] の name / style / lyrics が不正です")
    return _LyriaPromptInput(
        prompt=prompt,
        name=name,
        model=optional("model", str),
        target_duration=optional("target_duration_min", int | float),
        padding_min=optional("duration_padding_min", int | float),
        bpm=optional("bpm", int),
        intensity=optional("intensity", str),
        mode=optional("mode", str),
        reference_image=optional("reference_image", str),
        lyrics=lyrics or None,
    )


def _load_lyria_prompt_inputs(path: Path) -> tuple[_LyriaPromptInput, ...]:
    """検証済み Lyria JSON+HTML pair の entry を文書順で API 引数へ投影する。"""
    document = read_published_json_document(path, RepositorySchema.MUSIC_PROMPT)
    if not isinstance(document, Mapping) or document.get("engine") != "lyria":
        raise ValidationError("Lyria prompt document の engine は lyria である必要があります")
    entries = document.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValidationError("Lyria prompt document は entry を1件以上必要とします")
    return tuple(_parse_lyria_prompt_entry(entry, index) for index, entry in enumerate(entries, start=1))


def _resolve_segment_count(target_min: float, padding_min: float) -> int:
    """target + 余裕分から必要セグメント数 N を算出する。

    `(target_min + padding_min) * 60 / 184` を切り上げ。
    `target_min > 0` を validate するため戻り値は必ず 1 以上になる。
    `_MAX_SEGMENT_COUNT` を超える場合は上限に clamp して warning を出す。
    """
    if target_min <= 0:
        raise ValidationError(f"--target-duration は 1 以上を指定してください (got {target_min})")
    if padding_min < 0:
        raise ValidationError(f"--padding-min は 0 以上を指定してください (got {padding_min})")
    total_sec = (target_min + padding_min) * 60
    count = math.ceil(total_sec / _LYRIA_SEGMENT_SEC)
    if count > _MAX_SEGMENT_COUNT:
        print(
            f"WARNING: 算出セグメント数 {count} が上限 {_MAX_SEGMENT_COUNT} を超えたため "
            f"{_MAX_SEGMENT_COUNT} に切り詰めます "
            f"(target {target_min:g}min + padding {padding_min:g}min)。"
            "--target-duration の指定を確認してください",
            file=sys.stderr,
        )
        return _MAX_SEGMENT_COUNT
    return count


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

        # WAV 保存 (ffmpeg) 中の Ctrl+C でも支払い済み bytes を失わない（#481）。
        try:
            _save_audio_as_wav(audio_bytes, seg_path)
        except KeyboardInterrupt:
            recovered = lyria_client.persist_recovered_audio(audio_bytes)
            print(f"\n  [Recovered] {label} の支払い済みオーディオを退避しました → {recovered}")
            raise
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
        cost_tracker.log_generation(
            "audio",
            model=model,
            quantity=1,
            unit=unit_for_audio(model),
            metadata=metadata,
        )
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
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--prompt", help="legacy: Lyria 3 に渡すプロンプト本文")
    source.add_argument("--prompt-document", type=Path, help="検証済み lyria-prompt.json")
    parser.add_argument(
        "--name",
        required=False,
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
        "--loop",
        type=int,
        help="生成したセグメント列をマスター結合時に繰り返す回数 (1 以上、省略時は 1)",
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
    parser = _build_arg_parser()
    args = parser.parse_args()

    try:
        if args.loop is not None and args.loop < 1:
            raise ValidationError("--loop は 1 以上を指定してください")

        collection_dir = resolve_collection_dir(args.collection)
        paths = CollectionPaths(collection_dir)
        music_dir = paths.music_dir
        music_dir.mkdir(parents=True, exist_ok=True)

        if args.prompt_document is not None:
            document_path = args.prompt_document
            if not document_path.is_absolute():
                document_path = collection_dir / document_path
            prompt_inputs = _load_lyria_prompt_inputs(document_path)
        else:
            if not args.prompt or not args.name:
                raise ValidationError("legacy --prompt では --name も指定してください")
            prompt_inputs = (
                _LyriaPromptInput(
                    prompt=args.prompt,
                    name=args.name,
                    model=args.model,
                    target_duration=args.target_duration,
                    padding_min=args.padding_min,
                    bpm=args.bpm,
                    intensity=args.intensity,
                    mode=args.mode,
                    reference_image=args.reference_image,
                    lyrics=args.lyrics,
                ),
            )

        lyria_cfg = load_skill_config(_SKILL_LYRIA)
        masterup_cfg = load_skill_config(_SKILL_MASTERUP).get("audio", {})

        crossfade, bitrate = _resolve_masterup_audio(masterup_cfg)
        resolved_patterns = []
        for prompt_input in prompt_inputs:
            target_min = _resolve_target_duration(prompt_input.target_duration)
            padding_min = _resolve_padding_min(prompt_input.padding_min, lyria_cfg)
            resolved_patterns.append(
                (
                    prompt_input,
                    target_min,
                    padding_min,
                    _resolve_segment_count(target_min, padding_min),
                    _resolve_model(prompt_input.model, lyria_cfg),
                    _resolve_reference_image(prompt_input.reference_image, collection_dir),
                )
            )
        total_segments = sum(pattern[3] for pattern in resolved_patterns)
        if total_segments > _MAX_SEGMENT_COUNT:
            raise ValidationError(
                f"prompt document 全体のセグメント数 {total_segments} が上限 {_MAX_SEGMENT_COUNT} を超えています"
            )

        generated_order: list[str] = []
        global_index = 0
        for pattern_index, (prompt_input, target_min, padding_min, n, model, reference_image) in enumerate(
            resolved_patterns, start=1
        ):
            print()
            print("  yt-generate-lyria-master")
            print("  ──────────────────────────────────────────")
            print(f"  Collection : {collection_dir}")
            print(f"  Pattern    : {pattern_index}/{len(resolved_patterns)} ({prompt_input.name})")
            print(
                f"  Segments   : {n}  "
                f"(target {target_min:g}min + padding {padding_min:g}min @ {_LYRIA_SEGMENT_SEC}s/seg)"
            )
            print(f"  Model      : {model}")
            print()

            for pattern_segment_index in range(1, n + 1):
                global_index += 1
                seg_path = _segment_path(music_dir, global_index, prompt_input.name)
                ok = _generate_one_segment(
                    index=pattern_segment_index,
                    seg_path=seg_path,
                    prompt=prompt_input.prompt,
                    model=model,
                    reference_image=reference_image,
                    bpm=prompt_input.bpm,
                    intensity=prompt_input.intensity,
                    mode=prompt_input.mode,
                    lyrics=prompt_input.lyrics,
                    max_retries=args.max_retries,
                )
                if not ok:
                    print()
                    print("  成功済みセグメントは保持されています。再実行で続行できます。")
                    return 1
                generated_order.append(seg_path.name)

        print()
        print(f"  === セグメント生成完了 ({total_segments} segments) → クロスフェード結合 ===")
        replace_track_order(paths.audio_adjustments_path, generated_order, None, [])
        # 保存した order を結合にも明示的に渡す。省略するとファイル名のアルファベット順に
        # フォールバックし、music_dir に残った無関係な音声まで master に混入しうる。
        master_path = generate_master.generate_master(
            collection_dir,
            crossfade,
            bitrate,
            loops=args.loop,
            no_loop=args.loop is None,
            order=generated_order,
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
