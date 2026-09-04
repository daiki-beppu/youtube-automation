#!/usr/bin/env python3
"""Shorts (9:16) 用ループ動画を Veo または fal.ai で生成する.

`10-assets/short.png`（無ければ `short.jpg`）を入力に、`aspect_ratio="9:16"` で
8秒の縦型シームレスループ動画を生成し `10-assets/short-loop.mp4` に保存する.

Usage:
    yt-generate-shorts-loop <collection-path>
    yt-generate-shorts-loop <collection-path> --model veo-3.1-lite-generate-preview
    yt-generate-shorts-loop <collection-path> -y    # 確認スキップ
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from youtube_automation.configuration.skills import load_skill_config
from youtube_automation.core.errors import ConfigError
from youtube_automation.infrastructure.media.collection_paths import CollectionPaths
from youtube_automation.infrastructure.media.fal_video_generator import (
    DEFAULT_ALLOWED_MODELS as DEFAULT_FAL_ALLOWED_MODELS,
)
from youtube_automation.infrastructure.media.fal_video_generator import (
    DEFAULT_CANVAS as DEFAULT_FAL_CANVAS,
)
from youtube_automation.infrastructure.media.fal_video_generator import (
    DEFAULT_MODEL as DEFAULT_FAL_MODEL,
)
from youtube_automation.infrastructure.media.fal_video_generator import (
    generate_loop_video as generate_fal_loop_video,
)
from youtube_automation.infrastructure.media.genai_client import create_veo_genai_client
from youtube_automation.infrastructure.media.veo_generator import (
    DEFAULT_MODEL,
    DEFAULT_PROMPT,
    generate_loop_video,
)

SHORT_ASPECT_RATIO = "9:16"
SHORT_SKILL_NAME = "short"
DEFAULT_ENGINE = "veo"


def resolve_paths(collection_path: Path) -> tuple[Path, Path]:
    """コレクションパスから入力画像と出力動画のパスを解決する.

    `short.png` を優先、無ければ `short.jpg` にフォールバック.
    出力は常に `short-loop.mp4`.

    Returns:
        (image_path, output_path)
    """
    paths = CollectionPaths(collection_path)
    image_path = paths.find_short_loop_input_image()
    if image_path is None:
        searched = ", ".join(str(path) for path in paths.short_loop_input_image_search_paths())
        raise FileNotFoundError(f"Shorts ループ動画の入力画像が見つかりません。探索パス: {searched}")
    return image_path, paths.short_loop


def _build_parser() -> argparse.ArgumentParser:
    # `generate_loop_video.py` と同じく `--model` は preview/GA 切替を許容するため
    # choices で縛らず任意文字列を受ける（未知モデルは Vertex AI 側でエラー）.
    parser = argparse.ArgumentParser(
        description="Shorts (9:16) ループ動画生成",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("collection", nargs="?", help="コレクションパス (collections/live/<name>/)")
    parser.add_argument(
        "--engine", choices=("veo", "fal"), help="生成 engine (default: skill-config の engine, fallback: veo)"
    )
    parser.add_argument("--prompt", help="動画生成プロンプト (default: skill-config の veo.default_prompt)")
    parser.add_argument(
        "--model",
        help=(
            "Veo モデル名 (default: skill-config の veo.model, fallback: veo-3.1-fast-generate-001)。"
            " 例: veo-3.1-fast-generate-001 / veo-3.1-generate-001 / veo-3.1-lite-generate-preview"
        ),
    )
    parser.add_argument("-y", "--yes", action="store_true", help="確認をスキップ")
    return parser


def probe_video_dimensions(path: Path) -> tuple[int, int] | None:
    """ffprobe で生成物の実寸を読む。取得不能でも生成結果は失敗にしない。"""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    try:
        stream = json.loads(result.stdout)["streams"][0]
        return int(stream["width"]), int(stream["height"])
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        return None


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    # CLI を最優先し、未指定なら short skill-config の engine を使う。
    skill_cfg = load_skill_config(SHORT_SKILL_NAME)
    engine = args.engine or skill_cfg.get("engine", DEFAULT_ENGINE)
    veo_cfg = skill_cfg.get("veo", {})
    fal_cfg = skill_cfg.get("fal", {})
    engine_cfg = fal_cfg if engine == "fal" else veo_cfg
    default_model = DEFAULT_FAL_MODEL if engine == "fal" else DEFAULT_MODEL
    model = args.model or engine_cfg.get("model", default_model)
    prompt = args.prompt or engine_cfg.get("default_prompt", veo_cfg.get("default_prompt", DEFAULT_PROMPT))

    # コレクションパス解決
    if args.collection:
        collection_path = Path(args.collection)
        if not collection_path.is_absolute():
            collection_path = Path.cwd() / collection_path
    else:
        cwd = Path.cwd()
        if CollectionPaths(cwd).assets_dir.exists():
            collection_path = cwd
        else:
            parser.error("コレクションパスを指定するか、コレクションディレクトリ内で実行してください")
            return

    try:
        image_path, output_path = resolve_paths(collection_path)
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    # 確認プロンプト
    print()
    print("===========================================")
    print(f"  {engine} Shorts (9:16) ループ動画生成")
    print("===========================================")
    print(f"  入力:     {image_path}")
    print(f"  出力:     {output_path}")
    print(f"  モデル:   {model}")
    print(f"  比率:     {SHORT_ASPECT_RATIO}")
    print("===========================================")
    print()

    if not args.yes:
        answer = input("  生成しますか？ [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("  キャンセルしました。")
            sys.exit(0)

    start_time = time.monotonic()
    if engine == "fal":
        raw_canvas = fal_cfg.get("canvas", DEFAULT_FAL_CANVAS)
        canvas = {str(key): tuple(value) for key, value in raw_canvas.items()}
        upscale = fal_cfg.get("upscale_to", [1080, 1920])
        success = generate_fal_loop_video(
            image_path,
            output_path,
            model,
            prompt,
            duration_seconds=int(fal_cfg.get("duration_seconds", 5)),
            aspect_ratio=SHORT_ASPECT_RATIO,
            resolution=str(fal_cfg.get("resolution", "768P")),
            prompt_expansion_mode=str(fal_cfg.get("prompt_expansion_mode", "balanced")),
            timeout_sec=float(fal_cfg.get("timeout_seconds", 600)),
            poll_interval_sec=float(fal_cfg.get("poll_interval_seconds", 2)),
            allowed_models=frozenset(fal_cfg.get("allowed_models", DEFAULT_FAL_ALLOWED_MODELS)),
            canvas=canvas,
            upscale_to=tuple(upscale) if upscale is not None else None,
        )
    else:
        try:
            client = create_veo_genai_client()
        except ConfigError as e:
            print(f"[ERROR] {e}")
            sys.exit(1)
        success = generate_loop_video(client, image_path, output_path, model, prompt, aspect_ratio=SHORT_ASPECT_RATIO)
    elapsed = time.monotonic() - start_time

    print()
    print("===========================================")
    if success:
        print("  Shorts ループ動画生成: 完了")
        print(f"  ファイル: {output_path}")
        dimensions = probe_video_dimensions(output_path)
        if dimensions is not None:
            print(f"  実寸:     {dimensions[0]}x{dimensions[1]}")
        print(f"  時間:     {elapsed:.1f}秒")
    else:
        print("  Shorts ループ動画生成: 失敗")
        print("  --prompt でプロンプトを変えて再試行してください。")
    print("===========================================")
    print()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
