"""yt-config-migrate — 旧 config/channel_config.json を新 config/channel/*.json 構造に分割する。

Subcommands:
    migrate : 旧 → 新構造への変換 (default: dry-run、--apply で実書き込み)
    verify  : 新構造を新 loader で読み込み検証
    diff    : 旧 JSON と分割結果のキー差分表示 (未マップキー検出)

設計原則:
    `migrate` / `diff` は新 loader (utils/config) に依存せず独立動作する。
    automation v2.0.0 に pin-bump した直後、旧 channel_config.json のままでも
    実行可能である必要があるため（他のコマンドは新構造前提で起動失敗する）。
    `verify` のみ新 loader を lazy import し、移行後構造の読み込みを確認する。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from collections.abc import Iterable
from pathlib import Path

from youtube_automation.utils.exceptions import ConfigError

SECTION_MAP: dict[str, list[str]] = {
    "meta.json": ["channel", "youtube_channel"],
    "content.json": ["genre", "tags", "descriptions", "title"],
    "youtube.json": ["youtube", "music_engine", "content_model"],
    "analytics.json": ["analytics", "benchmark"],
    "playlists.json": ["playlists"],
    "workflow.json": ["workflow"],
    "audio.json": ["audio"],
}
LOCALIZATIONS_MERGE_KEY = "localization"  # rjn 由来、単数形
LOCALIZATIONS_FILENAME = "localizations.json"  # 複数形で固定


def _resolve_target_dir(target: str | None) -> Path:
    """対象チャンネルディレクトリを解決する.

    優先順: --target → CHANNEL_DIR → CWD 祖先探索で config/channel_config.json を持つディレクトリ.
    """
    if target:
        path = Path(target).resolve()
        if not path.is_dir():
            raise ConfigError(f"--target で指定されたディレクトリが存在しません: {path}")
        return path

    env = os.environ.get("CHANNEL_DIR")
    if env:
        path = Path(env).resolve()
        if not path.is_dir():
            raise ConfigError(f"CHANNEL_DIR で指定されたディレクトリが存在しません: {path}")
        return path

    for parent in [Path.cwd()] + list(Path.cwd().parents):
        if (parent / "config" / "channel_config.json").is_file():
            return parent

    raise ConfigError(
        "対象チャンネルディレクトリが特定できません。"
        "--target DIR を指定するか、CHANNEL_DIR 環境変数を設定するか、"
        "config/channel_config.json を持つディレクトリ配下で実行してください"
    )


def _load_legacy_json(target: Path) -> dict:
    path = target / "config" / "channel_config.json"
    if not path.is_file():
        raise ConfigError(f"旧 channel_config.json が見つかりません: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(f"channel_config.json の JSON パース失敗: {path}: {e}")
    if not isinstance(data, dict):
        raise ConfigError(f"channel_config.json のトップレベルは object でなければなりません: {path}")
    return data


def _ensure_channel_dir_empty(target: Path) -> None:
    channel_dir = target / "config" / "channel"
    if channel_dir.is_dir():
        existing = sorted(channel_dir.glob("*.json"))
        if existing:
            names = ", ".join(p.name for p in existing)
            raise ConfigError(
                f"config/channel/ に既に JSON ファイルが存在します ({names})。"
                f"上書きを避けるため中止します。{channel_dir} を手動で片付けてから再実行してください"
            )


def _split_sections(legacy: dict) -> tuple[dict[str, dict], list[str]]:
    """SECTION_MAP に従って分配。戻り値: (ファイル名 → セクション辞書, 未マップキー一覧)."""
    files: dict[str, dict] = {}
    mapped_keys: set[str] = set()
    for filename, keys in SECTION_MAP.items():
        section: dict = {}
        for key in keys:
            if key in legacy:
                section[key] = legacy[key]
                mapped_keys.add(key)
        if section:
            files[filename] = section
    mapped_keys.add(LOCALIZATIONS_MERGE_KEY)  # localization は別扱いだが未マップ扱いにしない
    unmapped = [k for k in legacy.keys() if k not in mapped_keys]
    return files, unmapped


def _compute_localization_merge(target: Path, localization_data: dict) -> tuple[str, dict | None]:
    """localization キーを localizations.json にマージする計画を立てる.

    戻り値:
        ("create", new_data): localizations.json が存在しないので新規作成
        ("match", None): 既存と一致、no-op
        値不一致 → ConfigError 送出
    """
    loc_path = target / "config" / LOCALIZATIONS_FILENAME
    if not loc_path.is_file():
        return ("create", dict(localization_data))

    try:
        with open(loc_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(f"{LOCALIZATIONS_FILENAME} の JSON パース失敗: {loc_path}: {e}")
    if not isinstance(existing, dict):
        raise ConfigError(f"{LOCALIZATIONS_FILENAME} のトップレベルは object でなければなりません: {loc_path}")

    mismatches = []
    for key, value in localization_data.items():
        if key not in existing:
            mismatches.append(f"  - {key}: 既存の {LOCALIZATIONS_FILENAME} に存在しません")
        elif existing[key] != value:
            mismatches.append(f"  - {key}: channel_config.json={value!r}, {LOCALIZATIONS_FILENAME}={existing[key]!r}")
    if mismatches:
        raise ConfigError(
            f"{LOCALIZATIONS_MERGE_KEY} キーと既存 {LOCALIZATIONS_FILENAME} の値が一致しません:\n"
            + "\n".join(mismatches)
        )
    return ("match", None)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")


def _format_preview(
    files: dict[str, dict],
    unmapped: list[str],
    loc_action: str | None,
    *,
    apply: bool,
) -> str:
    prefix = "" if apply else "[dry-run] "
    header = f"{prefix}書き出し{'完了' if apply else '予定'}ファイル:"
    lines = [header]
    for filename, section in files.items():
        keys = ", ".join(section.keys())
        lines.append(f"  {filename}: {keys}")
    if loc_action == "create":
        lines.append(f"  {LOCALIZATIONS_FILENAME}: (localization キーから新規作成)")
    elif loc_action == "match":
        lines.append(f"  {LOCALIZATIONS_FILENAME}: (既存と一致、マージ不要)")
    if unmapped:
        lines.append(f"  (unmapped) {', '.join(unmapped)}")
    return "\n".join(lines)


def cmd_migrate(args: argparse.Namespace) -> int:
    try:
        target = _resolve_target_dir(args.target)
        legacy = _load_legacy_json(target)
        _ensure_channel_dir_empty(target)

        files, unmapped = _split_sections(legacy)

        loc_action: str | None = None
        loc_new_data: dict | None = None
        if LOCALIZATIONS_MERGE_KEY in legacy:
            loc_action, loc_new_data = _compute_localization_merge(target, legacy[LOCALIZATIONS_MERGE_KEY])

        if unmapped:
            if args.strict:
                raise ConfigError(f"SECTION_MAP に未マップのトップレベルキーがあります: {', '.join(unmapped)}")
            print(
                f"[warning] SECTION_MAP に未マップのトップレベルキー: {', '.join(unmapped)}",
                file=sys.stderr,
            )
            print(
                "[warning]   旧 channel_config.json に残ります（--strict で ConfigError 化可能）",
                file=sys.stderr,
            )

        if loc_action == "match":
            print(
                f"[warning] {LOCALIZATIONS_MERGE_KEY} キーは既存 {LOCALIZATIONS_FILENAME} と一致、マージ不要",
                file=sys.stderr,
            )

        print(_format_preview(files, unmapped, loc_action, apply=args.apply))

        if not args.apply:
            return 0

        channel_dir = target / "config" / "channel"
        for filename, section in files.items():
            _write_json(channel_dir / filename, section)
        if loc_action == "create" and loc_new_data is not None:
            _write_json(target / "config" / LOCALIZATIONS_FILENAME, loc_new_data)

        source_path = target / "config" / "channel_config.json"
        if args.backup:
            backup_path = source_path.with_name(source_path.name + ".bak")
            shutil.copy2(source_path, backup_path)
            print(f"  backup: {backup_path.name}")
        if args.delete_source:
            source_path.unlink()
            print(f"  deleted: {source_path.name}")

        return 0
    except ConfigError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1


def cmd_verify(args: argparse.Namespace) -> int:
    try:
        target = _resolve_target_dir(args.target)
    except ConfigError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1

    original_env = os.environ.get("CHANNEL_DIR")
    os.environ["CHANNEL_DIR"] = str(target)
    try:
        from youtube_automation.utils.config import load_config, reset

        reset()
        config = load_config()
        print(f"OK: ChannelConfig loaded (meta.channel_name={config.meta.channel_name!r})")
        return 0
    except ConfigError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1
    finally:
        try:
            from youtube_automation.utils.config import reset

            reset()
        except Exception:  # noqa: BLE001
            pass
        if original_env is None:
            os.environ.pop("CHANNEL_DIR", None)
        else:
            os.environ["CHANNEL_DIR"] = original_env


def cmd_diff(args: argparse.Namespace) -> int:
    try:
        target = _resolve_target_dir(args.target)
        legacy = _load_legacy_json(target)
    except ConfigError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1

    files, unmapped = _split_sections(legacy)

    col_width = 24
    print(f"{'File':<{col_width}} Keys")
    print("-" * (col_width + 20))
    for filename, section in files.items():
        print(f"{filename:<{col_width}} {', '.join(section.keys())}")
    if LOCALIZATIONS_MERGE_KEY in legacy:
        print(f"{LOCALIZATIONS_FILENAME + ' (merged)':<{col_width}} {LOCALIZATIONS_MERGE_KEY}")
    if unmapped:
        print(f"{'(unmapped)':<{col_width}} {', '.join(unmapped)}")
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-config-migrate",
        description="旧 config/channel_config.json を新 config/channel/*.json 構造に分割する",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_migrate = sub.add_parser("migrate", help="旧 → 新構造への変換 (default: dry-run)")
    p_migrate.add_argument("--target", default=None, help="対象チャンネルディレクトリ (default: 自動解決)")
    p_migrate.add_argument("--apply", action="store_true", help="実書き込み (default: dry-run)")
    p_migrate.add_argument(
        "--backup",
        dest="backup",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="channel_config.json.bak を残す (default: 有効)",
    )
    p_migrate.add_argument(
        "--delete-source",
        action="store_true",
        help="成功後に channel_config.json を削除 (default: 残す、--apply 時のみ有効)",
    )
    p_migrate.add_argument(
        "--strict",
        action="store_true",
        help="未マップキーを ConfigError 扱い (default: warning で継続)",
    )
    p_migrate.set_defaults(func=cmd_migrate)

    p_verify = sub.add_parser("verify", help="分割後を新 loader で読み込みバリデート")
    p_verify.add_argument("--target", default=None, help="対象チャンネルディレクトリ (default: 自動解決)")
    p_verify.set_defaults(func=cmd_verify)

    p_diff = sub.add_parser("diff", help="旧 JSON と分割結果の差分表示 (未マップキー検出)")
    p_diff.add_argument("--target", default=None, help="対象チャンネルディレクトリ (default: 自動解決)")
    p_diff.set_defaults(func=cmd_diff)

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
