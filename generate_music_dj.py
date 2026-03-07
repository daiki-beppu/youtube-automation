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
CHECKPOINT_INTERVAL_SEC = 300  # 5分ごとに中間保存
CROSSFADE_SAMPLES = SAMPLE_RATE * 5  # 結合時の5秒クロスフェード


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


def build_segment_compositions(comp: dict) -> list[dict]:
    """composition を phase 境界でセグメント分割し、各セグメント用の部分 composition を返す。"""
    phases = comp["phases"]
    total_min = comp["total_duration_min"]
    segments = []

    for i, phase in enumerate(phases):
        if i + 1 < len(phases):
            duration_min = phases[i + 1]["at_min"] - phase["at_min"]
        else:
            duration_min = total_min - phase["at_min"]

        seg_comp = {
            "title": f"{comp['title']} [{i+1}/{len(phases)}] {phase['name']}",
            "total_duration_min": duration_min,
            "base": comp["base"],
            "phases": [dict(phase, at_min=0)],
            "transition_sec": comp["transition_sec"],
        }
        segments.append(seg_comp)

    return segments


async def generate_segmented(client, types, comp: dict, output: Path,
                             max_retries: int = 3) -> bytes | None:
    """phase 境界でセグメント分割し、各セグメントを個別セッションで生成→結合する。"""
    segments = build_segment_compositions(comp)
    seg_dir = output.parent
    seg_paths = [seg_dir / f"seg_{i+1:03d}.wav" for i in range(len(segments))]

    print(f"\n=== セグメント分割生成 ({len(segments)} segments) ===")
    for i, seg in enumerate(segments):
        dur = seg["total_duration_min"]
        print(f"  seg_{i+1:03d}: {seg['phases'][0]['name']} ({dur:.1f}min)")

    # 各セグメントを生成
    for i, (seg_comp, seg_path) in enumerate(zip(segments, seg_paths)):
        # 既存セグメントはスキップ
        if seg_path.exists():
            dur = pcm_duration_sec(read_wav_pcm(seg_path))
            print(f"\n  [skip] seg_{i+1:03d} ({format_time(dur / 60)}) — 既に存在")
            continue

        print(f"\n{'='*40}")
        print(f"  セグメント {i+1}/{len(segments)}: {seg_comp['phases'][0]['name']}")
        print(f"{'='*40}")

        success = False
        for attempt in range(max_retries + 1):
            if attempt > 0:
                print(f"\n  [retry {attempt}/{max_retries}] seg_{i+1:03d}")

            pcm = await generate_dj(client, types, seg_comp, seg_path)
            if pcm is not None:
                write_wav(pcm, seg_path)
                print(f"  [saved] seg_{i+1:03d} ({format_time(pcm_duration_sec(pcm) / 60)})")
                success = True
                break

        if not success:
            print(f"\n[ERROR] seg_{i+1:03d} が {max_retries + 1} 回失敗しました。")
            print("  成功済みセグメントは保持されています。再実行で続行できます。")
            return None

    # 全セグメントをクロスフェード結合
    print(f"\n=== 結合中 ({len(segments)} segments) ===")
    combined = read_wav_pcm(seg_paths[0])
    for i in range(1, len(seg_paths)):
        next_pcm = read_wav_pcm(seg_paths[i])
        combined = crossfade_join(combined, next_pcm)
        print(f"  joined: seg_{i:03d} + seg_{i+1:03d} -> {format_time(pcm_duration_sec(combined) / 60)}")

    write_wav(combined, output)

    # セグメントファイルを削除
    for seg_path in seg_paths:
        if seg_path.exists():
            seg_path.unlink()

    return combined


def read_wav_pcm(path: Path) -> bytes:
    """WAV ファイルから PCM データを読み込む。"""
    with wave.open(str(path), "rb") as wf:
        return wf.readframes(wf.getnframes())


def pcm_duration_sec(pcm_data: bytes | bytearray) -> float:
    """PCM データの再生時間（秒）を計算。"""
    return len(pcm_data) / (SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH)


