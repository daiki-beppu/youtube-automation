#!/usr/bin/env python3
"""Shorts (9:16) 用ループ動画を Veo 3.1 API で生成する.

`10-assets/short.png`（無ければ `short.jpg`）を入力に、`aspect_ratio="9:16"` で
8秒の縦型シームレスループ動画を生成し `10-assets/short-loop.mp4` に保存する.

Usage:
    yt-generate-shorts-loop <collection-path>
    yt-generate-shorts-loop <collection-path> --model veo-3.1-lite-generate-preview
    yt-generate-shorts-loop <collection-path> -y    # 確認スキップ
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from youtube_automation.infrastructure.errors import ConfigError
from youtube_automation.utils.collection_paths import CollectionPaths
from youtube_automation.utils.genai_client import create_genai_client
from youtube_automation.utils.skill_config import load_skill_config
from youtube_automation.utils.veo_generator import (
    DEFAULT_MODEL,
    DEFAULT_PROMPT,
    generate_loop_video,
)

SHORT_ASPECT_RATIO = "9:16"
SHORT_SKILL_NAME = "short"


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
        description="Veo 3.1 Shorts (9:16) ループ動画生成",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("collection", nargs="?", help="コレクションパス (collections/live/<name>/)")
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


def main() -> None:
    load_dotenv(find_dotenv())

    parser = _build_parser()
    args = parser.parse_args()

    # short skill-config から veo セクションを読み込む（plan 要件 14-c）
    skill_cfg = load_skill_config(SHORT_SKILL_NAME)
    veo_cfg = skill_cfg.get("veo", {})
    model = args.model or veo_cfg.get("model", DEFAULT_MODEL)
    prompt = args.prompt or veo_cfg.get("default_prompt", DEFAULT_PROMPT)

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
    print("  Veo 3.1 Shorts (9:16) ループ動画生成")
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

    # 生成実行
    try:
        client = create_genai_client(location="us-central1")
    except ConfigError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    start_time = time.monotonic()
    success = generate_loop_video(
        client,
        image_path,
        output_path,
        model,
        prompt,
        aspect_ratio=SHORT_ASPECT_RATIO,
    )
    elapsed = time.monotonic() - start_time

    print()
    print("===========================================")
    if success:
        print("  Shorts ループ動画生成: 完了")
        print(f"  ファイル: {output_path}")
        print(f"  時間:     {elapsed:.1f}秒")
    else:
        print("  Shorts ループ動画生成: 失敗")
        print("  --prompt でプロンプトを変えて再試行してください。")
    print("===========================================")
    print()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
