"""CLI adapter for collection upload preflight."""

import argparse
import sys
from pathlib import Path

from youtube_automation.configuration import channel_dir, load_config
from youtube_automation.domains.uploads.preflight import check_collection


def _planning_root() -> Path:
    return Path(channel_dir()) / "collections" / "planning"


def _supported_languages() -> list[str]:
    config = load_config()
    return list(dict.fromkeys(config.localizations.supported_languages))


def _resolve_targets(collections: list[str], planning_root: Path | None) -> list[Path]:
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


def main() -> None:
    parser = argparse.ArgumentParser(description="コレクションの標準ディレクトリ骨格を検証・補完する")
    parser.add_argument("collections", nargs="*", help="対象コレクション（ディレクトリ名 or パス）")
    parser.add_argument("--fix", action="store_true", help="欠落サブディレクトリを冪等に作成する")
    parser.add_argument("--planning-root", type=Path, default=None, help="planning ディレクトリの明示指定")
    args = parser.parse_args()

    targets = _resolve_targets(args.collections, args.planning_root)
    if not targets:
        print("[OK] 検証対象のコレクションがありません")
        return

    supported_languages = _supported_languages()
    all_ok = True
    for collection_dir in targets:
        ok, line = check_collection(collection_dir, fix=args.fix, supported_languages=supported_languages)
        print(line)
        all_ok = all_ok and ok

    if not all_ok:
        if not args.fix:
            print("\n[ERROR] 骨格が欠落しています。--fix で補完できます", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
