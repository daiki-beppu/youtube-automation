#!/usr/bin/env python3
"""Lyria RealTime API 経由で音楽を生成する。

Usage:
    python3 generate_music.py --prompt "Calm Celtic harp melody" -o output.wav -d 120
    python3 generate_music.py --prompt "Epic orchestral battle theme" -d 60 --bpm 140 -y
    python3 generate_music.py -p "Peaceful piano meditation" -o meditation.wav -d 300 --brightness 0.3 -y
"""

import argparse
import asyncio
import base64
import os
import sys
import time
import warnings
import wave
from pathlib import Path

SAMPLE_RATE = 48000
CHANNELS = 2
SAMPLE_WIDTH = 2  # 16-bit
MODEL = "models/lyria-realtime-exp"


def validate_args(args):
    """CLI 引数の範囲チェック。"""
    errors = []
    if args.duration < 1:
        errors.append("--duration は 1 以上を指定してください")
    if args.bpm is not None and not (60 <= args.bpm <= 200):
        errors.append("--bpm は 60〜200 の範囲で指定してください")
    if args.guidance is not None and not (0.0 <= args.guidance <= 6.0):
        errors.append("--guidance は 0.0〜6.0 の範囲で指定してください")
    if args.density is not None and not (0.0 <= args.density <= 1.0):
        errors.append("--density は 0.0〜1.0 の範囲で指定してください")
    if args.brightness is not None and not (0.0 <= args.brightness <= 1.0):
        errors.append("--brightness は 0.0〜1.0 の範囲で指定してください")
    if errors:
        for e in errors:
            print(f"[ERROR] {e}")
        sys.exit(1)


def confirm_generation(args) -> bool:
    """生成設定を表示し確認を求める。"""
    print()
    print("=== Lyria Music Generation ===")
    print(f"  モデル:       {MODEL}")
    print(f"  プロンプト:   {args.prompt}")
    print(f"  時間:         {args.duration}秒")
    print(f"  出力先:       {args.output}")
    print(f"  モード:       {args.mode}")
    if args.bpm is not None:
        print(f"  BPM:          {args.bpm}")
    if args.guidance is not None:
        print(f"  ガイダンス:   {args.guidance}")
    if args.density is not None:
        print(f"  密度:         {args.density}")
    if args.brightness is not None:
        print(f"  明るさ:       {args.brightness}")
    if args.temperature is not None:
        print(f"  温度:         {args.temperature}")
    print()
    try:
        answer = input("続行しますか? (y/N): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n中止しました。")
        return False
    return answer in ("y", "yes")


def build_music_config(types, args):
    """CLI 引数から LiveMusicGenerationConfig を構築する。"""
    kwargs = {}
    if args.bpm is not None:
        kwargs["bpm"] = args.bpm
    if args.guidance is not None:
        kwargs["guidance"] = args.guidance
    if args.density is not None:
        kwargs["density"] = args.density
    if args.brightness is not None:
        kwargs["brightness"] = args.brightness
    if args.temperature is not None:
        kwargs["temperature"] = args.temperature
    if args.mode != "QUALITY":
        kwargs["music_generation_mode"] = args.mode
    if not kwargs:
        return None
    return types.LiveMusicGenerationConfig(**kwargs)


async def generate_music(client, types, prompt: str, duration: int, args) -> bytes | None:
    """Lyria RealTime API で音楽を生成し、PCM データを返す。"""
    pcm_data = bytearray()

    try:
        warnings.filterwarnings("ignore", message="Realtime music generation is experimental")
        async with client.aio.live.music.connect(model=MODEL) as session:
            await session.set_weighted_prompts(
                prompts=[types.WeightedPrompt(text=prompt, weight=1.0)]
            )

            config = build_music_config(types, args)
            if config:
                await session.set_music_generation_config(config=config)

            await session.play()
            print("\n  [生成開始]")

            start = time.monotonic()
            last_report = 0

            async for message in session.receive():
                elapsed = time.monotonic() - start
                if elapsed >= duration:
                    break

                if message.server_content and message.server_content.audio_chunks:
                    chunk = message.server_content.audio_chunks[0].data
                    if isinstance(chunk, str):
                        pcm_data.extend(base64.b64decode(chunk))
                    else:
                        pcm_data.extend(chunk)

                # 5秒ごとに進捗表示
                if int(elapsed) - last_report >= 5:
                    last_report = int(elapsed)
                    pct = min(100, int(elapsed / duration * 100))
                    print(f"\r  [生成中] {int(elapsed)}秒 / {duration}秒 ({pct}%)", end="", flush=True)

            await session.stop()
            print(f"\r  [生成中] {duration}秒 / {duration}秒 (100%)")

    except KeyboardInterrupt:
        print("\n\n  [中断] Ctrl+C を検出。収集済みデータを保存します。")
    except ConnectionError as e:
        print(f"\n[ERROR] 接続エラー: {e}")
        print("  ネットワーク接続と API キーを確認してください。")
        return None
    except Exception as e:
        print(f"\n[ERROR] 生成中にエラーが発生: {e}")
        return None

    if not pcm_data:
        print("\n[ERROR] 音声データを受信できませんでした。")
        return None

    return bytes(pcm_data)


