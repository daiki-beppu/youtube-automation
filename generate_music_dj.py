#!/usr/bin/env python3
"""Lyria DJ Engine — composition.json 駆動のフェーズ展開音楽生成。"""

import argparse
import asyncio
import base64
import json
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


def load_composition(path: Path) -> dict:
    """composition.json を読み込みバリデーションする。"""
    with open(path) as f:
        comp = json.load(f)

    for key in ("title", "total_duration_min", "base", "phases"):
        if key not in comp:
            print(f"[ERROR] composition.json に '{key}' がありません")
            sys.exit(1)

    if not comp["phases"]:
        print("[ERROR] phases が空です")
        sys.exit(1)

    comp["phases"].sort(key=lambda p: p["at_min"])

    if comp["phases"][0]["at_min"] != 0:
        print("[ERROR] 最初の phase は at_min=0 である必要があります")
        sys.exit(1)

    comp.setdefault("transition_sec", 30)

    if "prompt_prefix" not in comp["base"]:
        print("[ERROR] base.prompt_prefix が必要です")
        sys.exit(1)

    return comp


def format_time(minutes: float) -> str:
    """分を mm:ss 形式に変換。"""
    m = int(minutes)
    s = int((minutes - m) * 60)
    return f"{m:02d}:{s:02d}"


def dry_run(comp: dict) -> None:
    """タイムラインを表示して終了。"""
    title = comp["title"]
    total = comp["total_duration_min"]
    trans = comp["transition_sec"]
    base = comp["base"]

    print(f"\n=== {title} ({total}min) ===")
    print(f"  Base: bpm={base.get('bpm', 'auto')} brightness={base.get('brightness', 'auto')}"
          f" mode={base.get('mode', 'QUALITY')}")
    print(f"  Transition: {trans}s crossfade")
    print()

    for i, phase in enumerate(comp["phases"]):
        at = phase["at_min"]
        name = phase["name"]
        overrides = {k: v for k, v in phase.items() if k not in ("at_min", "name", "prompt")}
        override_str = "  ".join(f"{k}={v}" for k, v in overrides.items()) if overrides else ""

        if i > 0:
            trans_start = at - trans / 120
            print(f"  {format_time(trans_start)}  ── transition ({trans}s) ──")

        print(f"  {format_time(at)}  {name:<20s} {override_str}")

    print(f"  {format_time(total)}  END")
    print()


def build_timeline(comp: dict) -> list[dict]:
    """composition からトランジションイベントのタイムラインを構築する。"""
    events = []
    phases = comp["phases"]
    trans_sec = comp["transition_sec"]
    half_trans = trans_sec / 2

    events.append({"at_sec": 0, "type": "phase", "phase_idx": 0})

    for i in range(1, len(phases)):
        at_sec = phases[i]["at_min"] * 60
        events.append({
            "at_sec": at_sec - half_trans,
            "type": "transition_start",
            "from_idx": i - 1,
            "to_idx": i,
        })
        events.append({
            "at_sec": at_sec + half_trans,
            "type": "transition_end",
            "phase_idx": i,
        })

    return events


def build_prompt(comp: dict, phase: dict) -> str:
    """base.prompt_prefix + phase.prompt を結合。"""
    return f"{comp['base']['prompt_prefix']}, {phase['prompt']}"


def build_config_for_phase(types, comp: dict, phase: dict):
    """base + phase オーバーライドから LiveMusicGenerationConfig を構築。"""
    base = comp["base"]
    kwargs = {}
    for key in ("bpm", "brightness", "density", "guidance", "temperature"):
        val = phase.get(key, base.get(key))
        if val is not None:
            kwargs[key] = val
    mode = phase.get("mode", base.get("mode", "QUALITY"))
    if mode != "QUALITY":
        kwargs["music_generation_mode"] = mode
    if kwargs:
        return types.LiveMusicGenerationConfig(**kwargs)
    return None


def write_wav(pcm_data: bytes, output: Path) -> None:
    """PCM データを WAV ファイルに書き出す。"""
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm_data)


