#!/usr/bin/env python3
"""Lyria 3 DJ Engine — composition.json 駆動のフェーズ展開音楽生成。"""

import argparse
import json
import math
import random
import struct
import sys
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from youtube_automation.utils import cost_tracker, lyria_client  # noqa: E402
from youtube_automation.utils.exceptions import ConfigError  # noqa: E402
from youtube_automation.utils.time_utils import format_duration_mmss  # noqa: E402

SAMPLE_RATE = 48000
CHANNELS = 2
SAMPLE_WIDTH = 2  # 16-bit
DEFAULT_MODEL = "lyria-3-pro-preview"
PREVIEW_MODEL = "lyria-3-clip-preview"
DEFAULT_SEGMENT_SEC = 120  # デフォルトのセグメント長（プロンプトで制御可能）
DEFAULT_SHUFFLE_SEGMENT_SEC = 180  # shuffle モード時のデフォルト（3分）


def load_composition(path: Path) -> dict:
    """composition.json を読み込みバリデーションする。"""
    with open(path) as f:
        comp = json.load(f)

    required = ("title", "base", "phases")
    for key in required:
        if key not in comp:
            print(f"[ERROR] composition.json に '{key}' がありません")
            sys.exit(1)

    if not comp["phases"]:
        print("[ERROR] phases が空です")
        sys.exit(1)

    if "prompt_prefix" not in comp["base"]:
        print("[ERROR] base.prompt_prefix が必要です")
        sys.exit(1)

    comp.setdefault("model", DEFAULT_MODEL)
    comp.setdefault("crossfade_sec", 5)
    comp.setdefault("shuffle_passes", 0)

    if comp["shuffle_passes"] > 0:
        # shuffle モード: at_min/total_duration_min は不要
        comp.setdefault("segment_duration_sec", DEFAULT_SHUFFLE_SEGMENT_SEC)
    else:
        # 通常モード: at_min によるタイムライン
        if "total_duration_min" not in comp:
            print("[ERROR] composition.json に 'total_duration_min' がありません")
            sys.exit(1)
        for p in comp["phases"]:
            if "at_min" not in p:
                print("[ERROR] 通常モードでは各 phase に at_min が必要です")
                sys.exit(1)
        comp["phases"].sort(key=lambda p: p["at_min"])
        if comp["phases"][0]["at_min"] != 0:
            print("[ERROR] 最初の phase は at_min=0 である必要があります")
            sys.exit(1)

    return comp


def dry_run(comp: dict) -> None:
    """タイムラインを表示して終了。"""
    title = comp["title"]
    crossfade = comp.get("crossfade_sec", 5)
    base = comp["base"]
    shuffle_passes = comp.get("shuffle_passes", 0)

    if shuffle_passes > 0:
        seg_sec = comp.get("segment_duration_sec", DEFAULT_SHUFFLE_SEGMENT_SEC)
        segments = build_segment_compositions(comp)
        n = len(segments)
        est_min = (n * seg_sec * shuffle_passes) / 60
        print(f"\n=== {title} (SHUFFLE × {shuffle_passes} passes) ===")
        print(f"  Model: {comp.get('model', DEFAULT_MODEL)}")
        print(f"  Base: {base.get('prompt_prefix', '')[:60]}...")
        if base.get("style_hints"):
            print(f"  Style: {base['style_hints']}")
        print(f"  Crossfade: {crossfade}s")
        print(f"  Segment length: {seg_sec}s ({seg_sec // 60}:{seg_sec % 60:02d})")
        print(f"  Unique segments: {n}")
        print(f"  Total occurrences: {n} × {shuffle_passes} = {n * shuffle_passes}")
        print(f"  Estimated master duration: ~{est_min:.0f} min")
        print()
        for i, seg in enumerate(segments):
            print(f"  seg_{i + 1:03d}  {seg['phase_name']:<30s}")
        print()
        return

    total = comp["total_duration_min"]
    print(f"\n=== {title} ({total}min) ===")
    print(f"  Model: {comp.get('model', DEFAULT_MODEL)}")
    print(f"  Base: {base.get('prompt_prefix', '')[:60]}...")
    if base.get("style_hints"):
        print(f"  Style: {base['style_hints']}")
    print(f"  Crossfade: {crossfade}s")
    print()

    segments = build_segment_compositions(comp)
    for i, seg in enumerate(segments):
        print(f"  seg_{i + 1:03d}  {seg['phase_name']:<30s}")
    print(f"\n  Total segments: {len(segments)}")
    print(f"  {format_duration_mmss(total)}  END")
    print()


