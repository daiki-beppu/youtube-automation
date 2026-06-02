#!/usr/bin/env python3
"""raw master (`01-master/master.mp3`) に `branding/rain_layers/*.wav` を
amix で重ねた後処理音源（`master-rain.wav` 既定）を生成する CLI。

issue #510: `post_processing.rain_layers` skill-config namespace 駆動の
opt-in 雨レイヤー後処理。`yt-finalize-master`（loudnorm 二段で master.mp3 を
in-place 上書き）とは異なり、本 CLI は

- 別ファイル（既定 `master-rain.wav` / PCM 16-bit 44.1kHz stereo）に出力
- 各レイヤーを `-stream_loop -1` で master 尺までループ
- `volume={dB}` で減衰、`amix=normalize=0` で正規化抑止
- loudnorm を行わず amix のみで合成（後段ミキシングは外部 DAW 想定）
- `workflow-state.json::assets.raw_master` を新出力ファイル名に切替

を行う。`post_processing.rain_layers.enabled: false` で何もせず exit 0、
`enabled: true` だが `branding/rain_layers/*.wav` が 0 件なら fail-loud で
ConfigError を投げる。

Usage:
    yt-apply-rain-layers                       # CWD がコレクションディレクトリ
    yt-apply-rain-layers <collection-path>     # 明示指定
    yt-apply-rain-layers --dry-run             # ffmpeg コマンドのみ表示
"""

from __future__ import annotations

import argparse
import json
import shlex
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

# 雨レイヤー設定 (skill-config post_processing.rain_layers namespace で上書き可)。
_DEFAULT_VOLUME_DB = -19.0
_DEFAULT_OUTPUT_NAME = "master-rain.wav"
_DEFAULT_OUTPUT_CODEC = "pcm_s16le"
_DEFAULT_OUTPUT_SAMPLE_RATE = 44100

# ディレクトリ・ファイル名の契約定数。
_BRANDING_DIRNAME = "branding"
_RAIN_LAYERS_DIRNAME = "rain_layers"
_RAIN_GLOB = "*.wav"  # finalize_master と異なり prefix 制約を持たない。
_MASTER_FILENAME = "master.mp3"

# skill-config のスキル名 (既存 masterup namespace を共有)。
_SKILL_NAME = "masterup"


def find_rain_layers(channel: Path) -> list[Path]:
    """`<channel>/branding/rain_layers/*.wav` を決定論的にソートして返す。

    `yt-finalize-master` 側は `rain_*.wav` glob だが、本 CLI は issue #510 で
    要求された「`branding/rain_layers/*.wav`」（prefix 制約なし）を採用する。
    """
    rain_dir = channel / _BRANDING_DIRNAME / _RAIN_LAYERS_DIRNAME
    if not rain_dir.is_dir():
        return []
    return sorted(rain_dir.glob(_RAIN_GLOB))


def _resolve_post_processing_config(skill_cfg: dict[str, Any]) -> dict[str, Any]:
    """skill-config `post_processing.rain_layers` namespace を defaults と
    マージして返す。

    `post_processing` キー自体が無い場合は `{"enabled": False}` を返し、
    上位の opt-in 判定で何もせず exit 0 する。
    """
    post = skill_cfg.get("post_processing") or {}
    if not isinstance(post, dict):
        raise ConfigError(f"skill-config の post_processing は mapping である必要があります: {post!r}")
    rain = post.get("rain_layers")
    if rain is None:
        return {"enabled": False}
    if not isinstance(rain, dict):
        raise ConfigError(f"skill-config の post_processing.rain_layers は mapping である必要があります: {rain!r}")

    return {
        "enabled": bool(rain.get("enabled", False)),
        "volume_db": float(rain.get("volume_db", _DEFAULT_VOLUME_DB)),
        "output_name": str(rain.get("output_name", _DEFAULT_OUTPUT_NAME)),
        "output_codec": str(rain.get("output_codec", _DEFAULT_OUTPUT_CODEC)),
        "output_sample_rate": int(rain.get("output_sample_rate", _DEFAULT_OUTPUT_SAMPLE_RATE)),
        # `layers` キーは将来の per-layer 個別音量上書き等の余地として
        # シェイプだけ受け取って素通しする（v1 では未使用）。
        "layers": rain.get("layers"),
    }


def build_filter(n_rain: int, volume_db: float) -> str:
    """ffmpeg filter_complex 文字列を生成する純粋関数。

    入力レイアウト: `[0]=master`, `[1..N]=rain_*.wav`。
    各 rain は `-stream_loop -1` でファイル側にループ指定し、フィルタ側では
    `volume={dB}` のみ適用 → master と amix=normalize=0 で合成する。

    `aloop` を使わず ffmpeg 入力フラグ `-stream_loop -1` に寄せることで
    フィルタチェーンを単純化し、PCM WAV 出力との相性も良くする。
    """
    if n_rain <= 0:
        raise ValidationError("rain layer が 0 件のため filter を生成できません")

    parts: list[str] = []
    labels: list[str] = ["[0:a]"]
    for i in range(n_rain):
        idx = i + 1  # 0=master, 1..N=rains
        label = f"[r{i}]"
        labels.append(label)
        parts.append(f"[{idx}:a]volume={volume_db:g}dB{label}")

    inputs = "".join(labels)
    parts.append(f"{inputs}amix=inputs={n_rain + 1}:duration=first:normalize=0[aout]")
    return ";".join(parts)


