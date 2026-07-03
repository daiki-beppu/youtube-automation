"""yt-skills — Claude Code 配布物を downstream リポに同期する。

`uv add git+https://github.com/daiki-beppu/youtube-automation` で本パッケージを
インストールしたあと、`yt-skills sync` を実行することで、wheel に同梱された
配布物 (Claude Code スキル / CLAUDE.md テンプレ) を任意のチャンネルリポジトリへ
展開できる。

Subcommands:
    list   : 同梱アセット一覧を表示
    sync   : --target に展開 (--symlink でシンボリックリンク, --force で上書き)
    diff   : 同梱版と target の差分を表示

Asset 種別 (`--asset`):
    all                 : デフォルト。下記すべての asset を一括処理する
    skills              : Claude Code スキル (`.claude/skills/`、ディレクトリ単位で 1 entry)
    claude-md           : BGM チャンネル運営方針テンプレ (`.claude/CLAUDE.md`、単一ファイル)
    workflow-cheatsheet : workflow 使い分けチートシート (`docs/workflow-cheatsheet.md`、単一ファイル)
    features            : 全 skill カタログ (`docs/features.md`、単一ファイル)
    auth-template       : OAuth client secrets テンプレート (`auth/client_secrets.template.json`、単一ファイル)

`yt-skills sync` (asset 未指定) は `--asset all` と同等で、配布物が `docs/`
にリンクを張る前提で動くため、デフォルトで全 asset を sync する設計に
なっている。skill だけ更新したい場合は `--asset skills` を明示する。

将来別種類の配布物を追加する場合は `_ASSET_SPECS` に entry を追加するだけで
list/sync/diff の各 subcommand が自動的にサポートする (kind="dir" / "file" を選ぶ)。
`--asset all` モードも追加された entry を自動的に巡回するため追加実装は不要。
"""

from __future__ import annotations

import argparse
from importlib.resources import as_file, files
from pathlib import Path
from typing import Iterable

# asset ごとの kind / wheel resource 名・開発時 fallback・デフォルト target を集約。
# (pyproject.toml の force-include で source_subdir 配下が resource_name/ に同梱される)
#
# kind="dir"  : ディレクトリ全体を 1 entry = 1 サブディレクトリとして配布。
# kind="file" : 単一ファイルを配布。source_filename が source 側のファイル名、
#               default_target が target 側のファイルパス (リネーム配布も可)。
_ASSET_SPECS: dict[str, dict[str, str]] = {
    "skills": {
        "kind": "dir",
        "resource_name": "_skills",
        "source_subdir": ".claude/skills",
        "default_target": ".claude/skills",
        "label": "スキル",
    },
    "claude-md": {
        "kind": "file",
        "resource_name": "_claude_md",
        "source_subdir": ".claude",
        "source_filename": "CLAUDE.template.md",
        "default_target": ".claude/CLAUDE.md",
        "label": "CLAUDE.md テンプレ",
    },
    "workflow-cheatsheet": {
        "kind": "file",
        "resource_name": "_docs",
        "source_subdir": "docs",
        "source_filename": "workflow-cheatsheet.md",
        "default_target": "docs/workflow-cheatsheet.md",
        "label": "workflow チートシート",
    },
    "features": {
        "kind": "file",
        "resource_name": "_docs",
        "source_subdir": "docs",
        "source_filename": "features.md",
        "default_target": "docs/features.md",
        "label": "skill カタログ",
    },
    "auth-template": {
        "kind": "file",
        "resource_name": "_auth",
        "source_subdir": "auth",
        "source_filename": "client_secrets.template.json",
        "default_target": "auth/client_secrets.template.json",
        "label": "OAuth client_secrets テンプレ",
    },
}


def _editable_root() -> Path:
    """開発時の repo root を返す。テストでは monkeypatch で差し替える。"""
    return Path(__file__).resolve().parents[4]


def _asset_root(asset: str) -> Path:
    """指定 asset の同梱ディレクトリを実体パスとして取得する。

    解決順:
        1. インストール済み wheel の `youtube_automation/<resource_name>/`
        2. リポジトリルート直下の `<source_subdir>/` (editable / 開発時)

    kind="file" の場合は同梱ファイルの **親ディレクトリ** を返す。
    実体ファイルは `_asset_root(asset) / spec["source_filename"]` で取得する。
    """
    spec = _ASSET_SPECS[asset]  # KeyError on unknown asset

    try:
        resource = files("youtube_automation").joinpath(spec["resource_name"])
        with as_file(resource) as p:
            path = Path(p)
            if path.exists():
                return path
    except (ModuleNotFoundError, FileNotFoundError):
        pass

    src_fallback = _editable_root() / spec["source_subdir"]
    if src_fallback.exists():
        return src_fallback

    raise FileNotFoundError(
        f"youtube_automation の {asset} データが見つかりません "
        f"(wheel 同梱: {spec['resource_name']}, ソース: {spec['source_subdir']})。"
    )