def build_prompt(comp: dict, phase: dict) -> str:
    """base.prompt_prefix + base.style_hints + phase.prompt を結合。"""
    parts = [comp["base"]["prompt_prefix"]]
    if comp["base"].get("style_hints"):
        parts.append(comp["base"]["style_hints"])
    parts.append(phase["prompt"])
    if phase.get("section_tag"):
        parts.append(phase["section_tag"])
    return ", ".join(parts)


def build_segment_compositions(comp: dict) -> list[dict]:
    """composition を phase 境界でセグメント分割し、長いフェーズは自動サブ分割する。

    shuffle_passes > 0 の場合、各 phase = 1 ユニークセグメントとして扱い、
    at_min/total_duration_min は無視する（後段の generate_shuffled_master で
    シャッフル順に連結される前提）。
    """
    if comp.get("shuffle_passes", 0) > 0:
        return _build_unique_segments(comp)

    phases = comp["phases"]
    total_min = comp["total_duration_min"]
    model = comp.get("model", DEFAULT_MODEL)
    default_seg_sec = 30 if model == PREVIEW_MODEL else DEFAULT_SEGMENT_SEC
    segments = []

    for i, phase in enumerate(phases):
        if i + 1 < len(phases):
            duration_min = phases[i + 1]["at_min"] - phase["at_min"]
        else:
            duration_min = total_min - phase["at_min"]

        duration_sec = duration_min * 60
        seg_len = phase.get("duration_hint_sec", default_seg_sec)
        num_subs = max(1, math.ceil(duration_sec / seg_len))

        prompt = build_prompt(comp, phase)
        phase_name = phase.get("name_en") or phase["name"]

        for sub in range(num_subs):
            sub_label = f"{phase_name} ({sub + 1}/{num_subs})" if num_subs > 1 else phase_name
            sub_prompt = prompt
            if num_subs > 1 and sub > 0:
                sub_prompt += ", continuing with new variations"

            segments.append(
                {
                    "title": f"{comp['title']} [seg_{len(segments) + 1:03d}] {sub_label}",
                    "prompt": sub_prompt,
                    "model": model,
                    "phase_name": sub_label,
                }
            )

    return segments


def _build_unique_segments(comp: dict) -> list[dict]:
    """shuffle モード用: 各 phase = 1 ユニークセグメント。

    duration_hint_sec or comp.segment_duration_sec の長さの単一セグメントとして扱う。
    プロンプトには長さ指示を付加してモデルが想定長を出すよう促す。
    """
    phases = comp["phases"]
    model = comp.get("model", DEFAULT_MODEL)
    default_seg_sec = comp.get("segment_duration_sec", DEFAULT_SHUFFLE_SEGMENT_SEC)
    segments = []

    for phase in phases:
        seg_sec = phase.get("duration_hint_sec", default_seg_sec)
        prompt = build_prompt(comp, phase)
        # 長さヒントをプロンプトに足してモデルに伝える（参考程度）
        prompt = f"{prompt}, approximately {seg_sec} seconds long, full musical arc within this duration"
        phase_name = phase.get("name_en") or phase["name"]
        segments.append(
            {
                "title": f"{comp['title']} [seg_{len(segments) + 1:03d}] {phase_name}",
                "prompt": prompt,
                "model": model,
                "phase_name": phase_name,
            }
        )

    return segments


