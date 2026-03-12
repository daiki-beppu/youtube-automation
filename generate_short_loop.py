#!/usr/bin/env python3
"""ショート用 9:16 ループ動画を Veo 3.1 API で生成する。

short.png（9:16 縦型サムネイル）を開始・終了フレームに指定し、
キャラクターアニメーション付きの 8秒シームレスループ動画を生成する。

Usage:
    # コレクションパス指定
    python3 generate_short_loop.py <collection-path>
    python3 generate_short_loop.py <collection-path> --prompt "gentle wind..."

    # CWD がコレクションディレクトリの場合
    python3 generate_short_loop.py

    # 末尾トリムなし
    python3 generate_short_loop.py <collection-path> --no-trim
"""

import argparse
import os
import sys
import time
from pathlib import Path

# --- パス解決 ---
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

import utils._path_setup  # noqa: F401, E402
from utils.veo_generator import (  # noqa: E402
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


def load_config() -> dict:
    """ChannelConfig から veo 設定を読み込む。"""
    try:
        from utils.channel_config import ChannelConfig  # noqa: E402
        config = ChannelConfig.load()
        return config.raw.get("veo", {})
    except Exception:
        return {}


def resolve_paths(collection_path: Path) -> tuple[Path, Path]:
    """コレクションパスから short.png と出力動画のパスを解決する。"""
    image_path = collection_path / "10-assets" / "short.png"
    output_path = collection_path / "10-assets" / "short-loop.mp4"
    return image_path, output_path


def main():
    from dotenv import find_dotenv, load_dotenv
    load_dotenv(find_dotenv())

    parser = argparse.ArgumentParser(description="Veo 3.1 ショート用 9:16 ループ動画生成")
    parser.add_argument("collection", nargs="?", help="コレクションパス")
    parser.add_argument("--prompt", help="動画生成プロンプト")
    parser.add_argument("--model", help="Veo モデル名")
    parser.add_argument("--no-trim", action="store_true", help="末尾トリムをスキップ")
    parser.add_argument("--trim-tail", type=float, default=1.0, help="末尾トリム秒数 (デフォルト: 1.0)")
    parser.add_argument("-y", "--yes", action="store_true", help="確認をスキップ")
    args = parser.parse_args()

    # 設定読み込み
    veo_config = load_config()
    model = args.model or veo_config.get("model", DEFAULT_MODEL)
    prompt = args.prompt or SHORT_DEFAULT_PROMPT

    # パス解決
    if args.collection:
        collection_path = Path(args.collection)
        if not collection_path.is_absolute():
            collection_path = Path.cwd() / collection_path
        image_path, output_path = resolve_paths(collection_path)
    else:
        cwd = Path.cwd()
        if (cwd / "10-assets").exists():
            image_path, output_path = resolve_paths(cwd)
        else:
            parser.error("コレクションパスを指定するか、コレクションディレクトリ内で実行してください")
            return

    # バリデーション
    if not image_path.exists():
        print(f"[ERROR] short.png が見つかりません: {image_path}")
        print("  /short-thumbnail で先に 9:16 サムネイルを生成してください")
        sys.exit(1)

    # 確認
    print()
    print("===========================================")
    print("  Veo 3.1 ショート用ループ動画生成")
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

    # API キー確認
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[ERROR] GEMINI_API_KEY 環境変数が設定されていません。")
        print("  export GEMINI_API_KEY='your-api-key'")
        sys.exit(1)

    # SDK インポート
    try:
        from google import genai
    except ImportError:
        print("[ERROR] google-genai がインストールされていません。")
        print("  pip3 install google-genai --break-system-packages")
        sys.exit(1)

    # 生成実行
    client = genai.Client()
    start_time = time.monotonic()
    success = generate_loop_video(client, image_path, output_path, model, prompt, aspect_ratio="9:16")

    if success and not args.no_trim:
        trim_tail(output_path, args.trim_tail)

    elapsed = time.monotonic() - start_time

    # レポート
    print()
    print("===========================================")
    if success:
        print("  ショートループ動画生成: 完了")
        try:
            print(f"  ファイル: {output_path.relative_to(REPO_ROOT)}")
        except ValueError:
            print(f"  ファイル: {output_path}")
        print(f"  時間:     {elapsed:.1f}秒")
    else:
        print("  ショートループ動画生成: 失敗")
        print("  --prompt でプロンプトを変えて再試行してください。")
    print("===========================================")
    print()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
