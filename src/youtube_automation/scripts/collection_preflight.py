#!/usr/bin/env python3
"""コレクションの標準ディレクトリ骨格を検証・補完する（#1494）。

`yt-init-collection` が作る標準骨格（``REQUIRED_SUBDIRS`` + workflow-state.json）が
揃っているかを fail-loud で検証する。欠落が後工程（/masterup, /videoup）まで
発覚しない事故を防ぐため、/wf-next・/suno-helper 開始前のプリフライトとして使う。

Usage:
    # planning 配下の全コレクションを検証
    uv run yt-collection-preflight

    # 特定コレクションのみ検証（ディレクトリ名 or パス）
    uv run yt-collection-preflight 20260702-slg-soulful-grooves-collection

    # 欠落サブディレクトリを冪等に作成（既存ファイルは非破壊）
    uv run yt-collection-preflight --fix

Exit codes:
    0: 骨格 OK（--fix 時は補完完了を含む）
    1: 骨格欠落あり（--fix なし）、または workflow-state.json 欠落
    2: 対象コレクションを解決できない
"""

import argparse
import sys
from pathlib import Path

from youtube_automation.utils.collection_paths import CollectionPaths


def _planning_root() -> Path:
    from youtube_automation.utils.config import channel_dir

    return Path(channel_dir()) / "collections" / "planning"


def _resolve_targets(collections: list[str], planning_root: Path | None) -> list[Path]:
    """CLI 引数からコレクションディレクトリ群を解決する。

    引数指定時: 各引数を「既存パス > planning 配下のディレクトリ名」の順に解決する。
    未指定時: planning 配下の ``*-collection`` ディレクトリ全件を対象にする。
    """
    if collections:
        targets = []
        for arg in collections:
            direct = Path(arg)
            if direct.is_dir():
                targets.append(direct.resolve())
                continue
            root = planning_root if planning_root is not None else _planning_root()
            candidate = root / arg
            if candidate.is_dir():
                targets.append(candidate.resolve())
                continue
            print(f"[ERROR] コレクションが見つかりません: {arg}", file=sys.stderr)
            print(f"        探索先: {direct.resolve()} / {candidate}", file=sys.stderr)
            sys.exit(2)
        return targets

    root = planning_root if planning_root is not None else _planning_root()
    if not root.is_dir():
        return []
    return sorted(p for p in root.glob("*-collection") if p.is_dir())


def check_collection(collection_dir: Path, fix: bool) -> tuple[bool, str]:
    """1 コレクションの骨格を検証（fix=True なら欠落を補完）し、(OK, 表示行) を返す。"""
    paths = CollectionPaths(collection_dir)
    name = collection_dir.name

    if fix:
        created = paths.ensure_required_dirs()
        missing = []
    else:
        created = []
        missing = paths.missing_required_dirs()

    state_ok = paths.workflow_state_path.is_file()

    problems = []
    if missing:
        problems.append(f"欠落: {', '.join(missing)}")
    if not state_ok:
        problems.append("workflow-state.json なし（/wf-new で初期化が必要）")

    if problems:
        return False, f"[NG] {name}: {' / '.join(problems)}"
    if created:
        return True, f"[FIXED] {name}: {', '.join(created)} を作成"
    return True, f"[OK] {name}"


def main():
    parser = argparse.ArgumentParser(description="コレクションの標準ディレクトリ骨格を検証・補完する")
    parser.add_argument(
        "collections",
        nargs="*",
        help="対象コレクション（ディレクトリ名 or パス）。未指定時は planning 配下の全コレクション",
    )
    parser.add_argument("--fix", action="store_true", help="欠落サブディレクトリを冪等に作成する（非破壊）")
    parser.add_argument(
        "--planning-root",
        type=Path,
        default=None,
        help="planning ディレクトリの明示指定（デフォルト: <CHANNEL_DIR>/collections/planning）",
    )
    args = parser.parse_args()

    targets = _resolve_targets(args.collections, args.planning_root)
    if not targets:
        print("[OK] 検証対象のコレクションがありません")
        return

    all_ok = True
    for collection_dir in targets:
        ok, line = check_collection(collection_dir, fix=args.fix)
        print(line)
        all_ok = all_ok and ok

    if not all_ok:
        if not args.fix:
            print(
                "\n[ERROR] 骨格が欠落しています。`yt-collection-preflight --fix` で補完できます",
                file=sys.stderr,
            )
        sys.exit(1)


if __name__ == "__main__":
    main()