def write_wav(pcm_data: bytes, output: Path) -> None:
    """PCM データを WAV ファイルに書き出す。"""
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm_data)


def read_wav_pcm(path: Path) -> bytes:
    """WAV ファイルから PCM データを読み込む。"""
    with wave.open(str(path), "rb") as wf:
        return wf.readframes(wf.getnframes())


def pcm_duration_sec(pcm_data: bytes | bytearray) -> float:
    """PCM データの再生時間（秒）を計算。"""
    return len(pcm_data) / (SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH)


def crossfade_join(pcm_a: bytes, pcm_b: bytes, fade_samples: int | None = None) -> bytes:
    """2つの PCM データをクロスフェードで結合する。"""
    if fade_samples is None:
        fade_samples = SAMPLE_RATE * 5

    bytes_per_sample = CHANNELS * SAMPLE_WIDTH
    fade_bytes = fade_samples * bytes_per_sample

    if len(pcm_a) < fade_bytes or len(pcm_b) < fade_bytes:
        return pcm_a + pcm_b

    head = pcm_a[:-fade_bytes]
    overlap_a = pcm_a[-fade_bytes:]
    overlap_b = pcm_b[:fade_bytes]
    tail = pcm_b[fade_bytes:]

    num_values = fade_bytes // SAMPLE_WIDTH
    fmt = f"<{num_values}h"

    samples_a = struct.unpack(fmt, overlap_a)
    samples_b = struct.unpack(fmt, overlap_b)

    samples_per_channel = num_values // CHANNELS if CHANNELS > 1 else num_values
    result = []
    for i in range(num_values):
        progress = (i // CHANNELS) / max(1, samples_per_channel - 1)
        val = int(samples_a[i] * (1.0 - progress) + samples_b[i] * progress)
        val = max(-32768, min(32767, val))
        result.append(val)

    mixed = struct.pack(fmt, *result)
    return head + mixed + tail


def generate_segment(prompt: str, model: str) -> bytes | None:
    """Lyria 3 API で1セグメントを生成し、オーディオバイトを返す。"""
    return lyria_client.generate_music(prompt, model)


def _save_audio_as_wav(data: bytes, path: Path) -> None:
    """API レスポンスのオーディオデータを WAV に変換して保存する。

    Lyria 3 は MP3 を返すため、ffmpeg で PCM WAV (48kHz, 16-bit, stereo) に変換する。
    """
    import subprocess

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_bytes(data)

    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(tmp_path),
                "-ar",
                str(SAMPLE_RATE),
                "-ac",
                str(CHANNELS),
                "-sample_fmt",
                "s16",
                "-f",
                "wav",
                str(path),
            ],
            capture_output=True,
            check=True,
        )
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def _generate_one_segment(i: int, seg: dict, seg_path: Path, max_retries: int) -> bool:
    """1つのセグメントを生成する。"""
    label = f"seg_{i + 1:03d}"

    if seg_path.exists():
        print(f"\n  [skip] {label} — 既に存在")
        return True

    print(f"\n  [{label}] 生成中: {seg['phase_name']}")

    for attempt in range(max_retries + 1):
        if attempt > 0:
            wait_sec = min(30, 10 * attempt)
            print(f"    [{label}] retry {attempt}/{max_retries} ({wait_sec}s 待機)")
            time.sleep(wait_sec)

        audio_data = generate_segment(seg["prompt"], seg["model"])

        if audio_data is not None:
            _save_audio_as_wav(audio_data, seg_path)
            size_kb = seg_path.stat().st_size / 1024
            print(f"  [{label}] 完了 ({size_kb:.0f} KB)")
            cost_tracker.log_generation(
                "audio",
                model=seg["model"],
                quantity=1,
                metadata={
                    "phase_name": seg["phase_name"],
                    "segment": label,
                    "output_file": cost_tracker.relative_to_channel_dir(seg_path),
                },
            )
            return True

    print(f"  [{label}] {max_retries + 1} 回失敗")
    return False