def crossfade_join(pcm_a: bytes, pcm_b: bytes, fade_samples: int = CROSSFADE_SAMPLES) -> bytes:
    """2つの PCM データをクロスフェードで結合する。"""
    import struct

    bytes_per_sample = CHANNELS * SAMPLE_WIDTH
    fade_bytes = fade_samples * bytes_per_sample

    if len(pcm_a) < fade_bytes or len(pcm_b) < fade_bytes:
        return pcm_a + pcm_b

    head = pcm_a[:-fade_bytes]
    overlap_a = pcm_a[-fade_bytes:]
    overlap_b = pcm_b[:fade_bytes]
    tail = pcm_b[fade_bytes:]

    mixed = bytearray(fade_bytes)
    num_values = fade_bytes // SAMPLE_WIDTH
    fmt = f"<{num_values}h"

    samples_a = struct.unpack(fmt, overlap_a)
    samples_b = struct.unpack(fmt, overlap_b)

    result = []
    samples_per_channel = num_values // CHANNELS if CHANNELS > 1 else num_values
    for i in range(num_values):
        progress = (i // CHANNELS) / max(1, samples_per_channel - 1)
        val = int(samples_a[i] * (1.0 - progress) + samples_b[i] * progress)
        val = max(-32768, min(32767, val))
        result.append(val)

    mixed = struct.pack(fmt, *result)
    return head + mixed + tail


def find_phase_at(comp: dict, elapsed_sec: float) -> int:
    """指定秒数時点でのフェーズインデックスを返す。"""
    phases = comp["phases"]
    idx = 0
    for i, p in enumerate(phases):
        if p["at_min"] * 60 <= elapsed_sec:
            idx = i
    return idx


async def generate_dj(client, types, comp: dict, output: Path,
                      offset_sec: float = 0) -> bytes | None:
    """Lyria RealTime API でフェーズ展開 DJ 生成を行い、PCM データを返す。

    offset_sec > 0 の場合、そのオフセットから生成を開始する（resume 用）。
    途中切断時も収集済みデータを .partial.wav に保存する。
    """
    phases = comp["phases"]
    total_sec = comp["total_duration_min"] * 60
    trans_sec = comp["transition_sec"]
    timeline = build_timeline(comp)
    pcm_data = bytearray()
    partial_path = output.with_suffix(".partial.wav")
    last_checkpoint = 0
    interrupted = False

    # offset_sec に基づいて開始フェーズを決定
    start_phase_idx = find_phase_at(comp, offset_sec)

    # offset 以降の timeline イベントのみ処理
    # (offset 分だけずらして判定)
    event_idx = 0
    for i, ev in enumerate(timeline):
        if ev["at_sec"] > offset_sec:
            event_idx = i
            break
    else:
        event_idx = len(timeline)

    try:
        warnings.filterwarnings("ignore", message="Realtime music generation is experimental")
        async with client.aio.live.music.connect(model=MODEL) as session:
            # 開始フェーズ設定
            initial_prompt = build_prompt(comp, phases[start_phase_idx])
            await session.set_weighted_prompts(
                prompts=[types.WeightedPrompt(text=initial_prompt, weight=1.0)]
            )

            config = build_config_for_phase(types, comp, phases[start_phase_idx])
            if config:
                await session.set_music_generation_config(config=config)

            await session.play()

            if offset_sec > 0:
                print(f"\n  [再開] {phases[start_phase_idx]['name']} (offset {format_time(offset_sec / 60)})")
            else:
                print(f"\n  [生成開始] {phases[start_phase_idx]['name']}")

            start = time.monotonic()
            last_report = 0
            current_phase_name = phases[start_phase_idx]["name"]

            # Transition state
            in_transition = False
            trans_from_prompt = ""
            trans_to_prompt = ""
            trans_start_time = 0.0
            last_weight_update = 0.0

            async for message in session.receive():
                stream_elapsed = time.monotonic() - start
                # 実際の経過時間 = offset + ストリーム内の経過
                virtual_elapsed = offset_sec + stream_elapsed

                if virtual_elapsed >= total_sec:
                    break

                # Collect audio
                if message.server_content and message.server_content.audio_chunks:
                    chunk = message.server_content.audio_chunks[0].data
                    if isinstance(chunk, str):
                        pcm_data.extend(base64.b64decode(chunk))
                    else:
                        pcm_data.extend(chunk)

                # Process timeline events (using virtual_elapsed for correct phase timing)
                while event_idx < len(timeline) and virtual_elapsed >= timeline[event_idx]["at_sec"]:
                    ev = timeline[event_idx]

                    if ev["type"] == "transition_start":
                        in_transition = True
                        trans_from_prompt = build_prompt(comp, phases[ev["from_idx"]])
                        trans_to_prompt = build_prompt(comp, phases[ev["to_idx"]])
                        trans_start_time = ev["at_sec"]
                        last_weight_update = virtual_elapsed
                        from_name = phases[ev['from_idx']]['name']
                        to_name = phases[ev['to_idx']]['name']
                        print(f"\n  [{format_time(virtual_elapsed / 60)}] transition: {from_name} -> {to_name}")

                    elif ev["type"] == "transition_end":
                        in_transition = False
                        current_phase_name = phases[ev["phase_idx"]]["name"]
                        new_config = build_config_for_phase(types, comp, phases[ev["phase_idx"]])
                        if new_config:
                            await session.set_music_generation_config(config=new_config)
                        await session.set_weighted_prompts(
                            prompts=[types.WeightedPrompt(text=trans_to_prompt, weight=1.0)]
                        )
                        print(f"\n  [{format_time(virtual_elapsed / 60)}] phase: {current_phase_name}")

                    event_idx += 1

                # Update crossfade weights during transition
                if in_transition and (virtual_elapsed - last_weight_update) >= 1.0:
                    last_weight_update = virtual_elapsed
                    progress = min(1.0, (virtual_elapsed - trans_start_time) / trans_sec)
                    old_w = round(1.0 - progress, 2)
                    new_w = round(progress, 2)
                    await session.set_weighted_prompts(
                        prompts=[
                            types.WeightedPrompt(text=trans_from_prompt, weight=old_w),
                            types.WeightedPrompt(text=trans_to_prompt, weight=new_w),
                        ]
                    )

                # Progress every 10 seconds
                if int(stream_elapsed) - last_report >= 10:
                    last_report = int(stream_elapsed)
                    m, s = divmod(int(virtual_elapsed), 60)
                    total_m, total_s = divmod(int(total_sec), 60)
                    phase_label = f" ({current_phase_name})" if not in_transition else " (transition)"
                    print(f"\r  [生成中] {m}:{s:02d} / {total_m}:{total_s:02d}{phase_label}", end="", flush=True)

                # Checkpoint: 5分ごとに中間保存
                checkpoint_elapsed = int(stream_elapsed)
                if checkpoint_elapsed > 0 and checkpoint_elapsed - last_checkpoint >= CHECKPOINT_INTERVAL_SEC:
                    last_checkpoint = checkpoint_elapsed
                    write_wav(bytes(pcm_data), partial_path)
                    dur = pcm_duration_sec(pcm_data)
                    print(f"\n  [checkpoint] {format_time(dur / 60)} saved to {partial_path.name}")

            await session.stop()
            print("\n  [生成完了]")

    except KeyboardInterrupt:
        interrupted = True
        print("\n\n  [中断] Ctrl+C を検出。収集済みデータを保存します。")
    except Exception as e:
        interrupted = True
        print(f"\n[ERROR] 生成中にエラーが発生: {e}")

    # 途中切断時もデータがあれば partial に保存
    if interrupted and pcm_data:
        write_wav(bytes(pcm_data), partial_path)
        dur = pcm_duration_sec(pcm_data)
        print(f"  [partial] {format_time(dur / 60)} を {partial_path.name} に保存しました")
        print(f"  再開: --resume {partial_path}")
        return None

    if not pcm_data:
        print("\n[ERROR] 音声データを受信できませんでした。")
        return None

    # 成功時: partial ファイルがあれば削除
    if partial_path.exists():
        partial_path.unlink()

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
    parser.add_argument("--resume", metavar="PARTIAL", help=".partial.wav から再開し、結合する")
    parser.add_argument("--max-retries", type=int, default=0,
                        help="切断時の自動リトライ回数 (default: 0=リトライなし)")
    parser.add_argument("--segmented", action=argparse.BooleanOptionalAction, default=True,
                        help="セグメント分割生成 (default: 有効、--no-segmented で無効)")
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
    partial_path = output.with_suffix(".partial.wav")
    max_retries = args.max_retries

    # Resume モード: 初期 partial の読み込み
    accumulated_pcm = None
    offset_sec = 0.0
    if args.resume:
        resume_path = Path(args.resume).resolve()
        if not resume_path.exists():
            print(f"[ERROR] {resume_path} が見つかりません")
            sys.exit(1)
        accumulated_pcm = read_wav_pcm(resume_path)
        offset_sec = pcm_duration_sec(accumulated_pcm)
        total_sec = comp["total_duration_min"] * 60
        remaining = total_sec - offset_sec
        print(f"\n  [resume] {format_time(offset_sec / 60)} の partial を読み込み")
        print(f"  [resume] 残り {format_time(remaining / 60)} を生成します")

    start_time = time.monotonic()
    attempt = 0

    if args.segmented and not args.resume:
        # セグメント分割生成モード（デフォルト）
        pcm_data = asyncio.run(generate_segmented(client, types, comp, output, max_retries=max_retries))
        gen_elapsed = time.monotonic() - start_time
        if pcm_data is None:
            print("\n音楽生成に失敗しました。")
            print("  成功済みセグメントは保持されています。再実行で続行できます。")
            sys.exit(1)
    else:
        # 既存リトライループ（resume モード + --no-segmented 用）
        while True:
            pcm_data = asyncio.run(generate_dj(client, types, comp, output, offset_sec=offset_sec))

            if pcm_data is not None:
                # 成功: accumulated があればクロスフェード結合
                if accumulated_pcm:
                    print(f"\n  [結合] partial ({format_time(offset_sec / 60)}) + "
                          f"new ({format_time(pcm_duration_sec(pcm_data) / 60)}) をクロスフェード結合...")
                    pcm_data = crossfade_join(accumulated_pcm, pcm_data)
                break

            # 失敗: リトライ判定
            attempt += 1
            if attempt > max_retries:
                print("\n音楽生成に失敗しました。")
                if accumulated_pcm or partial_path.exists():
                    print("  partial データは保持されています。再度 --resume で再開できます。")
                sys.exit(1)

            # partial.wav を読み込んで accumulated に結合し、自動リトライ
            if partial_path.exists():
                new_partial = read_wav_pcm(partial_path)
                if accumulated_pcm:
                    accumulated_pcm = crossfade_join(accumulated_pcm, new_partial)
                else:
                    accumulated_pcm = new_partial
                offset_sec = pcm_duration_sec(accumulated_pcm)

            if offset_sec >= comp["total_duration_min"] * 60:
                pcm_data = accumulated_pcm
                break

            wait_sec = min(30, 10 * attempt)
            print(f"\n  [auto-retry] {attempt}/{max_retries} — {wait_sec}秒後にリトライ "
                  f"(offset {format_time(offset_sec / 60)})...")
            time.sleep(wait_sec)

            # partial を上書き保存して再開
            write_wav(accumulated_pcm, partial_path)

        # 完了: partial ファイルを削除
        if partial_path.exists():
            partial_path.unlink()
            print(f"  [cleanup] {partial_path.name} を削除しました")

        gen_elapsed = time.monotonic() - start_time
        write_wav(pcm_data, output)

    actual_duration = pcm_duration_sec(pcm_data)
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
    if attempt > 0:
        print(f"  リトライ:   {attempt}回")
    print("===========================================")


if __name__ == "__main__":
    main()
