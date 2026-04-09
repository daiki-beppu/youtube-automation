#!/usr/bin/env python3
"""コレクションディレクトリと workflow-state.json を初期化する。

Usage:
    # チャンネルディレクトリから実行（CWD 自動検出）
    python3 ../../automation/init_collection.py "Collection Name" "theme-slug"
    python3 ../../automation/init_collection.py "Collection Name" "theme-slug" \\
        --track-count 12 --selected-plan B --music-engine lyria

    # ルートから CHANNEL_DIR 指定で実行
    CHANNEL_DIR=channels/fantasy-celtic-music python3 automation/init_collection.py "Collection Name" "theme-slug"

Example:
    python3 ../../automation/init_collection.py "Weaving with Brigid by the Hearth" \\
        "brigid-hearth" --selected-plan B --music-engine suno
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# --- パス解決 ---
SCRIPT_DIR = Path(__file__).resolve().parent

SUBDIRS = [
    "01-master",
    "02-Individual-music",
    "10-assets",
    "20-documentation",
]


def build_state(collection_name: str, theme: str, track_count: int, selected_plan: str, music_engine: str) -> dict:
    """workflow-state.json の初期状態を構築する（v2 スキーマ）。"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return {
        "collection_name": collection_name,
        "theme": theme,
        "created_at": now,
        "updated_at": now,
        "stage": "planning",
        "phase": "planning",
        "selected_plan": selected_plan,
        "track_count": track_count,
        "music_engine": music_engine,
        "assets": {
            "thumbnail": False,
            "loop_video": False,
            "music_prompts": False,
            "raw_master": None,
            "master_audio": None,
            "master_video": None,
            "description": False,
            "short_thumbnail": False,
        },
        "upload": {
            "video_id": None,
            "video_url": None,
            "publish_at": None,
        },
        "community": {
            "drafted": False,
            "posted": False,
        },
        "shorts": {
            "count": 0,
            "videos": [],
        },
    }


def main():
    from youtube_automation.utils.channel_config import ChannelConfig  # noqa: E402

    parser = argparse.ArgumentParser(description="コレクションディレクトリと workflow-state.json を初期化")
    parser.add_argument("collection_name", help="コレクション表示名")
    parser.add_argument("theme", help="テーマスラッグ（ハイフン区切り）")
    parser.add_argument("--track-count", type=int, default=12, help="トラック数（デフォルト: 12）")
    parser.add_argument("--selected-plan", default="A", help="選択した企画（A-E、デフォルト: A）")
    parser.add_argument(
        "--music-engine", default=None, choices=["suno", "lyria"],
        help="音楽エンジン（デフォルト: channel_config から自動判定）",
    )
    args = parser.parse_args()

    config = ChannelConfig.load()
    short = config.raw["channel"]["short"].lower()
    ch_dir = Path(ChannelConfig.channel_dir())

    music_engine = args.music_engine or ("lyria" if config.raw.get("lyria") else "suno")

    date_prefix = datetime.now().strftime("%Y%m%d")
    dir_name = f"{date_prefix}-{short}-{args.theme}-collection"
    base_path = ch_dir / "collections" / "planning" / dir_name

    if base_path.exists():
        print(f"[ERROR] ディレクトリが既に存在します: {base_path}", file=sys.stderr)
        sys.exit(1)

    # ディレクトリ作成
    for sub in SUBDIRS:
        (base_path / sub).mkdir(parents=True, exist_ok=True)

    # workflow-state.json 生成
    state = build_state(args.collection_name, args.theme, args.track_count, args.selected_plan, music_engine)
    state_path = base_path / "workflow-state.json"
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"[OK] コレクション作成完了: {base_path}")
    print(f"  テーマ: {args.theme}")
    print(f"  トラック数: {args.track_count}")
    print(f"  選択プラン: {args.selected_plan}")
    print(f"  音楽エンジン: {music_engine}")


if __name__ == "__main__":
    main()
