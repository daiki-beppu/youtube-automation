#!/usr/bin/env python3
"""Lyria 3 API 経由で音楽を生成する。

Usage:
    python3 generate_music.py --prompt "Calm jazz piano melody" -o output.wav
    python3 generate_music.py --prompt "Epic orchestral piece" -o output.wav --model lyria-3-clip-preview
    python3 generate_music.py -p "Peaceful piano meditation" -o meditation.wav -y
"""

import argparse
import sys
import time
from pathlib import Path

from youtube_automation.utils import cost_tracker, lyria_client
from youtube_automation.utils.exceptions import ConfigError


def main():
    try:
        from dotenv import find_dotenv, load_dotenv

        load_dotenv(find_dotenv())
    except ImportError:
        pass

    parser = argparse.ArgumentParser(
        description="Lyria 3 API で音楽を生成",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="例: python3 generate_music.py -p 'smooth jazz piano' -o output.wav -y",
    )
    parser.add_argument("--prompt", "-p", required=True, help="音楽の説明テキスト")
    parser.add_argument("--output", "-o", default="output.mp3", help="出力ファイルパス (default: output.mp3)")
    parser.add_argument(
        "--model",
        "-m",
        default="lyria-3-pro-preview",
        choices=["lyria-3-pro-preview", "lyria-3-clip-preview"],
        help="モデル (default: lyria-3-pro-preview, clip は 30 秒固定)",
    )
    parser.add_argument("-y", "--yes", action="store_true", help="確認をスキップ")
    args = parser.parse_args()

    output = Path(args.output).resolve()

    if not args.yes:
        print()
        print("=== Lyria 3 Music Generation ===")
        print(f"  モデル:     {args.model}")
        print(f"  プロンプト: {args.prompt}")
        print(f"  出力先:     {output}")
        print()
        try:
            answer = input("続行しますか? (y/N): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n中止しました。")
            sys.exit(0)
        if answer not in ("y", "yes"):
            print("中止しました。")
            sys.exit(0)

    print("\n  [生成中]...", end="", flush=True)
    start_time = time.monotonic()

    try:
        audio_data = lyria_client.generate_music(args.prompt, args.model)
    except ConfigError as e:
        print(f"\n[ERROR] {e}")
        sys.exit(1)

    elapsed = time.monotonic() - start_time

    if audio_data is None:
        print("\n音楽生成に失敗しました。")
        sys.exit(1)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(audio_data)

    size_mb = output.stat().st_size / (1024 * 1024)

    print("\r  [生成完了]    ")
    print()
    print("===========================================")
    print("  音楽生成: 完了")
    print(f"  ファイル: {output}")
    print(f"  サイズ:   {size_mb:.1f} MB")
    print(f"  生成時間: {elapsed:.1f}秒")
    print("===========================================")

    entry = cost_tracker.log_generation(
        "audio",
        model=args.model,
        quantity=1,
        metadata={
            "prompt_preview": args.prompt[:120],
            "output_file": cost_tracker.relative_to_channel_dir(output),
            "elapsed_sec": round(elapsed, 1),
        },
    )
    cost_tracker.print_last_report(entry)


if __name__ == "__main__":
    main()
