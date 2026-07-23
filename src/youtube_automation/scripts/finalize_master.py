#!/usr/bin/env python3
"""マスター音源 (`01-master/master.mp3`) に ambient layer (例:
`branding/rain_layers/rain_*.wav`) を N-layer 重ねて整音する pass-through CLI。

ambient layer ディレクトリ不在 / 対象 wav 0 件のチャンネルでは何もせず
exit 0 (pass-through)。導入チャンネルでは aloop で各 layer を master 全長まで
ループ展開し、loudnorm two-pass で整音した上で `master.tmp.mp3` 経由
atomic rename で in-place 上書きする。

skill-config の `audio.finalize.*` namespace で、レイヤー対象ディレクトリ・
glob・per-file 上書き・loudnorm パラメータ・mix の duration / normalize・
fadein curve・出力 sample_rate / codec / bitrate を全て注入できる。
設定は `audio.finalize.*` namespace で解決する。

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

from youtube_automation.configuration import channel_dir
from youtube_automation.utils.collection_paths import (
    CollectionPaths,
    resolve_collection_dir,
)
from youtube_automation.utils.exceptions import ConfigError, ValidationError
from youtube_automation.utils.skill_config import load_skill_config

# ambient layer 設定の組み込みデフォルト
# (skill-config audio.finalize.ambient_layers namespace で上書き可)。
_DEFAULT_VOLUME_DB = -19.0
_DEFAULT_FADEIN_S = 0.5
_DEFAULT_FADEIN_CURVE = "tri"  # ffmpeg afade のデフォルトカーブ
_DEFAULT_LOUDNORM = {"I": -14.0, "LRA": 11.0, "TP": -1.5}
_DEFAULT_LOUDNORM_ENABLED = True
_DEFAULT_LOUDNORM_MODE = "linear"  # `dynamic` は未実装
_DEFAULT_MIX_DURATION = "first"  # ffmpeg amix duration (first/shortest/longest)
_DEFAULT_MIX_NORMALIZE = 0  # 0=disabled, 1=enabled (ffmpeg amix normalize)

# 出力エンコード設定 (skill-config audio.finalize.* で上書き可)。
# 既存 v5.5.0 挙動: bitrate=192k / codec=libmp3lame / sample_rate は ffmpeg 既定。
_DEFAULT_BITRATE = "192k"
_DEFAULT_CODEC = "libmp3lame"
_DEFAULT_SAMPLE_RATE: int | None = None  # None → -ar フラグを付けない (ffmpeg 既定)

# ambient layer 探索のデフォルト (既存 v5.5.0 の rain_layers ディレクトリ規約)。
_BRANDING_DIRNAME = "branding"
_DEFAULT_LAYERS_DIRNAME = "rain_layers"
_DEFAULT_LAYERS_GLOB = "rain_*.wav"

# マスターファイル名の契約定数。
_MASTER_FILENAME = "master.mp3"
_MASTER_TMP_FILENAME = "master.tmp.mp3"

# skill-config のスキル名。既存 yt-generate-master と同じ namespace を共有する。
_SKILL_NAME = "masterup"


def find_ambient_layers(
    channel: Path,
    *,
    layers_dirname: str = _DEFAULT_LAYERS_DIRNAME,
    glob_pattern: str = _DEFAULT_LAYERS_GLOB,
) -> list[Path]:
    """`<channel>/branding/<layers_dirname>/<glob_pattern>` を決定論的にソートして返す。

    pass-through gate の前提条件: ディレクトリ不在または該当ファイル 0 件で
    空リストを返し、呼び出し側はそのケースで何もせず exit 0 する。

    layers_dirname / glob_pattern を未指定で呼ぶと既存 v5.5.0 の rain_layers
    規約 (`branding/rain_layers/rain_*.wav`) と完全一致する。
    """
    layers_dir = channel / _BRANDING_DIRNAME / layers_dirname
    if not layers_dir.is_dir():
        return []
    return sorted(layers_dir.glob(glob_pattern))


def _layer_volume(
    base_volume_db: float,
    fadein_s: float,
    fadein_curve: str,
    per_file_override: dict[str, Any] | None,
) -> tuple[float, float, str]:
    """layer 単位の override をかぶせて (volume_db, fadein_s, fadein_curve) を返す。"""
    if not per_file_override:
        return base_volume_db, fadein_s, fadein_curve
    return (
        float(per_file_override.get("volume_db", base_volume_db)),
        float(per_file_override.get("fadein_s", fadein_s)),
        str(per_file_override.get("fadein_curve", fadein_curve)),
    )


def build_filter(
    n_rain: int,
    volume_db: float,
    fadein_s: float,
    loudnorm: dict[str, float],
    measured: dict[str, str] | None = None,
    *,
    fadein_curve: str = _DEFAULT_FADEIN_CURVE,
    mix_duration: str = _DEFAULT_MIX_DURATION,
    mix_normalize: int = _DEFAULT_MIX_NORMALIZE,
    layer_overrides: list[dict[str, Any] | None] | None = None,
    apply_loudnorm: bool = True,
) -> str:
    """ffmpeg filter_complex 文字列を生成する純粋関数。

    入力レイアウト: `[0]=master`, `[1..N]=ambient layer*.wav`。各 layer を
    aloop で全長化 → volume / afade → (N>=2 のとき amix で中間合成) →
    master と `amix=duration=<mix_duration>:normalize=<mix_normalize>` →
    (apply_loudnorm 時のみ) loudnorm の順。

    measured=None で pass1 (`print_format=json`)、measured 指定で pass2
    (`measured_*` + `linear=true` + `print_format=summary`) を生成する。
    apply_loudnorm=False のときは loudnorm 段を省き、mix 結果に直接 `[aout]`
    ラベルを付けて 1-pass 出力 (`loudnorm.enabled: false` 経路)。

    layer_overrides: layer ごとに `{"volume_db": ..., "fadein_s": ...,
    "fadein_curve": ...}` を上書き指定する。None 要素はデフォルト値を採用。
    長さは n_rain と一致させる契約 (呼び出し側で揃える)。
    """
    if layer_overrides is None:
        layer_overrides = [None] * n_rain
    elif len(layer_overrides) != n_rain:
        raise ValidationError(f"layer_overrides 長 ({len(layer_overrides)}) が layer 数 ({n_rain}) と一致しません")

    parts: list[str] = []
    rain_labels: list[str] = []
    for i in range(n_rain):
        idx = i + 1  # ffmpeg 入力インデックス (0=master, 1..N=layers)
        label = f"[r{i}]"
        rain_labels.append(label)
        lv_db, lv_fadein_s, lv_curve = _layer_volume(volume_db, fadein_s, fadein_curve, layer_overrides[i])
        parts.append(
            f"[{idx}:a]aloop=loop=-1:size=2147483647"
            f",volume={lv_db:g}dB"
            f",afade=t=in:st=0:d={lv_fadein_s:g}:curve={lv_curve}"
            f"{label}"
        )

    if n_rain == 1:
        rain_input = rain_labels[0]
    else:
        intermediate = "".join(rain_labels)
        parts.append(f"{intermediate}amix=inputs={n_rain}:normalize={mix_normalize}[rainmix]")
        rain_input = "[rainmix]"

    # loudnorm を skip するときは mix 段の出力ラベルを直接 [aout] にする。
    mix_out_label = "[mixed]" if apply_loudnorm else "[aout]"
    parts.append(f"[0:a]{rain_input}amix=inputs=2:duration={mix_duration}:normalize={mix_normalize}{mix_out_label}")

    if not apply_loudnorm:
        return ";".join(parts)

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
    *,
    codec: str = _DEFAULT_CODEC,
    sample_rate: int | None = _DEFAULT_SAMPLE_RATE,
) -> list[str]:
    """loudnorm 第2パス (apply + encode) の ffmpeg コマンドを組み立てる。

    sample_rate=None のとき `-ar` を付けず ffmpeg の既定 (=master の sr) に任せる。
    """
    cmd = ["ffmpeg", "-y"]
    cmd.extend(_build_ffmpeg_inputs(master, rains))
    cmd.extend(
        [
            "-filter_complex",
            filter_expr,
            "-map",
            "[aout]",
            "-c:a",
            codec,
            "-b:a",
            bitrate,
        ]
    )
    if sample_rate is not None:
        cmd.extend(["-ar", str(sample_rate)])
    cmd.append(str(output))
    return cmd


def _build_single_pass_cmd(
    master: Path,
    rains: list[Path],
    filter_expr: str,
    output: Path,
    bitrate: str,
    *,
    codec: str = _DEFAULT_CODEC,
    sample_rate: int | None = _DEFAULT_SAMPLE_RATE,
) -> list[str]:
    """loudnorm を skip する 1-pass (amix のみ → encode) コマンド。

    `loudnorm.enabled: false` 経路。pass1/pass2 を呼ばず、amix 結果の `[aout]`
    を直接エンコードする。
    """
    return _build_pass2_cmd(
        master,
        rains,
        filter_expr,
        output,
        bitrate,
        codec=codec,
        sample_rate=sample_rate,
    )


class FinalizeConfig:
    """`audio.finalize.*` を解決した実行設定。

    `_resolve_finalize_config` が組み立てる純粋な値オブジェクト。dataclass を
    避けたのは layer_overrides の dict ネストが含まれるため (frozen 化の意義が薄い)。
    """

    __slots__ = (
        "bitrate",
        "codec",
        "fadein_curve",
        "fadein_s",
        "layers_dirname",
        "layers_glob",
        "layers_overrides",
        "loudnorm",
        "loudnorm_enabled",
        "loudnorm_mode",
        "mix_duration",
        "mix_normalize",
        "sample_rate",
        "volume_db",
    )

    def __init__(
        self,
        *,
        volume_db: float,
        fadein_s: float,
        fadein_curve: str,
        loudnorm: dict[str, float],
        loudnorm_enabled: bool,
        loudnorm_mode: str,
        mix_duration: str,
        mix_normalize: int,
        bitrate: str,
        codec: str,
        sample_rate: int | None,
        layers_dirname: str,
        layers_glob: str,
        layers_overrides: dict[str, dict[str, Any]],
    ) -> None:
        self.volume_db = volume_db
        self.fadein_s = fadein_s
        self.fadein_curve = fadein_curve
        self.loudnorm = loudnorm
        self.loudnorm_enabled = loudnorm_enabled
        self.loudnorm_mode = loudnorm_mode
        self.mix_duration = mix_duration
        self.mix_normalize = mix_normalize
        self.bitrate = bitrate
        self.codec = codec
        self.sample_rate = sample_rate
        self.layers_dirname = layers_dirname
        self.layers_glob = layers_glob
        self.layers_overrides = layers_overrides


def _resolve_finalize_config(skill_cfg: dict[str, Any]) -> FinalizeConfig:
    """skill-config から `audio.finalize.*` を解決する。

    `audio.finalize.ambient_layers.*` が組み込み defaults を上書きする。

    `audio.bitrate` は既存 yt-generate-master とも共有する skill-config の
    トップレベル audio セクションを優先し、`audio.finalize.bitrate` が
    明示指定されていればそれで上書きする。
    """
    audio_cfg = skill_cfg.get("audio") or {}
    finalize_cfg = audio_cfg.get("finalize") or {}
    ambient_cfg = finalize_cfg.get("ambient_layers") or {}

    volume_db = float(ambient_cfg.get("volume_db", _DEFAULT_VOLUME_DB))
    fadein_s = float(ambient_cfg.get("fadein_s", _DEFAULT_FADEIN_S))
    fadein_curve = str(ambient_cfg.get("fadein_curve", _DEFAULT_FADEIN_CURVE))

    layers_dirname = str(ambient_cfg.get("dirname", _DEFAULT_LAYERS_DIRNAME))
    layers_glob = str(ambient_cfg.get("glob", _DEFAULT_LAYERS_GLOB))

    raw_layer_overrides = ambient_cfg.get("layers") or {}
    if not isinstance(raw_layer_overrides, dict):
        raise ConfigError("`audio.finalize.ambient_layers.layers` は dict (filename → 上書き値) である必要があります")
    layer_overrides: dict[str, dict[str, Any]] = {
        str(k): dict(v) for k, v in raw_layer_overrides.items() if isinstance(v, dict)
    }

    # loudnorm は finalize namespace で解決する。
    loudnorm_block = finalize_cfg.get("loudnorm") or {}
    loudnorm_enabled = bool(loudnorm_block.get("enabled", _DEFAULT_LOUDNORM_ENABLED))
    loudnorm_mode = str(loudnorm_block.get("mode", _DEFAULT_LOUDNORM_MODE))
    if loudnorm_mode == "dynamic":
        # ffmpeg loudnorm は linear=true (= measured 注入) と dynamic (= 単発適用) を
        # 切り替えられるが、本 CLI は two-pass linear 前提で組まれている。
        raise NotImplementedError(
            "`audio.finalize.loudnorm.mode: dynamic` は未実装です (現状は two-pass linear のみサポート)。"
        )
    if loudnorm_mode != "linear":
        raise ConfigError(
            f"`audio.finalize.loudnorm.mode` の値が不正です: {loudnorm_mode!r} (許可: 'linear', 'dynamic'[未実装])"
        )
    loudnorm = dict(_DEFAULT_LOUDNORM)
    for key in ("I", "LRA", "TP"):
        if key in loudnorm_block:
            loudnorm[key] = float(loudnorm_block[key])

    # mix セクション (amix の duration / normalize)
    mix_block = finalize_cfg.get("mix") or {}
    mix_duration = str(mix_block.get("duration", _DEFAULT_MIX_DURATION))
    if mix_duration not in {"first", "shortest", "longest"}:
        raise ConfigError(
            f"`audio.finalize.mix.duration` の値が不正です: {mix_duration!r} (許可: 'first', 'shortest', 'longest')"
        )
    mix_normalize_raw = mix_block.get("normalize", _DEFAULT_MIX_NORMALIZE)
    # bool 表現 (True/False) を 1/0 に正規化する
    if isinstance(mix_normalize_raw, bool):
        mix_normalize = 1 if mix_normalize_raw else 0
    else:
        mix_normalize = int(mix_normalize_raw)
    if mix_normalize not in (0, 1):
        raise ConfigError(
            f"`audio.finalize.mix.normalize` の値が不正です: {mix_normalize!r} (許可: 0 / 1 / true / false)"
        )

    # 出力エンコード設定: audio.finalize.{bitrate,codec,sample_rate} > audio.bitrate > default
    bitrate_default = str(audio_cfg.get("bitrate", _DEFAULT_BITRATE))
    bitrate = str(finalize_cfg.get("bitrate", bitrate_default))
    codec = str(finalize_cfg.get("codec", _DEFAULT_CODEC))
    sample_rate_raw = finalize_cfg.get("sample_rate")
    sample_rate: int | None = int(sample_rate_raw) if sample_rate_raw is not None else _DEFAULT_SAMPLE_RATE

    return FinalizeConfig(
        volume_db=volume_db,
        fadein_s=fadein_s,
        fadein_curve=fadein_curve,
        loudnorm=loudnorm,
        loudnorm_enabled=loudnorm_enabled,
        loudnorm_mode=loudnorm_mode,
        mix_duration=mix_duration,
        mix_normalize=mix_normalize,
        bitrate=bitrate,
        codec=codec,
        sample_rate=sample_rate,
        layers_dirname=layers_dirname,
        layers_glob=layers_glob,
        layers_overrides=layer_overrides,
    )


def _layer_overrides_for(rains: list[Path], overrides: dict[str, dict[str, Any]]) -> list[dict[str, Any] | None]:
    """layer ファイル名 → override dict を `rains` の並びにあわせて展開する。"""
    return [overrides.get(rain.name) for rain in rains]


def finalize_master(
    collection_dir: Path,
    channel: Path,
    *,
    quiet: bool = False,
) -> int:
    """`01-master/master.mp3` に ambient layer を被せて in-place 上書きする。

    pass-through gate: ambient layer ファイルが 0 件なら skill-config も
    ffmpeg も触らず即 0 を返す (config 検証は gate 通過後にのみ実行する契約)。
    `loudnorm.enabled: false` 経路では pass1/pass2 を skip して amix 単発で
    encode する。

    フェイズ: gate → cfg 解決 → (loudnorm 有効なら) pass1 measure → pass2 apply
    / (loudnorm 無効なら) single pass amix → atomic rename。
    """
    # gate1 (skill-config 不読み込み): デフォルト規約 `branding/rain_layers/rain_*.wav`
    # で何も見つからない場合、skill-config に到達せず即 pass-through する
    # (未対応チャンネルに config 検証コストを払わせない)。
    # skill-config で `audio.finalize.ambient_layers.{dirname,glob}` を上書きする
    # 場合、ユーザーは既定パスにも 1 つ wav を置くか、または config 上書き後の
    # パスに置いたあとでも legacy デフォルトを通る `rain_*.wav` を 1 つ置く運用とする
    # (gate コストと汎用化の両立)。
    if not find_ambient_layers(channel):
        return 0

    cfg = load_skill_config(_SKILL_NAME)
    finalize_cfg = _resolve_finalize_config(cfg)

    # gate2 (skill-config 反映後): 上書きパスで再判定。上書きにより 0 件になる
    # ケースもここで安全に pass-through する。
    rains = find_ambient_layers(
        channel,
        layers_dirname=finalize_cfg.layers_dirname,
        glob_pattern=finalize_cfg.layers_glob,
    )
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

    layer_overrides = _layer_overrides_for(rains, finalize_cfg.layers_overrides)

    tmp = master.with_name(_MASTER_TMP_FILENAME)
    try:
        if not quiet:
            print(f"  Layering {len(rains)} ambient layer(s) onto {master.name}...")

        if not finalize_cfg.loudnorm_enabled:
            # loudnorm を完全に skip して amix だけで encode する 1-pass モード。
            single_filter = build_filter(
                len(rains),
                finalize_cfg.volume_db,
                finalize_cfg.fadein_s,
                finalize_cfg.loudnorm,
                measured=None,
                fadein_curve=finalize_cfg.fadein_curve,
                mix_duration=finalize_cfg.mix_duration,
                mix_normalize=finalize_cfg.mix_normalize,
                layer_overrides=layer_overrides,
                apply_loudnorm=False,
            )
            single_cmd = _build_single_pass_cmd(
                master,
                rains,
                single_filter,
                tmp,
                finalize_cfg.bitrate,
                codec=finalize_cfg.codec,
                sample_rate=finalize_cfg.sample_rate,
            )
            single = subprocess.run(single_cmd, capture_output=True, text=True, check=False)
            if single.returncode != 0:
                print(
                    f"ERROR: ffmpeg (single-pass amix) failed (rc={single.returncode})",
                    file=sys.stderr,
                )
                if single.stderr:
                    print(single.stderr, file=sys.stderr)
                return 1
            os.replace(tmp, master)
            if not quiet:
                print(f"  ✓ Ambient layer applied (loudnorm skipped): {master.name}")
            return 0

        # pass1: loudnorm measure (stderr に print_format=json で計測値が出る)
        pass1_filter = build_filter(
            len(rains),
            finalize_cfg.volume_db,
            finalize_cfg.fadein_s,
            finalize_cfg.loudnorm,
            measured=None,
            fadein_curve=finalize_cfg.fadein_curve,
            mix_duration=finalize_cfg.mix_duration,
            mix_normalize=finalize_cfg.mix_normalize,
            layer_overrides=layer_overrides,
        )
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
        pass2_filter = build_filter(
            len(rains),
            finalize_cfg.volume_db,
            finalize_cfg.fadein_s,
            finalize_cfg.loudnorm,
            measured=measured,
            fadein_curve=finalize_cfg.fadein_curve,
            mix_duration=finalize_cfg.mix_duration,
            mix_normalize=finalize_cfg.mix_normalize,
            layer_overrides=layer_overrides,
        )
        pass2_cmd = _build_pass2_cmd(
            master,
            rains,
            pass2_filter,
            tmp,
            finalize_cfg.bitrate,
            codec=finalize_cfg.codec,
            sample_rate=finalize_cfg.sample_rate,
        )
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
            print(f"  ✓ Ambient layer applied: {master.name}")
        return 0
    except ValidationError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    finally:
        # pass1/pass2/single の中断・例外・失敗いずれの経路でも tmp 残骸を必ず掃除する。
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                # tmp 削除失敗は master 保護の本体には影響しないため握りつぶす
                # (主目的の master.mp3 はこの時点で無傷)。
                pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="branding/<layers_dir>/ の ambient レイヤーをマスター音源にレイヤーする",
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