def build_ffmpeg_command(
    master: Path,
    rains: list[Path],
    filter_expr: str,
    output: Path,
    *,
    output_codec: str,
    output_sample_rate: int,
) -> list[str]:
    """ffmpeg コマンドを組み立てる純粋関数。

    各 rain 入力の直前に `-stream_loop -1` を置くことで、master 尺
    (`amix=duration=first`) まで rain がループ再生される。出力は PCM WAV
    で stereo / sample_rate=`output_sample_rate` 固定。
    """
    cmd: list[str] = ["ffmpeg", "-y", "-i", str(master)]
    for rain in rains:
        cmd.extend(["-stream_loop", "-1", "-i", str(rain)])
    cmd.extend(
        [
            "-filter_complex",
            filter_expr,
            "-map",
            "[aout]",
            "-c:a",
            output_codec,
            "-ar",
            str(output_sample_rate),
            "-ac",
            "2",
            str(output),
        ]
    )
    return cmd


def _update_workflow_state_raw_master(workflow_state_path: Path, new_name: str) -> bool:
    """workflow-state.json の `assets.raw_master` を `new_name` に書き換える。

    Returns:
        True: 書き換えた / False: workflow-state.json が無い等で何もしなかった
    """
    if not workflow_state_path.is_file():
        return False

    try:
        state = json.loads(workflow_state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValidationError(f"workflow-state.json のパースに失敗: {e}") from e

    if not isinstance(state, dict):
        raise ValidationError("workflow-state.json の root は object である必要があります")

    assets = state.setdefault("assets", {})
    if not isinstance(assets, dict):
        raise ValidationError("workflow-state.json::assets は object である必要があります")

    assets["raw_master"] = new_name
    workflow_state_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return True


def apply_rain_layers(
    collection_dir: Path,
    channel: Path,
    *,
    dry_run: bool = False,
    quiet: bool = False,
) -> int:
    """raw master に rain layer を amix で被せて別ファイル出力する。

    挙動:
    - `post_processing.rain_layers.enabled: false` (または未設定) → 何もせず 0
    - `enabled: true` だが rain wav 0 件 → fail-loud (rc=1)
    - dry_run=True → ffmpeg コマンドを stdout に出して 0
    - 通常実行 → ffmpeg 実行 + workflow-state.json::assets.raw_master 切替
    """
    cfg = load_skill_config(_SKILL_NAME)
    rain_cfg = _resolve_post_processing_config(cfg)

    if not rain_cfg["enabled"]:
        if not quiet:
            print("post_processing.rain_layers.enabled=false のため何もしません")
        return 0

    rains = find_rain_layers(channel)
    if not rains:
        print(
            "ERROR: post_processing.rain_layers.enabled=true ですが "
            f"{channel / _BRANDING_DIRNAME / _RAIN_LAYERS_DIRNAME}/*.wav が 0 件です。"
            " レイヤー WAV を配置するか enabled: false にしてください。",
            file=sys.stderr,
        )
        return 1

    paths = CollectionPaths(collection_dir)
    master = paths.master_dir / _MASTER_FILENAME
    if not master.is_file():
        print(f"ERROR: マスター音源が見つかりません: {master}", file=sys.stderr)
        return 1

    output = paths.master_dir / rain_cfg["output_name"]
    filter_expr = build_filter(len(rains), rain_cfg["volume_db"])
    cmd = build_ffmpeg_command(
        master,
        rains,
        filter_expr,
        output,
        output_codec=rain_cfg["output_codec"],
        output_sample_rate=rain_cfg["output_sample_rate"],
    )

    if dry_run:
        print(" ".join(shlex.quote(arg) for arg in cmd))
        return 0

    if shutil.which("ffmpeg") is None:
        print("ERROR: ffmpeg が見つかりません (brew install ffmpeg など)", file=sys.stderr)
        return 1

    if not quiet:
        print(f"  Applying {len(rains)} rain layer(s) onto {master.name} -> {output.name}...")

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        print(
            f"ERROR: ffmpeg apply_rain_layers failed (rc={proc.returncode})",
            file=sys.stderr,
        )
        if proc.stderr:
            print(proc.stderr, file=sys.stderr)
        return 1

    # 出力が実在することを確認してから state を更新（fail-fast）。
    if not output.is_file():
        print(
            f"ERROR: ffmpeg は成功扱いだが出力ファイルが生成されていません: {output}",
            file=sys.stderr,
        )
        return 1

    _update_workflow_state_raw_master(paths.workflow_state_path, rain_cfg["output_name"])

    if not quiet:
        print(f"  Rain layer applied: {output.name} (assets.raw_master を更新)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="branding/rain_layers/*.wav を raw master に amix で重ねた後処理音源を生成する",
    )
    parser.add_argument(
        "collection",
        nargs="?",
        help="コレクションディレクトリ (省略時は CWD)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="ffmpeg コマンドのみ表示して終了 (ffmpeg は実行しない)",
    )
    parser.add_argument("--quiet", action="store_true", help="進捗表示を抑制")
    args = parser.parse_args()

    try:
        collection_dir = resolve_collection_dir(args.collection)
        channel = channel_dir()
        return apply_rain_layers(
            collection_dir,
            channel,
            dry_run=args.dry_run,
            quiet=args.quiet,
        )
    except (ValidationError, ConfigError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
