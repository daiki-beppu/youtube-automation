#!/usr/bin/env python3
"""マスター音源 (`01-master/master.mp3`) に `branding/rain_layers/rain_*.wav` を
N-layer 重ねて整音する pass-through CLI。

`branding/rain_layers/` ディレクトリ不在 / `rain_*.wav` 0 件のチャンネルでは
何もせず exit 0 (pass-through)。雨音導入チャンネルでは aloop で各 rain を
master 全長までループ展開し、loudnorm two-pass で整音した上で
`master.tmp.mp3` 経由 atomic rename で in-place 上書きする。

Usage:
    yt-finalize-master                       # CWD がコレクションディレクトリ
    yt-finalize-master <collection-path>     # 明示指定
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from youtube_automation.utils.collection_paths import (
    CollectionPaths,
    resolve_collection_dir,
)
from youtube_automation.utils.config import channel_dir
from youtube_automation.utils.exceptions import ConfigError, ValidationError
from youtube_automation.utils.skill_config import load_skill_config

# 雨音レイヤー設定の組み込みデフォルト (skill-config rain_layer namespace で上書き可)。
_DEFAULT_VOLUME_DB = -19.0
_DEFAULT_FADEIN_S = 0.5
_DEFAULT_LOUDNORM = {"I": -14.0, "LRA": 11.0, "TP": -1.5}

# audio.bitrate は既存 masterup config を流用する。skill-config 未設定時の
# フォールバック値 (config.default.yaml の audio.bitrate と一致)。
_DEFAULT_BITRATE = "192k"

# ディレクトリ・ファイル名の契約定数 (1 箇所定義、複数箇所で再利用)。
_BRANDING_DIRNAME = "branding"
_RAIN_LAYERS_DIRNAME = "rain_layers"
_RAIN_GLOB = "rain_*.wav"
_MASTER_FILENAME = "master.mp3"
_MASTER_TMP_FILENAME = "master.tmp.mp3"

# skill-config のスキル名。既存 yt-generate-master と同じ namespace を共有する。
_SKILL_NAME = "masterup"


def find_rain_layers(channel: Path) -> list[Path]:
    """`<channel>/branding/rain_layers/rain_*.wav` を決定論的にソートして返す。

    pass-through gate の前提条件: ディレクトリ不在または該当ファイル 0 件で
    空リストを返し、呼び出し側はそのケースで何もせず exit 0 する。
    """
    rain_dir = channel / _BRANDING_DIRNAME / _RAIN_LAYERS_DIRNAME
    if not rain_dir.is_dir():
        return []
    return sorted(rain_dir.glob(_RAIN_GLOB))


def build_filter(
    n_rain: int,
    volume_db: float,
    fadein_s: float,
    loudnorm: dict[str, float],
    measured: dict[str, str] | None = None,
) -> str:
    """ffmpeg filter_complex 文字列を生成する純粋関数。

    入力レイアウト: `[0]=master`, `[1..N]=rain_*.wav`。各 rain を aloop で
    全長化 → volume / afade → (N>=2 のとき amix で中間合成) → master と
    `amix=duration=first:normalize=0` → loudnorm の順。

    measured=None で pass1 (`print_format=json`)、measured 指定で pass2
    (`measured_*` + `linear=true` + `print_format=summary`) を生成する。
    """
    parts: list[str] = []
    rain_labels: list[str] = []
    for i in range(n_rain):
        idx = i + 1  # ffmpeg 入力インデックス (0=master, 1..N=rains)
        label = f"[r{i}]"
        rain_labels.append(label)
        parts.append(
            f"[{idx}:a]aloop=loop=-1:size=2147483647,volume={volume_db:g}dB,afade=t=in:st=0:d={fadein_s:g}{label}"
        )

    if n_rain == 1:
        rain_input = rain_labels[0]
    else:
        intermediate = "".join(rain_labels)
        parts.append(f"{intermediate}amix=inputs={n_rain}:normalize=0[rainmix]")
        rain_input = "[rainmix]"

    parts.append(f"[0:a]{rain_input}amix=inputs=2:duration=first:normalize=0[mixed]")

    target_i = loudnorm["I"]
    target_lra = loudnorm["LRA"]
    target_tp = loudnorm["TP"]
    if measured is None:
        parts.append(f"[mixed]loudnorm=I={target_i:g}:LRA={target_lra:g}:TP={target_tp:g}:print_format=json[aout]")
    else:
        parts.append(
            f"[mixed]loudnorm=I={target_i:g}:LRA={target_lra:g}:TP={target_tp:g}"
            f":measured_I={measured['input_i']}"
            f":measured_LRA={measured['input_lra']}"
            f":measured_TP={measured['input_tp']}"
            f":measured_thresh={measured['input_thresh']}"
            f":offset={measured['target_offset']}"
            f":linear=true:print_format=summary[aout]"
        )

    return ";".join(parts)


def _parse_loudnorm_json(stderr: str) -> dict[str, str]:
    """ffmpeg pass1 stderr 末尾の loudnorm JSON ブロックを抽出する。

    ffmpeg バージョン差異で前置きフォーマットが揺れても末尾 JSON だけ
    確実に拾えるよう、`rfind('{')` / `rfind('}')` でブロック境界を特定する。
    """
    end = stderr.rfind("}")
    if end == -1:
        raise ValidationError("ffmpeg pass1 stderr に loudnorm JSON ブロックが見つかりません")
    start = stderr.rfind("{", 0, end)
    if start == -1:
        raise ValidationError("ffmpeg pass1 stderr に loudnorm JSON の開始括弧が見つかりません")
    block = stderr[start : end + 1]
    try:
        data = json.loads(block)
    except json.JSONDecodeError as e:
        raise ValidationError(f"loudnorm JSON のパースに失敗: {e}") from e
    if not isinstance(data, dict):
        raise ValidationError("loudnorm JSON が dict ではありません")
    # build_filter (pass2) は文字列のまま filter 式に埋め込むため文字列化する。
    return {key: str(value) for key, value in data.items()}


def _build_ffmpeg_inputs(master: Path, rains: list[Path]) -> list[str]:
    """`-i master -i rain1 -i rain2 ...` の入力部分を組み立てる。"""
    cmd: list[str] = ["-i", str(master)]
    for rain in rains:
        cmd.extend(["-i", str(rain)])
    return cmd


def _build_pass1_cmd(master: Path, rains: list[Path], filter_expr: str) -> list[str]:
    """loudnorm 第1パス (measure) の ffmpeg コマンドを組み立てる。

    `-f null -` で出力を捨て、stderr に print_format=json で計測値を吐かせる。
    """
    cmd = ["ffmpeg", "-y"]
    cmd.extend(_build_ffmpeg_inputs(master, rains))
    cmd.extend(
        [
            "-filter_complex",
            filter_expr,
            "-map",
            "[aout]",
            "-f",
            "null",
            "-",
        ]
    )
    return cmd


def _build_pass2_cmd(
    master: Path,
    rains: list[Path],
    filter_expr: str,
    output: Path,
    bitrate: str,
) -> list[str]:
    """loudnorm 第2パス (apply + encode) の ffmpeg コマンドを組み立てる。"""
    cmd = ["ffmpeg", "-y"]
    cmd.extend(_build_ffmpeg_inputs(master, rains))
    cmd.extend(
        [
            "-filter_complex",
            filter_expr,
            "-map",
            "[aout]",
            "-c:a",
            "libmp3lame",
            "-b:a",
            bitrate,
            str(output),
        ]
    )
    return cmd


def _resolve_rain_config(
    skill_cfg: dict[str, Any],
) -> tuple[float, float, dict[str, float]]:
    """skill-config `rain_layer` namespace を組み込み defaults とマージする。"""
    rain_cfg = skill_cfg.get("rain_layer") or {}
    volume_db = float(rain_cfg.get("volume_db", _DEFAULT_VOLUME_DB))
    fadein_s = float(rain_cfg.get("fadein_s", _DEFAULT_FADEIN_S))

    loudnorm_override = rain_cfg.get("loudnorm") or {}
    loudnorm = dict(_DEFAULT_LOUDNORM)
    for key in ("I", "LRA", "TP"):
        if key in loudnorm_override:
            loudnorm[key] = float(loudnorm_override[key])

    return volume_db, fadein_s, loudnorm


def finalize_master(
    collection_dir: Path,
    channel: Path,
    *,
    quiet: bool = False,
) -> int:
    """`01-master/master.mp3` に rain layer を被せて in-place 上書きする。

    pass-through gate: `branding/rain_layers/rain_*.wav` が空なら skill-config も
    ffmpeg も触らず即 0 を返す (config 検証は gate 通過後にのみ実行する契約)。
    """
    rains = find_rain_layers(channel)
    if not rains:
        return 0

    if shutil.which("ffmpeg") is None:
        print("ERROR: ffmpeg が見つかりません (brew install ffmpeg など)", file=sys.stderr)
        return 1

    paths = CollectionPaths(collection_dir)
    master = paths.master_dir / _MASTER_FILENAME
    if not master.is_file():
        print(f"ERROR: マスター音源が見つかりません: {master}", file=sys.stderr)
        return 1

    cfg = load_skill_config(_SKILL_NAME)
    volume_db, fadein_s, loudnorm = _resolve_rain_config(cfg)
    bitrate = str(cfg.get("audio", {}).get("bitrate", _DEFAULT_BITRATE))

    tmp = master.with_name(_MASTER_TMP_FILENAME)
    try:
        if not quiet:
            print(f"  Layering {len(rains)} rain layer(s) onto {master.name}...")

        # pass1: loudnorm measure (stderr に print_format=json で計測値が出る)
        pass1_filter = build_filter(len(rains), volume_db, fadein_s, loudnorm, measured=None)
        pass1_cmd = _build_pass1_cmd(master, rains, pass1_filter)
        pass1 = subprocess.run(pass1_cmd, capture_output=True, text=True, check=False)
        if pass1.returncode != 0:
            print(
                f"ERROR: ffmpeg pass1 (loudnorm measure) failed (rc={pass1.returncode})",
                file=sys.stderr,
            )
            if pass1.stderr:
                print(pass1.stderr, file=sys.stderr)
            return 1

        measured = _parse_loudnorm_json(pass1.stderr)

        # pass2: measured を fold-in して apply + encode (master.tmp.mp3 へ書く)
        pass2_filter = build_filter(len(rains), volume_db, fadein_s, loudnorm, measured=measured)
        pass2_cmd = _build_pass2_cmd(master, rains, pass2_filter, tmp, bitrate)
        pass2 = subprocess.run(pass2_cmd, capture_output=True, text=True, check=False)
        if pass2.returncode != 0:
            print(
                f"ERROR: ffmpeg pass2 (apply) failed (rc={pass2.returncode})",
                file=sys.stderr,
            )
            if pass2.stderr:
                print(pass2.stderr, file=sys.stderr)
            return 1

        # pass2 成功時のみ atomic rename で master を上書き (失敗時は元 master を保護)
        os.replace(tmp, master)

        if not quiet:
            print(f"  ✓ Rain layer applied: {master.name}")
        return 0
    except ValidationError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    finally:
        # pass1/pass2 の中断・例外・失敗いずれの経路でも tmp 残骸を必ず掃除する。
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                # tmp 削除失敗は master 保護の本体には影響しないため握りつぶす
                # (主目的の master.mp3 はこの時点で無傷)。
                pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="branding/rain_layers/ の雨音をマスター音源にレイヤーする",
    )
    parser.add_argument(
        "collection",
        nargs="?",
        help="コレクションディレクトリ (省略時は CWD)",
    )
    parser.add_argument("--quiet", action="store_true", help="進捗表示を抑制")
    args = parser.parse_args()

    try:
        collection_dir = resolve_collection_dir(args.collection)
        channel = channel_dir()
        return finalize_master(collection_dir, channel, quiet=args.quiet)
    except (ValidationError, ConfigError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
