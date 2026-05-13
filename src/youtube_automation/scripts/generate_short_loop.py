#!/usr/bin/env python3
"""Shorts 用 9:16 ループ動画を Veo 3.1 API で生成する。

`short.png`（9:16 縦型サムネイル）を開始・終了フレームに指定し、
キャラクターアニメーション付きの 8 秒シームレスループ動画を生成する。

Usage:
    uv run yt-shorts-generate-loop <collection-path>
    uv run yt-shorts-generate-loop <collection-path> --prompt "gentle wind..."
    uv run yt-shorts-generate-loop                   # CWD がコレクションディレクトリの場合
    uv run yt-shorts-generate-loop <collection-path> --no-trim
"""

import argparse
import sys
import time
from pathlib import Path

from youtube_automation.utils.config import channel_dir
from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.skill_config import load_skill_config
from youtube_automation.utils.veo_generator import (
    DEFAULT_MODEL,
    generate_loop_video,
    trim_tail,
)

SHORT_DEFAULT_PROMPT = (
    "Gentle character animation: the character slowly moves their head, "
    "hair sways softly in the breeze, clothing ripples with subtle movement, "
    "hand gently reaches toward a light source. "
    "Flowers and plants sway gently in the wind. "
    "Soft flickering light shifts on surfaces. "
    "Keep all text completely static and unchanged. "
    "No smoke, no particles, no falling objects."
)


def _load_veo_config() -> dict:
    """loop-video skill-config の `veo` セクションを読み込む（Shorts も同設定を共有）."""
    return load_skill_config("loop-video").get("veo", {})


def _resolve_paths(collection_path: Path) -> tuple[Path, Path]:
    """コレクションパスから `short.png` と出力動画のパスを解決する."""
    image_path = collection_path / "10-assets" / "short.png"
    output_path = collection_path / "10-assets" / "short-loop.mp4"
    return image_path, output_path


def main():
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv())

    parser = argparse.ArgumentParser(description="Veo 3.1 Shorts 用 9:16 ループ動画生成")
    parser.add_argument("collection", nargs="?", help="コレクションパス")
    parser.add_argument("--prompt", help="動画生成プロンプト")
    parser.add_argument(
        "--model",
        choices=["veo-3.1-fast-generate-001", "veo-3.1-generate-001"],
        help="Veo モデル名 (default: veo-3.1-fast-generate-001)",
    )
    parser.add_argument("--no-trim", action="store_true", help="末尾トリムをスキップ")
    parser.add_argument("--trim-tail", type=float, default=1.0, help="末尾トリム秒数 (デフォルト: 1.0)")
    parser.add_argument("-y", "--yes", action="store_true", help="確認をスキップ")
    args = parser.parse_args()

    veo_config = _load_veo_config()
    model = args.model or veo_config.get("model", DEFAULT_MODEL)
    prompt = args.prompt or SHORT_DEFAULT_PROMPT

    if args.collection:
        collection_path = Path(args.collection)
        if not collection_path.is_absolute():
            collection_path = Path.cwd() / collection_path
        image_path, output_path = _resolve_paths(collection_path)
    else:
        cwd = Path.cwd()
        if (cwd / "10-assets").exists():
            image_path, output_path = _resolve_paths(cwd)
        else:
            parser.error("コレクションパスを指定するか、コレクションディレクトリ内で実行してください")
            return

    if not image_path.exists():
        print(f"[ERROR] short.png が見つかりません: {image_path}")
        print("  /short-thumbnail で先に 9:16 サムネイルを生成してください")
        sys.exit(1)

    print()
    print("===========================================")
    print("  Veo 3.1 Shorts 用ループ動画生成")
    print("===========================================")
    print(f"  入力:   {image_path}")
    print(f"  出力:   {output_path}")
    print(f"  モデル: {model}")
    print("  比率:   9:16（縦型）")
    print(f"  トリム: {'なし' if args.no_trim else f'末尾 {args.trim_tail}秒カット'}")
    print("===========================================")
    print()

    if not args.yes:
        try:
            answer = input("  生成しますか？ [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  キャンセルしました。")
            sys.exit(0)
        if answer not in ("y", "yes"):
            print("  キャンセルしました。")
            sys.exit(0)

    try:
        from youtube_automation.utils.genai_client import create_genai_client
    except ImportError:
        print("[ERROR] google-genai がインストールされていません。")
        sys.exit(1)

    try:
        client = create_genai_client(location="us-central1")
    except ConfigError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    start_time = time.monotonic()
    success = generate_loop_video(client, image_path, output_path, model, prompt, aspect_ratio="9:16")

    if success and not args.no_trim:
        trim_tail(output_path, args.trim_tail)

    elapsed = time.monotonic() - start_time

    print()
    print("===========================================")
    if success:
        print("  Shorts ループ動画生成: 完了")
        try:
            print(f"  ファイル: {output_path.relative_to(channel_dir())}")
        except ValueError:
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