def generate_segmented(
    comp: dict, output: Path, max_retries: int = 3, workers: int = 0, cleanup: bool = False
) -> bytes | None:
    """セグメント分割生成 → クロスフェード結合。

    workers=0: 逐次実行
    workers>0: 最大 workers 並列で生成
    """
    segments = build_segment_compositions(comp)
    seg_dir = output.parent
    seg_paths = [seg_dir / f"seg_{i + 1:03d}.wav" for i in range(len(segments))]
    crossfade_sec = comp.get("crossfade_sec", 5)
    fade_samples = SAMPLE_RATE * crossfade_sec

    mode = f"{workers} workers" if workers > 0 else "sequential"
    print(f"\n=== セグメント分割生成 ({len(segments)} segments, {mode}) ===")
    for i, seg in enumerate(segments):
        print(f"  seg_{i + 1:03d}: {seg['phase_name']}")

    if workers > 0:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {}
            for i, (seg, seg_path) in enumerate(zip(segments, seg_paths)):
                future = executor.submit(
                    _generate_one_segment,
                    i,
                    seg,
                    seg_path,
                    max_retries,
                )
                futures[future] = i

            results = [None] * len(segments)
            for future in futures:
                idx = futures[future]
                results[idx] = future.result()

        if not all(results):
            failed = [i + 1 for i, ok in enumerate(results) if not ok]
            print(f"\n[ERROR] 失敗セグメント: {failed}")
            print("  成功済みセグメントは保持されています。再実行で続行できます。")
            return None
    else:
        for i, (seg, seg_path) in enumerate(zip(segments, seg_paths)):
            ok = _generate_one_segment(i, seg, seg_path, max_retries)
            if not ok:
                print("  成功済みセグメントは保持されています。再実行で続行できます。")
                return None

    # 全セグメントをクロスフェード結合
    print(f"\n=== 結合中 ({len(segments)} segments, crossfade {crossfade_sec}s) ===")
    combined = read_wav_pcm(seg_paths[0])
    for i in range(1, len(seg_paths)):
        next_pcm = read_wav_pcm(seg_paths[i])
        combined = crossfade_join(combined, next_pcm, fade_samples)
        print(f"  joined: seg_{i:03d} + seg_{i + 1:03d} -> {format_duration_mmss(pcm_duration_sec(combined) / 60)}")

    write_wav(combined, output)

    if cleanup:
        for seg_path in seg_paths:
            if seg_path.exists():
                seg_path.unlink()
        print("  セグメントファイルを削除しました")
    else:
        individual_dir = output.parent.parent / "02-Individual-music"
        individual_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n=== セグメントファイルを {individual_dir.name}/ に移動 ===")
        for i, (seg_path, seg) in enumerate(zip(seg_paths, segments)):
            if not seg_path.exists():
                continue
            safe_name = seg["phase_name"].replace(" ", "-").replace("/", "-").replace("\\", "-").replace(":", "-")
            # 括弧を除去 (サブセグメント表記 "(1/3)" 等)
            safe_name = safe_name.replace("(", "").replace(")", "")
            new_name = f"{i + 1:02d}_{safe_name}.wav"
            new_path = individual_dir / new_name
            seg_path.rename(new_path)
            print(f"  {seg_path.name} -> {individual_dir.name}/{new_name}")

    return combined


