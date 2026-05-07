#!/usr/bin/env python3
"""設計 D の音声側施策を実行する master.mp3 ファイナライズ。

`01-master/master.mp3` (Step 5 出力の本編楽曲) + `branding/intro_sfx/{cup,paper,vinyl}.wav`
(3 SFX) + `branding/rain_layers/rain_*.wav` (N レイヤー) を ffmpeg で amix し、
loudnorm two-pass で整音した最終 `master.mp3` を atomic rename で in-place 上書きする。

intro 素材ディレクトリ (`branding/intro_sfx/` または `branding/rain_layers/`) が
存在しないチャンネルでは pass-through で rc=0 終了する (`/videoup` の自動検出と対称)。

設計 D の核:
- 楽曲は `song_delay_ms` ms 遅延 + `song_fadein_s` 秒 afade-in (intro 区間を雨 + SFX に譲る)
- 雨 N レイヤー: 各 layer `rain_volume_db` dB / `rain_fadein_s` 秒 fadein → amix
- SFX 3 種: 配置 ms / dB を `intro_audio.sfx.{cup,paper,vinyl}` から組み立て → amix
- 最終 mix: `[song][sfx][rain]amix=inputs=3:duration=first:normalize=0,loudnorm[aout]`

Usage:
    python finalize_master.py <collection-path>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from youtube_automation.utils.config import channel_dir
from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.skill_config import load_skill_config

# SFX 並びは config["sfx"] のキーから固定取得する。順序は名前 → input index に決定する
_SFX_ORDER = ("cup", "paper", "vinyl")

_REQUIRED_KEYS: tuple[str, ...] = (
    "song_delay_ms",
    "song_fadein_s",
    "song_volume_db",
    "rain_volume_db",
    "rain_fadein_s",
    "loudnorm",
    "sfx",
)

_RAIN_GLOB = "rain_*.wav"

# ファイル名定数: master.mp3 を atomic rename で上書きするため temp は同一ディレクトリに置く
_MASTER_FILENAME = "master.mp3"
_MASTER_TMP_FILENAME = "master.tmp.mp3"


def _validate_intro_audio(config: dict[str, Any]) -> None:
    """intro_audio dict (= load_skill_config('masterup')['intro_audio'] 部分)
    の必須キーを検証する。欠落で ConfigError。"""
    missing = [k for k in _REQUIRED_KEYS if k not in config]
    if missing:
        raise ConfigError(
            f"intro_audio config に必須キーが欠落: {missing} "
            "(masterup/config.default.yaml の intro_audio: namespace を確認してください)"
        )
    sfx = config["sfx"]
    if not isinstance(sfx, dict):
        raise ConfigError(f"intro_audio.sfx は dict である必要があります: {type(sfx)!r}")
    sfx_missing = [name for name in _SFX_ORDER if name not in sfx]
    if sfx_missing:
        raise ConfigError(
            f"intro_audio.sfx に必須エントリが欠落: {sfx_missing} "
            f"(必要: {list(_SFX_ORDER)})"
        )


def _format_seconds(value: float | int) -> str:
    """ffmpeg 引数用に秒値を文字列化。整数なら整数表記、小数なら小数のまま。"""
    if isinstance(value, bool):  # bool は int の subclass なので明示分岐
        raise TypeError(f"秒値に bool は使えません: {value!r}")
    f = float(value)
    if f.is_integer():
        return str(int(f))
    return f"{f:g}"


def build_common_parts(config: dict[str, Any], *, n_rain: int) -> list[str]:
    """SFX + rain + song の filter graph parts を組み立てる (loudnorm / 最終 amix
    は含まない)。input layout は [0]=master, [1..3]=SFX (cup/paper/vinyl 固定順),
    [4..N+3]=rain_*.wav。

    Returns:
        ffmpeg `-filter_complex` の各 part を区切りなしで並べたリスト
        (`;`.join() で連結する想定)。

    Raises:
        ConfigError: 必須キー欠落 / sfx エントリ欠落
    """
    _validate_intro_audio(config)
    if n_rain < 1:
        raise ConfigError(f"n_rain は 1 以上である必要があります: {n_rain}")

    sfx_cfg = config["sfx"]
    parts: list[str] = []

    # ── SFX: cup=[1:a], paper=[2:a], vinyl=[3:a] ──
    for idx, name in enumerate(_SFX_ORDER, start=1):
        entry = sfx_cfg[name]
        start_ms = int(entry["start_ms"])
        volume_db = entry["volume_db"]
        # intro 30s 全体に届かせるため apad で尾部を埋める
        parts.append(
            f"[{idx}:a]adelay={start_ms}|{start_ms},"
            f"volume={volume_db}dB,apad[{name}]"
        )

    parts.append(
        f"[{_SFX_ORDER[0]}][{_SFX_ORDER[1]}][{_SFX_ORDER[2]}]"
        f"amix=inputs=3:duration=first:normalize=0[sfx]"
    )

    # ── rain N-layer: input index 4..N+3 ──
    rain_volume = config["rain_volume_db"]
    rain_fadein = _format_seconds(config["rain_fadein_s"])
    rain_labels: list[str] = []
    for i in range(n_rain):
        in_idx = 4 + i
        label = f"r{i}"
        rain_labels.append(f"[{label}]")
        parts.append(
            f"[{in_idx}:a]volume={rain_volume}dB,"
            f"afade=t=in:st=0:d={rain_fadein},"
            f"aloop=loop=-1:size=2147483647[{label}]"
        )
    if n_rain == 1:
        parts.append("[r0]anull[rain]")
    else:
        parts.append(
            f"{''.join(rain_labels)}amix=inputs={n_rain}:"
            "duration=first:normalize=0[rain]"
        )

    # ── song: 設計 D の核 (10s 遅延 + 2s afade-in + volume) ──
    delay_ms = int(config["song_delay_ms"])
    fadein_s = _format_seconds(config["song_fadein_s"])
    fadein_start_s = _format_seconds(delay_ms / 1000.0)
    song_volume = config["song_volume_db"]
    parts.append(
        f"[0:a]adelay={delay_ms}|{delay_ms},"
        f"afade=t=in:st={fadein_start_s}:d={fadein_s},"
        f"volume={song_volume}dB[song]"
    )

    return parts


def _loudnorm_filter(loudnorm: dict[str, Any], *, measured: dict[str, str] | None) -> str:
    """loudnorm filter 文字列を組み立てる。

    Args:
        loudnorm: `{I: -14, LRA: 11, TP: -1.5}` 相当の target 値 dict
        measured: pass1 の測定値を渡すと pass2 の linear モードを使う
    """
    target_i = loudnorm["I"]
    target_lra = loudnorm["LRA"]
    target_tp = loudnorm["TP"]
    base = f"loudnorm=I={target_i}:LRA={target_lra}:TP={target_tp}"
    if measured is None:
        return f"{base}:print_format=json"
    return (
        f"{base}:"
        f"measured_I={measured['input_i']}:"
        f"measured_LRA={measured['input_lra']}:"
        f"measured_TP={measured['input_tp']}:"
        f"measured_thresh={measured['input_thresh']}:"
        f"offset={measured.get('target_offset', '0')}:"
        "linear=true:print_format=summary"
    )


def build_filter(
    config: dict[str, Any],
    *,
    n_rain: int = 1,
    measured: dict[str, str] | None = None,
) -> str:
    """完全な filter_complex 文字列 (末尾 `[aout]`) を組み立てる。

    Args:
        config: `intro_audio` namespace dict
        n_rain: rain layer 件数
        measured: pass1 の loudnorm 測定値。None=pass1 (measurement) モード
    """
    parts = list(build_common_parts(config, n_rain=n_rain))
    final = (
        f"[song][sfx][rain]amix=inputs=3:duration=first:normalize=0,"
        f"{_loudnorm_filter(config['loudnorm'], measured=measured)}[aout]"
    )
    parts.append(final)
    return ";".join(parts)


_LOUDNORM_KEYS = ("input_i", "input_tp", "input_lra", "input_thresh")


def parse_loudnorm_json(stderr: str) -> dict[str, Any]:
    """ffmpeg pass1 の stderr から loudnorm の JSON ブロックを抽出する。

    Returns:
        dict (input_i / input_tp / input_lra / input_thresh / target_offset 含む)

    Raises:
        RuntimeError: stderr に loudnorm JSON ブロックが見つからない
    """
    # `{ ... }` 形式の JSON ブロックを greedy に抽出 (loudnorm が最後に出すのが本命)
    blocks = re.findall(r"\{[^{}]*\}", stderr, flags=re.DOTALL)
    for block in reversed(blocks):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and all(k in data for k in _LOUDNORM_KEYS):
            return data
    raise RuntimeError(
        "ffmpeg stderr に loudnorm JSON ブロック (input_i/input_tp/input_lra/"
        "input_thresh を含む) が見つかりません"
    )


def _intro_mode_enabled(repo: Path) -> bool:
    """intro 素材ディレクトリの有無で intro モード適用可否を判定する。

    `branding/intro_sfx/` または `branding/rain_layers/` のどちらか一方でも
    存在しないチャンネルは intro モード非対応として扱う (pass-through トリガー)。
    `is_dir()` を使うのは file/symlink での誤検出を避けるため。
    """
    sfx_dir = repo / "branding" / "intro_sfx"
    rain_dir = repo / "branding" / "rain_layers"
    return sfx_dir.is_dir() and rain_dir.is_dir()


def finalize(collection: Path) -> int:
    """`<collection>/01-master/master.mp3` に intro 区間 SFX + rain + 楽曲を amix し、
    atomic rename で `master.mp3` を in-place 上書きする。

    intro 素材ディレクトリ (`branding/intro_sfx/` / `branding/rain_layers/`) が存在
    しないチャンネルでは pass-through で rc=0 終了する (master.mp3 不変)。

    Returns:
        exit code (0=成功 or pass-through / 1=入力検証失敗 / その他=ffmpeg 伝播)
    """
    config_full = load_skill_config("masterup", use_cache=False)
    intro_audio = config_full.get("intro_audio")
    if not isinstance(intro_audio, dict):
        raise ConfigError(
            "masterup/config.default.yaml に intro_audio: namespace が必要です"
        )
    _validate_intro_audio(intro_audio)

    repo = channel_dir()
    master = collection / "01-master" / _MASTER_FILENAME

    # 入力検証 (Fail Fast)
    if not master.exists():
        print(f"ERROR: {_MASTER_FILENAME} が見つかりません: {master}", file=sys.stderr)
        return 1

    # intro モード自動検出: ディレクトリ自体が無いチャンネルは pass-through
    if not _intro_mode_enabled(repo):
        print(
            f"INFO: intro 素材ディレクトリ (branding/intro_sfx/ または "
            f"branding/rain_layers/) が見つかりません。pass-through で終了します "
            f"({master})",
            file=sys.stderr,
        )
        return 0

    # ハーフ実装防止 (dir はあるが中身欠落 = fail-fast)
    sfx_dir = repo / "branding" / "intro_sfx"
    sfx_files: list[Path] = []
    for name in _SFX_ORDER:
        entry = intro_audio["sfx"][name]
        path = sfx_dir / entry["file"]
        if not path.exists():
            print(f"ERROR: SFX wav が見つかりません: {path}", file=sys.stderr)
            return 1
        sfx_files.append(path)

    rain_dir = repo / "branding" / "rain_layers"
    rain_files = sorted(rain_dir.glob(_RAIN_GLOB))
    if not rain_files:
        print(
            f"ERROR: rain layer (rain_*.wav) が {rain_dir} に存在しません",
            file=sys.stderr,
        )
        return 1

    n_rain = len(rain_files)
    temp_out = collection / "01-master" / _MASTER_TMP_FILENAME

    # ── pass1: loudnorm 測定 ──
    pass1_filter = build_filter(
        intro_audio,
        n_rain=n_rain,
        measured=None,
    )
    cmd1: list[str] = ["ffmpeg", "-y", "-i", str(master)]
    for s in sfx_files:
        cmd1 += ["-i", str(s)]
    for r in rain_files:
        cmd1 += ["-i", str(r)]
    cmd1 += [
        "-filter_complex", pass1_filter,
        "-map", "[aout]",
        "-f", "null", "-",
    ]
    result1 = subprocess.run(cmd1, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    if result1.returncode != 0:
        print(
            f"ERROR: ffmpeg pass1 (loudnorm 測定) が失敗 (exit {result1.returncode})",
            file=sys.stderr,
        )
        if result1.stderr:
            print(result1.stderr, file=sys.stderr)
        return result1.returncode

    measured = parse_loudnorm_json(result1.stderr or "")

    # ── pass2: linear loudnorm + temp 書き出し ──
    pass2_filter = build_filter(
        intro_audio,
        n_rain=n_rain,
        measured=measured,
    )
    cmd2: list[str] = ["ffmpeg", "-y", "-i", str(master)]
    for s in sfx_files:
        cmd2 += ["-i", str(s)]
    for r in rain_files:
        cmd2 += ["-i", str(r)]
    cmd2 += [
        "-filter_complex", pass2_filter,
        "-map", "[aout]",
        "-c:a", "libmp3lame", "-b:a", "192k",
        str(temp_out),
    ]
    result2 = subprocess.run(cmd2, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    if result2.returncode != 0:
        print(
            f"ERROR: ffmpeg pass2 (final mix) が失敗 (exit {result2.returncode})",
            file=sys.stderr,
        )
        if result2.stderr:
            print(result2.stderr, file=sys.stderr)
        # temp の best-effort 削除 (元 master.mp3 は os.replace を呼ばない限り無傷)
        try:
            os.remove(temp_out)
        except OSError:
            pass
        return result2.returncode

    # ── atomic rename: temp_out → master (同一 fs 内で os.replace) ──
    os.replace(temp_out, master)

    print(f"Success: {master}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection", type=Path, help="コレクションディレクトリ")
    args = parser.parse_args()
    return finalize(args.collection)


if __name__ == "__main__":
    sys.exit(main())
