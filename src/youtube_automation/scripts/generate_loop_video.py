#!/usr/bin/env python3
"""コレクション用ループ動画背景を Veo 3.1 / Gemini Omni Flash で生成する。

main.png を開始・終了フレーム両方に指定し、微細なアニメーション付きの
シームレスなループ動画を生成する。

Usage:
    # コレクションパス指定（通常: Veo 生成 → 既存 loop.mp4 を退避し、保持上限超過分を削除）
    python3 generate_loop_video.py <collection-path>
    python3 generate_loop_video.py <collection-path> --prompt "gentle wind..."

    # CWD がコレクションディレクトリの場合
    python3 generate_loop_video.py

    # 既存 loop.mp4 があれば Veo を叩かず skip（再課金回避・冪等再実行）
    python3 generate_loop_video.py <collection-path> --skip-existing

    # post-process 専用: 既存 loop.mp4 に FFmpeg クロスフェード補正のみ適用（Veo を叩かない）
    python3 generate_loop_video.py <collection-path> --smooth
"""

import argparse
import sys
import time
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.genai_client import create_genai_client
from youtube_automation.utils.omni_generator import (
    DEFAULT_MODEL as DEFAULT_OMNI_MODEL,
)
from youtube_automation.utils.omni_generator import (
    create_omni_client,
)
from youtube_automation.utils.omni_generator import (
    generate_loop_video as generate_omni_loop_video,
)
from youtube_automation.utils.veo_generator import (
    DEFAULT_MODEL,
    DEFAULT_PROMPT,
    build_structured_prompt,
    generate_loop_video,
    smooth_loop,
)
from youtube_automation.utils.video_type import VideoType, VideoTypeConfig


def _channel_root() -> Path:
    from youtube_automation.configuration import channel_dir

    return channel_dir()


# ファイル名・ディレクトリ名は契約文字列のため定数で 1 箇所に集約
ASSETS_DIR = "10-assets"
INPUT_PNG = "main.png"
INPUT_JPG = "main.jpg"
OUTPUT_MP4 = "loop.mp4"
BACKUP_PREFIX = "loop-v"
BACKUP_SUFFIX = ".mp4"
DEFAULT_MAX_BACKUPS = 3


def load_config() -> dict:
    """loop-video skill-config 全体を読み込む（max_backups / veo / compression を含む）。"""
    try:
        from youtube_automation.utils.skill_config import load_skill_config

        return load_skill_config("loop-video")
    except Exception:
        return {}


def _parse_csv(value: str | None) -> list[str]:
    """カンマ区切り文字列を strip+filter した list にする。"""
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def resolve_prompt(args, veo_config: dict) -> str:
    """CLI 引数と skill-config から最終プロンプトを決定する。

    優先順位:
      1. --prompt（全文上書き、最強）
      2. CLI --motion-targets / --static-targets で structured 構築
      3. skill-config の motion_targets / static_targets で structured 構築
      4. skill-config の default_prompt
      5. ハードコード DEFAULT_PROMPT
    """
    if args.prompt:
        if args.motion_targets or args.static_targets:
            print("  [Warn]   --prompt が指定されたため --motion-targets / --static-targets は無視されます")
        return args.prompt

    template = veo_config.get("prompt_template", "")
    base_rules = veo_config.get("base_rules", "")

    cli_motion = _parse_csv(args.motion_targets)
    cli_static = _parse_csv(args.static_targets)
    if (cli_motion or cli_static) and not template:
        print("  [Warn]   prompt_template が skill-config に無いため structured 構築をスキップ")
    elif cli_motion or cli_static:
        try:
            return build_structured_prompt(cli_motion, cli_static, template, base_rules)
        except ValueError as e:
            print(f"  [Warn]   CLI structured prompt 構築失敗 ({e}) → default_prompt にフォールバック")

    cfg_motion = list(veo_config.get("motion_targets") or [])
    cfg_static = list(veo_config.get("static_targets") or [])
    if (cfg_motion or cfg_static) and template:
        try:
            return build_structured_prompt(cfg_motion, cfg_static, template, base_rules)
        except ValueError:
            pass

    return veo_config.get("default_prompt") or DEFAULT_PROMPT


def resolve_collection_paths(collection_path: Path) -> tuple[Path, Path]:
    """コレクションパスから入力画像と出力動画のパスを解決する（pure: 副作用ゼロ）。

    `main.png` を優先し、無ければ `main.jpg` にフォールバック。
    両方無い場合も raise せず `main.png` の path を返す（validation は呼出側責務）。
    既存 `loop.mp4` の rename は本関数では行わない（→ `_backup_existing_loop`）。
    """
    assets = collection_path / ASSETS_DIR
    image_path = assets / INPUT_PNG
    if not image_path.exists():
        jpg_path = assets / INPUT_JPG
        if jpg_path.exists():
            image_path = jpg_path
    output_path = assets / OUTPUT_MP4
    return image_path, output_path