def generate_shuffled_master(
    comp: dict, output: Path, passes: int, max_retries: int = 3, workers: int = 0, cleanup: bool = False
) -> bytes | None:
    """ユニーク12曲 × N パス シャッフルマスター生成。

    1. phases に対応する N 個のユニークセグメントを生成
    2. 各セグメントの順番を passes 回シャッフル
    3. 各シャッフル順でクロスフェード結合 → pass_pcm
    4. 全 pass_pcm をクロスフェード結合 → master.wav
    """
    segments = build_segment_compositions(comp)
    seg_dir = output.parent
    seg_paths = [seg_dir / f"seg_{i + 1:03d}.wav" for i in range(len(segments))]
    crossfade_sec = comp.get("crossfade_sec", 5)
    fade_samples = SAMPLE_RATE * crossfade_sec
    n = len(segments)

    mode = f"{workers} workers" if workers > 0 else "sequential"
    print(f"\n=== Unique セグメント生成 ({n} segments, {mode}) ===")
    for i, seg in enumerate(segments):
        print(f"  seg_{i + 1:03d}: {seg['phase_name']}")

    if workers > 0:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    _generate_one_segment,
                    i,
                    seg,
                    seg_path,
                    max_retries,
                ): i
                for i, (seg, seg_path) in enumerate(zip(segments, seg_paths))
            }
            results = [None] * n
            for future in futures:
                results[futures[future]] = future.result()
    else:
        results = []
        for i, (seg, seg_path) in enumerate(zip(segments, seg_paths)):
            results.append(_generate_one_segment(i, seg, seg_path, max_retries))

    if not all(results):
        failed = [i + 1 for i, ok in enumerate(results) if not ok]
        print(f"\n[ERROR] 失敗セグメント: {failed}")
        print("  成功済みセグメントは保持されています。再実行で続行できます。")
        return None

    # シャッフル順を passes 個生成
    # 制約:
    #   1. 全パスの並びは互いに重複しない（ベストエフォート）
    #   2. パス境界で同じ曲が連続しない（前パスの末尾 != 現パスの先頭）
    seed = comp.get("shuffle_seed")
    rng = random.Random(seed)
    used_orders: set[tuple[int, ...]] = set()
    pass_orders: list[list[int]] = []
    for _ in range(passes):
        prev_last = pass_orders[-1][-1] if pass_orders else None
        order = list(range(n))
        # まずは制約を満たす並びを探索
        for _ in range(200):
            rng.shuffle(order)
            if prev_last is not None and order[0] == prev_last:
                continue
            key = tuple(order)
            if key not in used_orders:
                used_orders.add(key)
                break
        else:
            # 200 回試行で見つからなければ、連続禁止だけは守って採用
            for _ in range(50):
                rng.shuffle(order)
                if prev_last is None or order[0] != prev_last:
                    break
        pass_orders.append(list(order))

    # 各セグメントの PCM を読み込み
    pcms = [read_wav_pcm(p) for p in seg_paths]

    # 各パスごとにクロスフェード結合
    print(f"\n=== {passes} パスのシャッフル結合 (crossfade {crossfade_sec}s) ===")
    pass_pcms: list[bytes] = []
    for p_idx, order in enumerate(pass_orders):
        order_str = " -> ".join(f"{i + 1:02d}" for i in order)
        print(f"  pass {p_idx + 1}/{passes}: {order_str}")
        combined = pcms[order[0]]
        for j in range(1, len(order)):
            combined = crossfade_join(combined, pcms[order[j]], fade_samples)
        pass_pcms.append(combined)
        print(f"    pass {p_idx + 1} duration: {format_duration_mmss(pcm_duration_sec(combined) / 60)}")

    # パス間をクロスフェード結合
    print(f"\n=== {passes} パスを統合中 (crossfade {crossfade_sec}s) ===")
    master = pass_pcms[0]
    for i in range(1, len(pass_pcms)):
        master = crossfade_join(master, pass_pcms[i], fade_samples)
        print(f"  joined: pass_{i:02d} + pass_{i + 1:02d} -> {format_duration_mmss(pcm_duration_sec(master) / 60)}")

    write_wav(master, output)

    if cleanup:
        for sp in seg_paths:
            if sp.exists():
                sp.unlink()
        print("  セグメントファイルを削除しました")
    else:
        individual_dir = output.parent.parent / "02-Individual-music"
        individual_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n=== セグメントファイルを {individual_dir.name}/ に移動 ===")
        for i, (sp, seg) in enumerate(zip(seg_paths, segments)):
            if not sp.exists():
                continue
            safe_name = seg["phase_name"].replace(" ", "-").replace("/", "-").replace("\\", "-").replace(":", "-")
            safe_name = safe_name.replace("(", "").replace(")", "")
            new_name = f"{i + 1:02d}_{safe_name}.wav"
            new_path = individual_dir / new_name
            sp.rename(new_path)
            print(f"  {sp.name} -> {individual_dir.name}/{new_name}")

    # シャッフル順をログとして保存
    log_path = output.parent.parent / "20-documentation" / "shuffle_orders.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_data = {
        "passes": passes,
        "segment_count": n,
        "crossfade_sec": crossfade_sec,
        "shuffle_seed": seed,
        "orders": [
            {"pass": p_idx + 1, "order_1based": [i + 1 for i in order]} for p_idx, order in enumerate(pass_orders)
        ],
    }
    log_path.write_text(json.dumps(log_data, indent=2, ensure_ascii=False))
    print(f"\n  シャッフル順ログ: {log_path}")

    return master


