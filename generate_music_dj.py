#!/usr/bin/env python3
"""Lyria DJ Engine — composition.json 駆動のフェーズ展開音楽生成。"""

import argparse
import json
import sys
from pathlib import Path


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
    print(f"  Base: bpm={base.get('bpm', 'auto')} brightness={base.get('brightness', 'auto')} mode={base.get('mode', 'QUALITY')}")
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

    # 生成ロジックは Task 2 で実装
    print("[TODO] 生成ロジック未実装")


if __name__ == "__main__":
    main()