def _backup_existing_loop(output_path: Path, max_backups: int = DEFAULT_MAX_BACKUPS) -> Path:
    """既存 `loop.mp4` を退避し、古いバックアップを保持上限まで削除する。

    Args:
        output_path: 退避対象の `loop.mp4` path。
        max_backups: 保持する `loop-v{n}.mp4` の最大数。

    Returns:
        退避先 path（`loop-v{n}.mp4`）。
    """
    parent = output_path.parent
    numbered_backups: list[tuple[int, Path]] = []
    for candidate in parent.glob(f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}"):
        number_text = candidate.name[len(BACKUP_PREFIX) : -len(BACKUP_SUFFIX)]
        if number_text.isdigit():
            numbered_backups.append((int(number_text), candidate))

    next_number = max((number for number, _path in numbered_backups), default=0) + 1
    backup = parent / f"{BACKUP_PREFIX}{next_number}{BACKUP_SUFFIX}"
    output_path.rename(backup)
    print(f"  [Backup] 既存ファイルを {backup.name} にリネーム")

    numbered_backups.append((next_number, backup))
    excess_count = len(numbered_backups) - max_backups
    for _number, old_backup in sorted(numbered_backups)[: max(0, excess_count)]:
        old_backup.unlink()
        print(f"  [Backup] 古いバックアップを削除: {old_backup.name}")

    return backup


def _build_parser() -> argparse.ArgumentParser:
    # Veo の preview/GA リリースサイクルに追従するため、`--model` は choices で
    # 縛らず任意文字列を受ける。未知モデルは Vertex AI 側でエラーになる。
    # RawTextHelpFormatter: help 文字列にハイフン入りモデル名が連なるため、
    # 80 桁折り返しで `veo-3.1-lite-` / `generate-preview` のように分断されないようにする。
    parser = argparse.ArgumentParser(
        description="Veo 3.1 / Gemini Omni Flash コレクションループ動画生成",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("collection", nargs="?", help="コレクションパス")
    parser.add_argument(
        "--engine",
        choices=("veo", "omni"),
        default="veo",
        help="動画生成エンジン (default: veo)",
    )
    parser.add_argument(
        "--prompt",
        help="動画生成プロンプト（全文上書き、最強）。指定時は --motion-targets / --static-targets は無視される",
    )
    parser.add_argument(
        "--motion-targets",
        dest="motion_targets",
        help=(
            "動かす対象（カンマ区切り）。skill-config の prompt_template に展開される。"
            " 例: 'slow leaves swaying,subtle steam rising from coffee'"
        ),
    )
    parser.add_argument(
        "--static-targets",
        dest="static_targets",
        help=(
            "固定対象（カンマ区切り）。数や形を保持したい要素はカウントを書く。"
            " 例: 'the character,two animals (count remains 2),bird bath'"
        ),
    )
    parser.add_argument(
        "--model",
        help=(
            "モデル名 (default: 選択 engine の skill-config model)。"
            " 例: veo-3.1-fast-generate-001 / veo-3.1-generate-001 / veo-3.1-lite-generate-preview"
        ),
    )
    parser.add_argument(
        "--smooth",
        action="store_true",
        help="post-process 専用: 既存 loop.mp4 に FFmpeg クロスフェード補正のみ適用 (Veo を叩かない)",
    )
    parser.add_argument("--crossfade", type=float, default=0.5, help="クロスフェード秒数 (デフォルト: 0.5)")
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="既存 loop.mp4 があれば生成 API を叩かず skip して終了 (再課金回避)",
    )
    parser.add_argument("-y", "--yes", action="store_true", help="確認をスキップ")
    return parser


def _resolve_collection_path(args: argparse.Namespace, parser: argparse.ArgumentParser) -> Path:
    """CLI 引数または CWD からコレクションパスを解決する。"""
    if args.collection:
        collection_path = Path(args.collection)
        if not collection_path.is_absolute():
            collection_path = Path.cwd() / collection_path
        return collection_path

    cwd = Path.cwd()
    if (cwd / ASSETS_DIR).exists():
        return cwd

    parser.error("コレクションパスを指定するか、コレクションディレクトリ内で実行してください")
    raise SystemExit(2)  # parser.error は NoReturn だが型推論補助


def _run_smooth_only(output_path: Path, crossfade: float, compression: dict | None = None) -> None:
    """`--smooth` 早期分岐: 既存 loop.mp4 に post-process のみ適用する。

    Veo クライアントは生成せず、confirm prompt も出さない（IR3）。
    入力 `loop.mp4` 不在時は明確なエラーで exit 1（IR1: エラー握りつぶし禁止）。
    """
    if not output_path.exists():
        print(f"[ERROR] --smooth は既存 {output_path.name} を必要としますが見つかりません: {output_path}")
        sys.exit(1)

    crf, preset = _resolve_smooth_codec(compression)

    print()
    print("===========================================")
    print("  ループ動画 post-process (--smooth)")
    print("===========================================")
    print(f"  対象:       {output_path}")
    print(f"  crossfade:  {crossfade}s")
    print(f"  encode:     CRF {crf} / preset {preset}")
    print("===========================================")
    print()

    smooth_loop(output_path, crossfade, trim_tail_sec=0.0, crf=crf, preset=preset)
    sys.exit(0)


