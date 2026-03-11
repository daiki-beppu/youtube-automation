#!/usr/bin/env python3
"""Veo 3.1 API 経由で汎用動画を生成する（ダイレクトモード）。

任意の画像を入力として、Veo 3.1 でループ動画を生成する。
コレクション構造に依存しない汎用スクリプト。

Usage:
    python3 generate_veo_video.py --image /path/to/image.png --output /path/to/output.mp4
    python3 generate_veo_video.py --image img.png --output out.mp4 --prompt "gentle wind..."
    python3 generate_veo_video.py --image img.png --output out.mp4 --smooth --crossfade 0.8
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
    DEFAULT_PROMPT,
    generate_loop_video,
    smooth_loop,
)


def main():
    from dotenv import find_dotenv, load_dotenv
    load_dotenv(find_dotenv())

    parser = argparse.ArgumentParser(description="Veo 3.1 汎用動画生成（ダイレクトモード）")
    parser.add_argument("--image", required=True, help="入力画像パス")
    parser.add_argument("--output", required=True, help="出力動画パス")
    parser.add_argument("--prompt", help="動画生成プロンプト")
    parser.add_argument("--model", help="Veo モデル名")
    parser.add_argument("--smooth", action="store_true", help="FFmpeg クロスフェードでループ補正")
    parser.add_argument("--crossfade", type=float, default=0.5, help="クロスフェード秒数 (デフォルト: 0.5)")
    parser.add_argument("-y", "--yes", action="store_true", help="確認をスキップ")
    args = parser.parse_args()

    model = args.model or DEFAULT_MODEL
    prompt = args.prompt or DEFAULT_PROMPT

    image_path = Path(args.image).resolve()
    output_path = Path(args.output).resolve()

    # バリデーション
    if not image_path.exists():
        print(f"[ERROR] 入力画像が見つかりません: {image_path}")
        sys.exit(1)

    # 確認
    print()
    print("===========================================")
    print("  Veo 3.1 動画生成（ダイレクトモード）")
    print("===========================================")
    print(f"  入力:   {image_path}")
    print(f"  出力:   {output_path}")
    print(f"  モデル: {model}")
    print(f"  補正:   {'あり' if args.smooth else 'なし'}")
    print("===========================================")
    print()

    if not args.yes:
        answer = input("  生成しますか？ [y/N] ").strip().lower()
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
    success = generate_loop_video(client, image_path, output_path, model, prompt)

    if success and args.smooth:
        smooth_loop(output_path, args.crossfade)

    elapsed = time.monotonic() - start_time

    # レポート
    print()
    print("===========================================")
    if success:
        print("  動画生成: 完了")
        try:
            print(f"  ファイル: {output_path.relative_to(REPO_ROOT)}")
        except ValueError:
            print(f"  ファイル: {output_path}")
        print(f"  時間:     {elapsed:.1f}秒")
    else:
        print("  動画生成: 失敗")
        print("  --prompt でプロンプトを変えて再試行してください。")
    print("===========================================")
    print()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
