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

from youtube_automation.core.errors import ValidationError, WorkflowStateError
from youtube_automation.domains.collections.workflow_state import WorkflowState
from youtube_automation.domains.collections.workflow_state import read_or_none as read_workflow_state_or_none
from youtube_automation.domains.collections.workflow_state import update as update_workflow_state
from youtube_automation.domains.uploads.playlist_resolution import (
    categorizing_playlist_keys,
    validate_playlist_keys,
)
from youtube_automation.infrastructure.media.collection_paths import CollectionPaths

# --- パス解決 ---
SCRIPT_DIR = Path(__file__).resolve().parent

# 初期化済みコレクションだけが持つ workflow-state のキー（企画 draft 投影では書かれない）。
_INITIALIZED_STATE_KEYS = frozenset(
    {"collection_name", "theme", "created_at", "stage", "phase", "selected_plan", "track_count", "assets", "upload"}
)


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


def _is_plan_draft_directory(base_path: Path) -> bool:
    """企画 draft 公開だけが作った未初期化ディレクトリかを判定する (#4754).

    `/wf-new` Phase 1 は初期化前に `20-documentation/plan_proposals.json` pair を公開し、
    `yt-collection-plan-select` が `planning.*` だけの `workflow-state.json` を作る。この
    状態のディレクトリで Phase 2a を止めると、本来の workflow-state を書ける入口が無くなる。
    初期化済みコレクションと破損 state は従来どおり fail-loud で拒否する。
    """
    if not (base_path / "20-documentation" / "plan_proposals.json").is_file():
        return False
    try:
        state = read_workflow_state_or_none(base_path / "workflow-state.json")
    except WorkflowStateError:
        return False
    return state is None or not (_INITIALIZED_STATE_KEYS & state.keys())


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
        choices=["suno", "lyria"],
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

    plan_draft = base_path.exists() and _is_plan_draft_directory(base_path)
    if base_path.exists() and not plan_draft:
        print(f"[ERROR] ディレクトリが既に存在します: {base_path}", file=sys.stderr)
        print(
            "        骨格の欠落を補完する場合は手動 mkdir ではなく "
            f"`uv run yt-collection-preflight {shlex.quote(dir_name)} --fix` を使ってください",
            file=sys.stderr,
        )
        sys.exit(1)

    if plan_draft:
        print(f"[INFO] 企画 draft 公開済みディレクトリを初期化します: {base_path}")

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

    def initialize(current: WorkflowState) -> WorkflowState:
        """企画確定で投影済みの planning 値を初期化で消さない (#4754)。"""
        published = current.get("planning")
        if isinstance(published, dict):
            state["planning"] = {**published, **state["planning"]}
        return WorkflowState(state)

    update_workflow_state(state_path, initialize)

    print(f"[OK] コレクション作成完了: {base_path}")
    print(f"  テーマ: {args.theme}")
    print(f"  トラック数: {args.track_count}")
    print(f"  選択プラン: {args.selected_plan}")
    print(f"  音楽エンジン: {music_engine}")
    if playlists is not None:
        print(f"  プレイリスト: {', '.join(playlists) if playlists else '(auto_add のみ)'}")


if __name__ == "__main__":
    main()