def write_wav(pcm_data: bytes, output: Path) -> None:
    """PCM データを WAV ファイルに書き出す。"""
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm_data)


def format_duration(seconds: float) -> str:
    """秒数を m:ss 形式にフォーマット。"""
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def main():
    try:
        from dotenv import find_dotenv, load_dotenv
        load_dotenv(find_dotenv())
    except ImportError:
        pass

    parser = argparse.ArgumentParser(
        description="Lyria RealTime API で音楽を生成",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="例: python3 generate_music.py -p 'Celtic harp melody' -d 60 -o output.wav -y",
    )
    parser.add_argument("--prompt", "-p", required=True, help="音楽の説明テキスト")
    parser.add_argument("--output", "-o", default="output.wav", help="出力 WAV ファイルパス (default: output.wav)")
    parser.add_argument("--duration", "-d", type=int, default=60, help="生成時間（秒） (default: 60)")
    parser.add_argument("--bpm", type=int, default=None, help="BPM (60-200)")
    parser.add_argument("--guidance", type=float, default=None, help="ガイダンス値 (0.0-6.0)")
    parser.add_argument("--density", type=float, default=None, help="密度 (0.0-1.0)")
    parser.add_argument("--brightness", type=float, default=None, help="明るさ (0.0-1.0)")
    parser.add_argument("--temperature", type=float, default=None, help="温度パラメータ")
    parser.add_argument(
        "--mode", choices=["QUALITY", "DIVERSITY"], default="QUALITY", help="生成モード (default: QUALITY)",
    )
    parser.add_argument("-y", "--yes", action="store_true", help="確認をスキップ")
    args = parser.parse_args()

    validate_args(args)

    output = Path(args.output).resolve()

    if output.exists() and not args.yes:
        try:
            answer = input(f"  {output} は既に存在します。上書きしますか? (y/N): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n中止しました。")
            sys.exit(0)
        if answer not in ("y", "yes"):
            print("中止しました。")
            sys.exit(0)

    if not args.yes:
        if not confirm_generation(args):
            sys.exit(0)

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("[ERROR] GEMINI_API_KEY 環境変数が設定されていません。")
        print("  export GEMINI_API_KEY='your-api-key'")
        sys.exit(1)

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("[ERROR] google-genai がインストールされていません。")
        print("  uv pip install google-genai")
        sys.exit(1)

    client = genai.Client(http_options={"api_version": "v1alpha"})
    start_time = time.monotonic()

    pcm_data = asyncio.run(generate_music(client, types, args.prompt, args.duration, args))

    elapsed = time.monotonic() - start_time

    if pcm_data is None:
        print("\n音楽生成に失敗しました。")
        sys.exit(1)

    write_wav(pcm_data, output)

    actual_duration = len(pcm_data) / (SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH)
    size_mb = output.stat().st_size / (1024 * 1024)

    print()
    print("===========================================")
    print("  音楽生成: 完了")
    print(f"  ファイル: {output}")
    print(f"  時間:     {actual_duration:.1f}秒 ({format_duration(actual_duration)})")
    print(f"  サイズ:   {size_mb:.1f} MB")
    print(f"  生成時間: {elapsed:.1f}秒")
    print("===========================================")


if __name__ == "__main__":
    main()