def _resolve_smooth_codec(compression: dict | None) -> tuple[int, str]:
    """`--smooth` の crf/preset を解決する。compression 無効時は legacy CRF 18 に倒す。"""
    if compression and compression.get("enabled", True):
        return int(compression.get("crf", 22)), str(compression.get("preset", "slow"))
    return 18, "slow"


def _run_skip_existing(output_path: Path) -> None:
    """`--skip-existing` 早期分岐: 既存 loop.mp4 を温存して exit 0 (IR2)。"""
    print()
    print("===========================================")
    print("  ループ動画生成: skip (--skip-existing)")
    print("===========================================")
    print(f"  既存ファイル: {output_path}")
    print("  既存 loop.mp4 が存在するため生成 API を呼ばずに終了します。")
    print("===========================================")
    print()
    sys.exit(0)


def _run_generate(
    image_path: Path,
    output_path: Path,
    model: str,
    prompt: str,
    *,
    engine: str = "veo",
    engine_config: dict | None = None,
    assume_yes: bool,
    max_backups: int = DEFAULT_MAX_BACKUPS,
    compression: dict | None = None,
) -> None:
    """通常経路: image 検証 → confirm → backup → 選択 engine 生成 → report。"""
    if not image_path.exists():
        print(f"[ERROR] 入力画像が見つかりません: {image_path}")
        sys.exit(1)

    print()
    print("===========================================")
    print(f"  {engine} ループ動画生成")
    print("===========================================")
    print(f"  入力:   {image_path}")
    print(f"  出力:   {output_path}")
    print(f"  モデル: {model}")
    print("===========================================")
    print()

    if not assume_yes:
        answer = input("  生成しますか？ [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("  キャンセルしました。")
            sys.exit(0)

    if output_path.exists():
        _backup_existing_loop(output_path, max_backups=max_backups)

    try:
        client = create_omni_client() if engine == "omni" else create_genai_client(location="us-central1")
    except ConfigError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    start_time = time.monotonic()
    if engine == "omni":
        omni_config = engine_config or {}
        success = generate_omni_loop_video(
            client,
            image_path,
            output_path,
            model,
            prompt,
            timeout_sec=float(omni_config.get("timeout_seconds", 600)),
            poll_interval_sec=float(omni_config.get("poll_interval_seconds", 5)),
            compression=compression,
        )
    else:
        success = generate_loop_video(client, image_path, output_path, model, prompt, compression=compression)
    elapsed = time.monotonic() - start_time

    print()
    print("===========================================")
    if success:
        print("  ループ動画生成: 完了")
        try:
            print(f"  ファイル: {output_path.relative_to(_channel_root())}")
        except (ValueError, ConfigError):
            print(f"  ファイル: {output_path}")
        print(f"  時間:     {elapsed:.1f}秒")
    else:
        print("  ループ動画生成: 失敗")
        print("  --prompt または engine 設定を確認して再試行してください。")
    print("===========================================")
    print()

    sys.exit(0 if success else 1)


def main():
    load_dotenv(find_dotenv())

    parser = _build_parser()
    args = parser.parse_args()

    skill_config = load_config()
    try:
        video_type = VideoTypeConfig.from_mapping(
            skill_config,
            config_path="config/skills/loop-video.yaml::video_type",
        ).video_type
    except ConfigError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
    if video_type is not VideoType.LOOP:
        print(
            f"[ERROR] yt-generate-loop-video does not generate video_type={video_type.value!r}; use video_type='loop'",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"  [Config] video_type={video_type.value}")
    if not skill_config.get("enabled", True):
        print(
            "ループ動画化はチャンネル設定で無効化されています。"
            "config/skills/loop-video.yaml::enabled を確認してください",
            file=sys.stderr,
        )
        sys.exit(1)
    engine_config = skill_config.get(args.engine, {})
    compression_config = skill_config.get("compression", {})
    max_backups = int(skill_config.get("max_backups", DEFAULT_MAX_BACKUPS))
    default_model = DEFAULT_OMNI_MODEL if args.engine == "omni" else DEFAULT_MODEL
    model = args.model or engine_config.get("model", default_model)
    prompt = resolve_prompt(args, engine_config)

    collection_path = _resolve_collection_path(args, parser)
    image_path, output_path = resolve_collection_paths(collection_path)

    # 分岐優先順位: --smooth (明示アクション) > --skip-existing (no-op) > 通常経路
    if args.smooth:
        _run_smooth_only(output_path, args.crossfade, compression=compression_config)

    if args.skip_existing and output_path.exists():
        _run_skip_existing(output_path)

    _run_generate(
        image_path,
        output_path,
        model,
        prompt,
        engine=args.engine,
        engine_config=engine_config,
        assume_yes=args.yes,
        max_backups=max_backups,
        compression=compression_config,
    )


if __name__ == "__main__":
    main()
