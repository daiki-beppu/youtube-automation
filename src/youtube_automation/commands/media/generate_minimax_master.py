"""MiniMax Music segments を生成し、既存 master builder で長尺音源へ結合する CLI。"""

from __future__ import annotations

import argparse
import hashlib
import math
import os
import sys
import time
from collections.abc import Mapping
from pathlib import Path

from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.commands.media import generate_master
from youtube_automation.configuration import channel_dir, load_config
from youtube_automation.configuration.skills import load_skill_config
from youtube_automation.core.errors import ConfigError, GeneratorError, ValidationError
from youtube_automation.infrastructure import cost_tracker
from youtube_automation.infrastructure.media import minimax_client
from youtube_automation.infrastructure.media.collection_paths import CollectionPaths, resolve_collection_dir

_MUSIC_PATH = "/v1/music_generation"
_MINIMAX_SEGMENT_SEC = 300
_MAX_SEGMENT_COUNT = 60
_DEFAULT_MAX_RETRIES = 3
_RECOVERY_SUBDIR = ("tmp", "minimax-recovered")
_AUDIO_SETTING = {"sample_rate": 44100, "bitrate": 256000, "format": "mp3"}


def _mapping(value: object, label: str) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise GeneratorError(f"MiniMax response の {label} は object である必要があります")
    return value


def _config_mapping(value: object, label: str) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise ConfigError(f"{label} は object である必要があります")
    return value


def _extract_audio(body: Mapping[str, object]) -> bytes:
    """公式 response の完了済み hex audio を bytes へ変換する。"""
    base_resp = _mapping(body.get("base_resp"), "base_resp")
    status_code = base_resp.get("status_code")
    if isinstance(status_code, bool) or not isinstance(status_code, int) or status_code != 0:
        safe_code = status_code if isinstance(status_code, int) and not isinstance(status_code, bool) else "invalid"
        raise GeneratorError(f"MiniMax music generation が失敗しました (status_code={safe_code})")

    data = _mapping(body.get("data"), "data")
    if data.get("status") != 2:
        raise GeneratorError("MiniMax music generation response が完了状態ではありません")
    encoded = data.get("audio")
    if not isinstance(encoded, str) or not encoded:
        raise GeneratorError("MiniMax music generation response に audio がありません")
    try:
        audio = bytes.fromhex(encoded)
    except ValueError:
        raise GeneratorError("MiniMax music generation response の audio hex が不正です") from None
    if not audio:
        raise GeneratorError("MiniMax music generation response の audio が空です")
    return audio


def _resolve_segment_count(target_min: float, padding_min: float) -> int:
    if target_min <= 0:
        raise ValidationError(f"--target-duration は 0 より大きい値が必要です (got {target_min})")
    if padding_min < 0:
        raise ValidationError(f"--padding-min は 0 以上が必要です (got {padding_min})")
    count = math.ceil((target_min + padding_min) * 60 / _MINIMAX_SEGMENT_SEC)
    if count > _MAX_SEGMENT_COUNT:
        print(
            f"WARNING: 算出セグメント数 {count} が上限 {_MAX_SEGMENT_COUNT} を超えたため "
            f"{_MAX_SEGMENT_COUNT} に切り詰めます。--target-duration を確認してください",
            file=sys.stderr,
        )
        return _MAX_SEGMENT_COUNT
    return count


