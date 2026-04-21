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
import sys
import time
from pathlib import Path


# --- パス解決 ---
def _channel_root() -> Path:
    from youtube_automation.utils.config import channel_dir

    return channel_dir()


from youtube_automation.utils.exceptions import ConfigError  # noqa: E402
from youtube_automation.utils.image_generator import (  # noqa: E402
    DEFAULT_IMAGE_SIZE,
    DEFAULT_MODEL,
    VALID_IMAGE_SIZES,
    apply_composition_rules,
    confirm_cost,
    generate_image,
    load_gemini_config,
    print_cost_summary,
    resolve_unique_path,
)


def main():
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv())

    parser = argparse.ArgumentParser(description="Gemini API で画像を生成（ダイレクトモード）")
    parser.add_argument("--prompt", type=str, default=None, help="プロンプトテキスト")
    parser.add_argument("--output", type=str, default=None, help="出力パス")
    parser.add_argument("-y", "--yes", action="store_true", help="コスト確認をスキップ")
    parser.add_argument("--model", type=str, default=None, help="使用するモデル（例: gemini-3.1-flash-image-preview）")
    parser.add_argument(
        "--reference",
        type=str,
        action="append",
        default=None,
        help="参照画像パス（複数指定可。複数指定時はスタイルブレンド/合成）",
    )
    parser.add_argument("--aspect-ratio", type=str, default="16:9", help="アスペクト比（例: 16:9, 9:16, 1:1）")
    parser.add_argument(
        "--size",
        type=str,
        choices=list(VALID_IMAGE_SIZES),
        default=DEFAULT_IMAGE_SIZE,
        help=f"画像解像度 {VALID_IMAGE_SIZES} （デフォルト: {DEFAULT_IMAGE_SIZE}）",
    )
    parser.add_argument("--no-composition", action="store_true", help="composition_prefix の自動付加をスキップ")
    parser.add_argument(
        "--costs",
        action="store_true",
        help="data/image_costs.json から累積コストサマリを表示して終了",
    )
    args = parser.parse_args()

    if args.costs:
        print_cost_summary()
        sys.exit(0)

    if not args.prompt or not args.output:
        parser.error("--prompt と --output は必須です（--costs 単独実行を除く）")

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
    print(f"解像度:       {args.size}")
    if args.reference:
        print(f"参照画像:     {', '.join(args.reference)}")

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

    try:
        from youtube_automation.utils.genai_client import create_genai_client
    except ImportError:
        print("[ERROR] google-genai がインストールされていません。")
        print("  pip3 install google-genai Pillow --break-system-packages")
        sys.exit(1)

    # 参照画像解決（複数対応）
    reference_images: list[Path] = []
    for raw_ref in args.reference or []:
        ref_path = Path(raw_ref)
        if not ref_path.is_absolute():
            ref_path = Path.cwd() / ref_path
        if not ref_path.exists():
            print(f"[ERROR] 参照画像が見つかりません: {ref_path}")
            sys.exit(1)
        reference_images.append(ref_path)

    # 生成実行
    try:
        client = create_genai_client()
    except ConfigError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)
    start_time = time.monotonic()
    success = generate_image(
        client,
        prompt,
        model,
        output_path,
        reference_image=reference_images or None,
        aspect_ratio=args.aspect_ratio,
        image_size=args.size,
        cost_per_image_usd=cost_per_image,
    )
    elapsed = time.monotonic() - start_time

    # レポート
    print()
    print("===========================================")
    if success:
        print("  画像生成: 完了")
        try:
            print(f"  ファイル: {output_path.relative_to(_channel_root())}")
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