def _guard_target_with_all(args: argparse.Namespace) -> None:
    """`--asset all` + `--target` の組み合わせを検出して `ValueError` を raise する。

    asset ごとに default_target が異なるため、all モードで target を 1 つに固定すると
    意図しない asset (例: claude-md) がユーザー指定の skills 用 path に書き込まれる
    silent な誤動作になる。これを防ぐためのガードで、CLI 経由 (`_resolve_default_target`)
    と公開 API 直呼び (`cmd_sync` / `cmd_diff`) の両方の入口から呼ぶ。

    例外の使い分け:
      - ライブラリとして import して呼ぶ caller は `ValueError` を受け取って
        通常の Python 例外ハンドリングで処理できる (SystemExit で強制終了されない)
      - CLI 経由 (`yt-skills` コマンド) では `_resolve_default_target` が
        この `ValueError` を catch して stderr + `sys.exit(2)` に変換する
    """
    if args.asset == "all" and getattr(args, "target", None) is not None:
        raise ValueError(
            "--target は --asset all モードでは使えません "
            "(asset ごとに default_target が異なるため曖昧)。"
            " skills だけを独自 path に出すなら --asset skills --target ... のように"
            " asset を明示してください。全 asset を sync するなら --target を外してください。"
        )


def _list_entries(root: Path, kind: str = "dir", source_filename: str | None = None) -> list[str]:
    """asset 配下の entry 名を返す。

    kind="dir"  : `root.iterdir()` の名前を sort して返す。
    kind="file" : `[source_filename]` を返す (単一エントリ)。
    """
    if kind == "file":
        if source_filename is None:
            raise ValueError("kind='file' の asset には source_filename が必要です")
        return [source_filename]
    return sorted(p.name for p in root.iterdir())


def bundled_skill_names() -> list[str]:
    """`yt-skills sync --asset skills` が配布する skill 名一覧を返す。"""
    spec = _ASSET_SPECS["skills"]
    root = _asset_root("skills")
    return _list_entries(root, kind=spec["kind"], source_filename=spec.get("source_filename"))


def cmd_list(args: argparse.Namespace) -> int:
    if args.asset == "all":
        # 全 asset を巡回。dir asset → file asset の順で人間が読みやすい並び。
        # cmd_list には target がないため _guard_target_with_all は不要。
        for i, asset_name in enumerate(sorted(_ASSET_SPECS.keys())):
            if i > 0:
                print()
            cmd_list(argparse.Namespace(asset=asset_name))
        return 0
    spec = _ASSET_SPECS[args.asset]
    root = _asset_root(args.asset)
    entries = _list_entries(root, kind=spec["kind"], source_filename=spec.get("source_filename"))
    print(f"同梱{spec['label']} {len(entries)} 件 (source: {root})")
    for name in entries:
        print(f"  - {name}")
    return 0


# submodule 再エクスポート — primitives 定義後に行うことで
# submodule 側の `from youtube_automation.cli.skills_sync import ...` が解決できる。
# `as` alias は ruff F401 を抑止する canonical re-export 記法。
from youtube_automation.cli.skills_sync._ops import _copy_entry as _copy_entry  # noqa: E402, I001
from youtube_automation.cli.skills_sync._ops import _ensure_target_parent as _ensure_target_parent  # noqa: E402
from youtube_automation.cli.skills_sync._ops import _has_diff as _has_diff  # noqa: E402
from youtube_automation.cli.skills_sync._ops import _prune_orphans as _prune_orphans  # noqa: E402
from youtube_automation.cli.skills_sync._ops import _symlink_entry as _symlink_entry  # noqa: E402
from youtube_automation.cli.skills_sync._sync import cmd_sync as cmd_sync  # noqa: E402
from youtube_automation.cli.skills_sync._diff import cmd_diff as cmd_diff  # noqa: E402
from youtube_automation.cli.skills_sync._parser import _resolve_default_target as _resolve_default_target  # noqa: E402
from youtube_automation.cli.skills_sync._parser import build_parser as build_parser  # noqa: E402


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    _resolve_default_target(args)
    return args.func(args)


__all__ = ["build_parser", "bundled_skill_names", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
