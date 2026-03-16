#!/usr/bin/env python3
"""Gemini API 経由で画像を生成する汎用スクリプト（ダイレクトモード）。

プロンプトテキストと出力パスを直接指定して画像生成。
workflow-state.json には触れない。

Usage:
    python3 generate_image.py --prompt "A mystical forest..." --output /tmp/preview.png -y
    python3 generate_image.py --prompt "Celtic harp in moonlight" --output previews/plan-a.png
    python3 generate_image.py --prompt "..." --output out.png --reference ref.png -y
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
from utils.image_generator import (  # noqa: E402
    DEFAULT_MODEL,
    apply_composition_rules,
    confirm_cost,
    generate_image,
    load_gemini_config,
    resolve_unique_path,
)


def main():
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv())

    parser = argparse.ArgumentParser(description="Gemini API で画像を生成（ダイレクトモード）")
    parser.add_argument("--prompt", type=str, required=True, help="プロンプトテキスト")
    parser.add_argument("--output", type=str, required=True, help="出力パス")
    parser.add_argument("-y", "--yes", action="store_true", help="コスト確認をスキップ")
    parser.add_argument("--model", type=str, default=None, help="使用するモデル（例: gemini-3.1-flash-image-preview）")
    parser.add_argument(
        "--reference", type=str, default=None, help="参照画像パス（main.png等）。画像+プロンプトで Gemini に送信"
    )
    parser.add_argument(
        "--aspect-ratio", type=str, default="16:9", help="アスペクト比（例: 16:9, 9:16, 1:1）"
    )
    parser.add_argument(
        "--no-composition", action="store_true", help="composition_prefix の自動付加をスキップ"
    )
    args = parser.parse_args()

    config = load_gemini_config()
    if args.no_composition or args.reference:
        prompt = args.prompt
    else:
        prompt = apply_composition_rules(args.prompt, config)
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = Path.cwd() / output_path

    model = args.model or config.get("model", DEFAULT_MODEL)
    cost_per_image = config.get("cost_per_image_usd", 0.04)

    print("\nモード:       ダイレクト")
    print(f"プロンプト:   {prompt[:80]}{'...' if len(prompt) > 80 else ''}")
    print(f"出力先:       {output_path}")
    if args.reference:
        print(f"参照画像:     {args.reference}")

    # 既存ファイル確認
    if output_path.exists() and output_path.stat().st_size > 0:
        if args.yes:
            original = output_path
            output_path = resolve_unique_path(output_path)
            if output_path != original:
                print(f"\n[INFO] 既存ファイルあり → 自動採番: {output_path.name}")
        else:
            print(f"\n[INFO] 既存ファイルが見つかりました: {output_path.name} ({output_path.stat().st_size:,} bytes)")
            try:
                answer = input("上書きしますか? (y/N): ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n中止しました。")
                sys.exit(0)
            if answer not in ("y", "yes"):
                print("中止しました。")
                sys.exit(0)

    # コスト確認
    if not args.yes:
        if not confirm_cost(model, cost_per_image):
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
        print("  pip3 install google-genai Pillow --break-system-packages")
        sys.exit(1)

    # 参照画像解決
    reference_image = None
    if args.reference:
        reference_image = Path(args.reference)
        if not reference_image.is_absolute():
            reference_image = Path.cwd() / reference_image
        if not reference_image.exists():
            print(f"[ERROR] 参照画像が見つかりません: {reference_image}")
            sys.exit(1)

    # 生成実行
    client = genai.Client()
    start_time = time.monotonic()
    success = generate_image(client, prompt, model, output_path, reference_image=reference_image, aspect_ratio=args.aspect_ratio)
    elapsed = time.monotonic() - start_time

    # レポート
    print()
    print("===========================================")
    if success:
        print("  画像生成: 完了")
        try:
            print(f"  ファイル: {output_path.relative_to(REPO_ROOT)}")
        except ValueError:
            print(f"  ファイル: {output_path}")
        print(f"  コスト:   ${cost_per_image:.3f}")
        print(f"  時間:     {elapsed:.1f}秒")
    else:
        print("  画像生成: 失敗")
        print("  プロンプトを調整して再試行してください。")
    print("===========================================")
    print()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