def build_preview_compositions(comp: dict) -> list[tuple[int, dict]]:
    """3つの代表フェーズからプレビュー用セグメント情報を構築する。"""
    phases = comp["phases"]
    n = len(phases)

    if n <= 3:
        indices = list(range(n))
    else:
        indices = [0, n // 2, n - 1]

    previews = []
    for idx in indices:
        phase = phases[idx]
        prompt = build_prompt(comp, phase)
        preview_seg = {
            "title": f"Preview: {phase.get('name_en', phase['name'])}",
            "prompt": prompt,
            "model": PREVIEW_MODEL,
            "phase_name": phase.get("name_en") or phase["name"],
        }
        previews.append((idx, preview_seg))

    return previews


def generate_previews(comp: dict, output_dir: Path) -> bool:
    """3つの代表フェーズから30秒プレビューを並列生成する。"""
    previews = build_preview_compositions(comp)

    print(f"\n=== プレビュー生成 ({len(previews)} samples, Clip model) ===")
    for i, (phase_idx, seg) in enumerate(previews):
        print(f"  preview_{i + 1:02d}: [{phase_idx + 1}/{len(comp['phases'])}] {seg['phase_name']}")

    output_dir.mkdir(parents=True, exist_ok=True)

    preview_paths = []
    for i, (_, seg) in enumerate(previews):
        safe_name = seg["phase_name"].replace(" ", "-").replace("/", "-").replace("\\", "-").replace(":", "-")
        path = output_dir / f"preview_{i + 1:02d}_{safe_name}.wav"
        preview_paths.append(path)

    with ThreadPoolExecutor(max_workers=len(previews)) as executor:
        futures = {}
        for i, ((_, seg), path) in enumerate(zip(previews, preview_paths)):
            future = executor.submit(
                _generate_one_segment,
                i,
                seg,
                path,
                max_retries=1,
            )
            futures[future] = i

        results = [None] * len(previews)
        for future in futures:
            idx = futures[future]
            results[idx] = future.result()

    if all(results):
        print("\n=== プレビュー完了 ===")
        for path in preview_paths:
            print(f"  {path.name}")
        return True
    else:
        failed = [i + 1 for i, ok in enumerate(results) if not ok]
        print(f"\n[ERROR] プレビュー生成失敗: {failed}")
        return False


def main():
    try:
        from dotenv import find_dotenv, load_dotenv

        load_dotenv(find_dotenv())
    except ImportError:
        pass

    parser = argparse.ArgumentParser(
        description="Lyria 3 DJ Engine — composition.json 駆動の音楽生成",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-c", "--composition", required=True, help="composition.json パス")
    parser.add_argument("-o", "--output", default="master.wav", help="出力 WAV パス (default: master.wav)")
    parser.add_argument("-y", "--yes", action="store_true", help="確認スキップ")
    parser.add_argument("--dry-run", action="store_true", help="タイムライン表示のみ")
    parser.add_argument("--max-retries", type=int, default=3, help="失敗時の自動リトライ回数 (default: 3)")
    parser.add_argument("--workers", type=int, default=0, help="並列生成数 (default: 0=逐次、N=N並列、-1=全並列)")
    parser.add_argument(
        "--cleanup", action="store_true", default=False, help="生成後にセグメントファイルを削除 (default: 保持)"
    )
    parser.add_argument("--preview", action="store_true", help="3つの代表フェーズから30秒プレビューを生成 (Clip model)")
    parser.add_argument(
        "--shuffle-passes", type=int, default=None, help="N>0 で各 phase を 1 セグメントずつ生成し N 回シャッフル連結"
    )
    args = parser.parse_args()

    comp_path = Path(args.composition).resolve()
    if not comp_path.exists():
        print(f"[ERROR] {comp_path} が見つかりません")
        sys.exit(1)

    comp = load_composition(comp_path)

    # CLI フラグが composition.json をオーバーライド
    if args.shuffle_passes is not None:
        comp["shuffle_passes"] = args.shuffle_passes
        if args.shuffle_passes > 0:
            comp.setdefault("segment_duration_sec", DEFAULT_SHUFFLE_SEGMENT_SEC)

    if args.dry_run:
        dry_run(comp)
        sys.exit(0)

    dry_run(comp)

    if args.preview:
        output_dir = Path(args.output).resolve().parent / "preview"
        start_time = time.monotonic()
        try:
            ok = generate_previews(comp, output_dir)
        except ConfigError as e:
            print(f"[ERROR] {e}")
            sys.exit(1)
        elapsed = time.monotonic() - start_time

        if ok:
            print(f"\n  生成時間: {int(elapsed)}秒")
            print("  プレビューを確認し、問題なければ --preview を外して本生成を実行してください。")
        else:
            sys.exit(1)
        sys.exit(0)

    if not args.yes:
        try:
            answer = input("続行しますか? (y/N): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n中止しました。")
            sys.exit(0)
        if answer not in ("y", "yes"):
            print("中止しました。")
            sys.exit(0)

    output = Path(args.output).resolve()
    workers = args.workers if args.workers >= 0 else len(build_segment_compositions(comp))

    start_time = time.monotonic()

    try:
        if comp.get("shuffle_passes", 0) > 0:
            pcm_data = generate_shuffled_master(
                comp,
                output,
                passes=comp["shuffle_passes"],
                max_retries=args.max_retries,
                workers=workers,
                cleanup=args.cleanup,
            )
        else:
            pcm_data = generate_segmented(
                comp,
                output,
                max_retries=args.max_retries,
                workers=workers,
                cleanup=args.cleanup,
            )
    except ConfigError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    gen_elapsed = time.monotonic() - start_time

    if pcm_data is None:
        print("\n音楽生成に失敗しました。")
        print("  成功済みセグメントは保持されています。再実行で続行できます。")
        sys.exit(1)

    actual_duration = pcm_duration_sec(pcm_data)
    size_mb = output.stat().st_size / (1024 * 1024)
    m, s = divmod(int(actual_duration), 60)

    print()
    print("===========================================")
    print(f"  DJ 生成: 完了 — {comp['title']}")
    print(f"  ファイル:   {output}")
    print(f"  時間:       {int(actual_duration)}秒 ({m}:{s:02d})")
    print(f"  サイズ:     {size_mb:.1f} MB")
    seg_count = len(build_segment_compositions(comp))
    if comp.get("shuffle_passes", 0) > 0:
        passes = comp["shuffle_passes"]
        print(f"  セグメント: {seg_count} unique × {passes} passes = {seg_count * passes} occurrences")
    else:
        print(f"  セグメント: {seg_count}")
    print(f"  生成時間:   {int(gen_elapsed)}秒")
    print("===========================================")

    cost_tracker.print_last_report()


if __name__ == "__main__":
    main()