async def generate_dj(client, types, comp: dict) -> bytes | None:
    """Lyria RealTime API でフェーズ展開 DJ 生成を行い、PCM データを返す。"""
    phases = comp["phases"]
    total_sec = comp["total_duration_min"] * 60
    trans_sec = comp["transition_sec"]
    timeline = build_timeline(comp)
    pcm_data = bytearray()

    try:
        warnings.filterwarnings("ignore", message="Realtime music generation is experimental")
        async with client.aio.live.music.connect(model=MODEL) as session:
            # 初期フェーズ設定
            initial_prompt = build_prompt(comp, phases[0])
            await session.set_weighted_prompts(
                prompts=[types.WeightedPrompt(text=initial_prompt, weight=1.0)]
            )

            config = build_config_for_phase(types, comp, phases[0])
            if config:
                await session.set_music_generation_config(config=config)

            await session.play()
            print(f"\n  [生成開始] {phases[0]['name']}")

            start = time.monotonic()
            last_report = 0
            event_idx = 1  # skip event 0 (initial phase)
            current_phase_name = phases[0]["name"]

            # Transition state
            in_transition = False
            trans_from_prompt = ""
            trans_to_prompt = ""
            trans_start_time = 0.0
            last_weight_update = 0.0

            async for message in session.receive():
                elapsed = time.monotonic() - start
                if elapsed >= total_sec:
                    break

                # Collect audio
                if message.server_content and message.server_content.audio_chunks:
                    chunk = message.server_content.audio_chunks[0].data
                    if isinstance(chunk, str):
                        pcm_data.extend(base64.b64decode(chunk))
                    else:
                        pcm_data.extend(chunk)

                # Process timeline events
                while event_idx < len(timeline) and elapsed >= timeline[event_idx]["at_sec"]:
                    ev = timeline[event_idx]

                    if ev["type"] == "transition_start":
                        in_transition = True
                        trans_from_prompt = build_prompt(comp, phases[ev["from_idx"]])
                        trans_to_prompt = build_prompt(comp, phases[ev["to_idx"]])
                        trans_start_time = ev["at_sec"]
                        last_weight_update = elapsed
                        from_name = phases[ev['from_idx']]['name']
                        to_name = phases[ev['to_idx']]['name']
                        print(f"\n  [{format_time(elapsed / 60)}] transition: {from_name} -> {to_name}")

                    elif ev["type"] == "transition_end":
                        in_transition = False
                        current_phase_name = phases[ev["phase_idx"]]["name"]
                        # Apply new phase config
                        new_config = build_config_for_phase(types, comp, phases[ev["phase_idx"]])
                        if new_config:
                            await session.set_music_generation_config(config=new_config)
                        # Set full weight to new prompt
                        await session.set_weighted_prompts(
                            prompts=[types.WeightedPrompt(text=trans_to_prompt, weight=1.0)]
                        )
                        print(f"\n  [{format_time(elapsed / 60)}] phase: {current_phase_name}")

                    event_idx += 1

                # Update crossfade weights during transition (every ~1 second)
                if in_transition and (elapsed - last_weight_update) >= 1.0:
                    last_weight_update = elapsed
                    progress = min(1.0, (elapsed - trans_start_time) / trans_sec)
                    old_w = round(1.0 - progress, 2)
                    new_w = round(progress, 2)
                    await session.set_weighted_prompts(
                        prompts=[
                            types.WeightedPrompt(text=trans_from_prompt, weight=old_w),
                            types.WeightedPrompt(text=trans_to_prompt, weight=new_w),
                        ]
                    )

                # Progress every 10 seconds
                if int(elapsed) - last_report >= 10:
                    last_report = int(elapsed)
                    m, s = divmod(int(elapsed), 60)
                    total_m, total_s = divmod(int(total_sec), 60)
                    phase_label = f" ({current_phase_name})" if not in_transition else " (transition)"
                    print(f"\r  [生成中] {m}:{s:02d} / {total_m}:{total_s:02d}{phase_label}", end="", flush=True)

            await session.stop()
            print("\n  [生成完了]")

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


def main():
    try:
        from dotenv import find_dotenv, load_dotenv
        load_dotenv(find_dotenv())
    except ImportError:
        pass

    parser = argparse.ArgumentParser(
        description="Lyria DJ Engine — composition.json 駆動の音楽生成",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-c", "--composition", required=True, help="composition.json パス")
    parser.add_argument("-o", "--output", default="master.wav", help="出力 WAV パス (default: master.wav)")
    parser.add_argument("-y", "--yes", action="store_true", help="確認スキップ")
    parser.add_argument("--dry-run", action="store_true", help="タイムライン表示のみ")
    args = parser.parse_args()

    comp_path = Path(args.composition).resolve()
    if not comp_path.exists():
        print(f"[ERROR] {comp_path} が見つかりません")
        sys.exit(1)

    comp = load_composition(comp_path)

    if args.dry_run:
        dry_run(comp)
        sys.exit(0)

    # Show timeline as confirmation
    dry_run(comp)

    if not args.yes:
        try:
            answer = input("続行しますか? (y/N): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n中止しました。")
            sys.exit(0)
        if answer not in ("y", "yes"):
            print("中止しました。")
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
    output = Path(args.output).resolve()
    start_time = time.monotonic()

    pcm_data = asyncio.run(generate_dj(client, types, comp))

    gen_elapsed = time.monotonic() - start_time

    if pcm_data is None:
        print("\n音楽生成に失敗しました。")
        sys.exit(1)

    write_wav(pcm_data, output)

    actual_duration = len(pcm_data) / (SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH)
    size_mb = output.stat().st_size / (1024 * 1024)
    m, s = divmod(int(actual_duration), 60)

    print()
    print("===========================================")
    print(f"  DJ 生成: 完了 — {comp['title']}")
    print(f"  ファイル:   {output}")
    print(f"  時間:       {int(actual_duration)}秒 ({m}:{s:02d})")
    print(f"  サイズ:     {size_mb:.1f} MB")
    print(f"  フェーズ数: {len(comp['phases'])}")
    print(f"  生成時間:   {int(gen_elapsed)}秒")
    print("===========================================")


if __name__ == "__main__":
    main()
