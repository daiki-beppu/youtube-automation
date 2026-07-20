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
import json
import sys
from pathlib import Path

from youtube_automation.utils.collection_paths import CollectionPaths
from youtube_automation.utils.config import load_config
from youtube_automation.utils.exceptions import ValidationError
from youtube_automation.utils.preflight_checks import requires_scene_phrases


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


def _supported_languages() -> list[str]:
    config = load_config()
    return list(dict.fromkeys(config.localizations.supported_languages))


def _validate_scene_phrases(paths: CollectionPaths, supported_languages: list[str]) -> list[str]:
    if not paths.workflow_state_path.is_file():
        return []

    try:
        state = json.loads(paths.workflow_state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ["workflow-state.json の JSON が不正"]
    if not isinstance(state, dict):
        return ["workflow-state.json の root は object である必要があります"]

    if not requires_scene_phrases(supported_languages):
        return []

    scene_phrases = state.get("scene_phrases")
    if not isinstance(scene_phrases, dict) or not scene_phrases:
        return ["workflow-state.json.scene_phrases なし（yt-populate-scene-phrases を実行）"]

    missing = [lang for lang in supported_languages if not scene_phrases.get(lang)]
    if missing:
        return [f"workflow-state.json.scene_phrases に不足: {', '.join(missing)}"]
    return []


def check_collection(
    collection_dir: Path,
    fix: bool,
    *,
    supported_languages: list[str] | None = None,
) -> tuple[bool, str]:
    """1 コレクションの骨格を検証（fix=True なら欠落を補完）し、(OK, 表示行) を返す。"""
    paths = CollectionPaths(collection_dir)
    name = collection_dir.name
    langs = ["en"] if supported_languages is None else list(dict.fromkeys(supported_languages))

    if fix:
        try:
            created = paths.ensure_required_dirs()
        except ValidationError as exc:
            return False, f"[NG] {name}: {exc}"
        missing = []
    else:
        created = []
        missing = paths.missing_required_dirs()

    invalid = paths.invalid_required_dirs()
    state_ok = paths.workflow_state_path.is_file()

    problems = []
    if invalid:
        problems.append(f"同名ファイルあり: {', '.join(invalid)}")
    if missing:
        problems.append(f"欠落: {', '.join(missing)}")
    if not state_ok:
        problems.append("workflow-state.json なし（/wf-new で初期化が必要）")
    problems.extend(_validate_scene_phrases(paths, langs))

    if problems:
        return False, f"[NG] {name}: {' / '.join(problems)}"
    if created:
        return True, f"[FIXED] {name}: {', '.join(created)} を作成"
    return True, f"[OK] {name}"


def ensure_collection_preflight(collection_dir: Path) -> None:
    ok, line = check_collection(collection_dir, fix=False, supported_languages=_supported_languages())
    if not ok:
        raise ValidationError(line)


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
    supported_languages = _supported_languages()
    for collection_dir in targets:
        ok, line = check_collection(collection_dir, fix=args.fix, supported_languages=supported_languages)
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
