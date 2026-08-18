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
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path

from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.collections.workflow_state import WorkflowState
from youtube_automation.domains.collections.workflow_state import update as update_workflow_state
from youtube_automation.domains.uploads.playlist_resolution import (
    categorizing_playlist_keys,
    validate_playlist_keys,
)
from youtube_automation.infrastructure.media.collection_paths import CollectionPaths

# --- パス解決 ---
SCRIPT_DIR = Path(__file__).resolve().parent


def build_state(
    collection_name: str,
    theme: str,
    track_count: int,
    selected_plan: str,
    music_engine: str,
    playlists: list[str] | None = None,
) -> dict:
    """workflow-state.json の初期状態を構築する（v2 スキーマ）。

    ``playlists`` は所属させるプレイリスト key の明示指定（#4346）。``None`` は
    未決定として key 自体を書かない。``[]`` は「auto_add 以外へは入れない」の明示。
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    planning: dict = {"music": {"engine": music_engine}}
    if playlists is not None:
        planning["playlists"] = list(playlists)
    return {
        "collection_name": collection_name,
        "theme": theme,
        "created_at": now,
        "updated_at": now,
        "stage": "planning",
        "phase": "planning",
        "selected_plan": selected_plan,
        "track_count": track_count,
        "planning": planning,
        "assets": {
            "thumbnail": False,
            "loop_video": False,
            "music_prompts": False,
            "raw_master": None,
            "master_audio": None,
            "master_video": None,
            "description": False,
        },
        "upload": {
            "video_id": None,
            "video_url": None,
            "publish_at": None,
        },
    }


def _resolve_playlist_argument(config, args) -> list[str] | None:
    """`--playlist` / `--no-playlist` を検証して planning.playlists の値を決める (#4346).

    分類プレイリスト（`auto_add` 以外）を定義しているチャンネルでは、どちらかの
    明示を必須にする。theme slug のキーワード照合に任せると新テーマで必ず漏れ、
    黙って `auto_add` プレイリストだけに入るため。
    """
    playlists_config = config.playlists.items
    categorizing = categorizing_playlist_keys(playlists_config)

    if args.no_playlist:
        if args.playlists:
            print("[ERROR] --playlist と --no-playlist は同時に指定できません", file=sys.stderr)
            sys.exit(1)
        return []

    if args.playlists:
        try:
            validate_playlist_keys(playlists_config, args.playlists, source="--playlist")
        except ValidationError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            sys.exit(1)
        # 重複指定は正規化する（config 定義順）。
        selected = set(args.playlists)
        explicit = [key for key in playlists_config if key in selected]
        if categorizing and not any(key in categorizing for key in explicit):
            print(
                "[ERROR] --playlist には分類プレイリストを1つ以上指定してください。\n"
                "        分類しないことが意図なら --no-playlist を明示してください",
                file=sys.stderr,
            )
            sys.exit(1)
        return explicit

    if categorizing:
        print(
            "[ERROR] プレイリストの割り当て先が未指定です。\n"
            f"        --playlist で指定してください（候補: {', '.join(categorizing)}）\n"
            "        分類しないことが意図なら --no-playlist を明示してください",
            file=sys.stderr,
        )
        sys.exit(1)

    return None


def main():
    from youtube_automation.configuration import channel_dir, load_config

    parser = argparse.ArgumentParser(description="コレクションディレクトリと workflow-state.json を初期化")
    parser.add_argument("collection_name", help="コレクション表示名")
    parser.add_argument("theme", help="テーマスラッグ（ハイフン区切り）")
    parser.add_argument("--track-count", type=int, default=12, help="トラック数（デフォルト: 12）")
    parser.add_argument("--selected-plan", default="A", help="選択した企画（A-E、デフォルト: A）")
    parser.add_argument(
        "--music-engine",
        default=None,
        choices=["suno", "lyria", "minimax"],
        help="音楽エンジン（デフォルト: channel_config から自動判定）",
    )
    parser.add_argument(
        "--playlist",
        action="append",
        dest="playlists",
        metavar="KEY",
        help=(
            "所属させるプレイリスト key（config/channel/playlists.json）。複数指定可。"
            "分類プレイリストを定義しているチャンネルでは必須"
        ),
    )
    parser.add_argument(
        "--no-playlist",
        action="store_true",
        help="分類プレイリストへは意図的に追加しない（auto_add のみ）ことを明示する",
    )
    args = parser.parse_args()

    config = load_config()
    short = config.meta.channel_short.lower()
    ch_dir = Path(channel_dir())

    music_engine = args.music_engine or config.youtube.music_engine
    playlists = _resolve_playlist_argument(config, args)

    date_prefix = datetime.now().strftime("%Y%m%d")
    dir_name = f"{date_prefix}-{short}-{args.theme}-collection"
    base_path = ch_dir / "collections" / "planning" / dir_name

    if base_path.exists():
        print(f"[ERROR] ディレクトリが既に存在します: {base_path}", file=sys.stderr)
        print(
            "        骨格の欠落を補完する場合は手動 mkdir ではなく "
            f"`uv run yt-collection-preflight {shlex.quote(dir_name)} --fix` を使ってください",
            file=sys.stderr,
        )
        sys.exit(1)

    # ディレクトリ作成（REQUIRED_SUBDIRS を CollectionPaths と共有、#1494）
    base_path.mkdir(parents=True, exist_ok=True)
    CollectionPaths(base_path).ensure_required_dirs()

    # workflow-state.json 生成
    state = build_state(
        args.collection_name,
        args.theme,
        args.track_count,
        args.selected_plan,
        music_engine,
        playlists=playlists,
    )
    state_path = base_path / "workflow-state.json"
    update_workflow_state(state_path, lambda _current: WorkflowState(state))

    print(f"[OK] コレクション作成完了: {base_path}")
    print(f"  テーマ: {args.theme}")
    print(f"  トラック数: {args.track_count}")
    print(f"  選択プラン: {args.selected_plan}")
    print(f"  音楽エンジン: {music_engine}")
    if playlists is not None:
        print(f"  プレイリスト: {', '.join(playlists) if playlists else '(auto_add のみ)'}")


if __name__ == "__main__":
    main()