def _write_audio_file(audio: bytes, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        temporary.write_bytes(audio)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def recovery_path(audio: bytes) -> Path:
    digest = hashlib.sha256(audio).hexdigest()
    return Path(channel_dir()).joinpath(*_RECOVERY_SUBDIR) / f"{digest}.mp3"


def persist_recovered_audio(audio: bytes) -> Path:
    path = recovery_path(audio)
    _write_audio_file(audio, path)
    return path


def _persist_segment(audio: bytes, segment_path: Path) -> None:
    try:
        _write_audio_file(audio, segment_path)
    except KeyboardInterrupt:
        recovered = persist_recovered_audio(audio)
        print(f"\n  [Recovered] 支払い済み MiniMax audio を退避しました → {recovered}")
        raise
    except OSError as error:
        try:
            recovered = persist_recovered_audio(audio)
        except OSError:
            raise GeneratorError(f"MiniMax segment の保存と recovery に失敗しました: {segment_path}") from error
        raise GeneratorError(
            f"MiniMax segment の保存に失敗しました。支払い済み audio は {recovered} へ退避しました"
        ) from error


def _payload(prompt: str, model: str) -> dict[str, object]:
    return {
        "model": model,
        "prompt": prompt,
        "is_instrumental": True,
        "output_format": "hex",
        "audio_setting": dict(_AUDIO_SETTING),
    }


def _generate_segment(
    *,
    index: int,
    segment_path: Path,
    prompt: str,
    model: str,
    timeout: float,
    max_retries: int,
) -> None:
    label = f"seg_{index:02d}"
    if segment_path.is_file() and segment_path.stat().st_size > 0:
        print(f"  [skip] {label} — 既に存在 ({segment_path.name})")
        return
    if max_retries < 0:
        raise ValidationError("--max-retries は 0 以上が必要です")

    for attempt in range(max_retries + 1):
        if attempt > 0:
            wait_seconds = min(30, attempt * 10)
            print(f"  [{label}] retry {attempt}/{max_retries} ({wait_seconds}s 待機)")
            time.sleep(wait_seconds)
        try:
            body = minimax_client.request_json(_MUSIC_PATH, _payload(prompt, model), timeout=timeout)
            audio = _extract_audio(body)
        except GeneratorError:
            if attempt == max_retries:
                raise GeneratorError(f"MiniMax {label} は {max_retries + 1} 回失敗しました") from None
            continue

        _persist_segment(audio, segment_path)
        cost_tracker.log_generation(
            "audio",
            model=model,
            quantity=1,
            unit="song",
            metadata={
                "segment": label,
                "output_file": cost_tracker.relative_to_channel_dir(segment_path),
            },
        )
        print(f"  [{label}] 完了 ({segment_path.stat().st_size / 1024:.0f} KB)")
        return


def _number(config: Mapping[object, object], key: str, label: str) -> float:
    value = config.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{label}.{key} は数値である必要があります")
    return float(value)


def _string(config: Mapping[object, object], key: str, label: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{label}.{key} は空でない文字列である必要があります")
    return value


def _minimax_config() -> Mapping[object, object]:
    generate = load_skill_config("music.generate")
    return _config_mapping(generate.get("minimax"), "music.generate.minimax")


def _master_audio_config() -> Mapping[object, object]:
    master = load_skill_config("masterup")
    return _config_mapping(master.get("audio"), "masterup.audio")


def _resolve_target_duration(argument: float | None) -> float:
    if argument is not None:
        return argument
    configured = load_config().audio.target_duration_min
    if configured is None:
        raise ValidationError(
            "目標尺が決まりません。--target-duration または config/channel/audio.json を設定してください"
        )
    return float(configured)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-generate-minimax-master",
        description="MiniMax Music segments を生成し、長尺 master.mp3 へ結合する。",
    )
    parser.add_argument("--prompt", required=True, help="MiniMax Music に渡す instrumental style prompt")
    parser.add_argument("--name", required=True, help="segment filename slug")
    parser.add_argument("--collection", help="collection directory（省略時は CWD から解決）")
    parser.add_argument("--target-duration", type=float, help="目標尺（分。省略時は channel audio config）")
    parser.add_argument("--model", help="MiniMax Music model（省略時は music.generate.minimax.model）")
    parser.add_argument("--padding-min", type=float, help="segment数算出時に追加する余裕（分）")
    parser.add_argument(
        "--max-retries",
        type=int,
        default=_DEFAULT_MAX_RETRIES,
        help=f"segmentごとの再試行回数（default: {_DEFAULT_MAX_RETRIES}）",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    collection = resolve_collection_dir(args.collection)
    paths = CollectionPaths(collection)
    paths.music_dir.mkdir(parents=True, exist_ok=True)

    minimax_config = _minimax_config()
    master_config = _master_audio_config()
    target_duration = _resolve_target_duration(args.target_duration)
    padding_min = (
        args.padding_min
        if args.padding_min is not None
        else _number(minimax_config, "duration_padding_min", "music.generate.minimax")
    )
    model = args.model or _string(minimax_config, "model", "music.generate.minimax")
    timeout = _number(minimax_config, "request_timeout_sec", "music.generate.minimax")
    if timeout <= 0:
        raise ConfigError("music.generate.minimax.request_timeout_sec は 0 より大きい値が必要です")
    segment_count = _resolve_segment_count(target_duration, padding_min)
    crossfade = _number(master_config, "crossfade_duration", "masterup.audio")
    bitrate = _string(master_config, "bitrate", "masterup.audio")

    print("\n  yt-generate-minimax-master")
    print(f"  Collection : {collection}")
    print(
        f"  Segments   : {segment_count} "
        f"(target {target_duration:g}min + padding {padding_min:g}min @ {_MINIMAX_SEGMENT_SEC}s/seg)"
    )
    print(f"  Model      : {model}\n")

    for index in range(1, segment_count + 1):
        _generate_segment(
            index=index,
            segment_path=paths.music_dir / f"{index:02d}_{args.name}.mp3",
            prompt=args.prompt,
            model=model,
            timeout=timeout,
            max_retries=args.max_retries,
        )

    master_path = generate_master.generate_master(collection, crossfade, bitrate)
    print(f"\n  Master audio: {master_path}")
    cost_tracker.print_last_report()
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_cli(build_parser, run, argv, failure_message="MiniMax master generation error")


if __name__ == "__main__":
    raise SystemExit(main())
