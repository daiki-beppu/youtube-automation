"""Workspace の channel を独立 repository 用 directory へコピーする。"""

from __future__ import annotations

import argparse
import fnmatch
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.commands.channel.channel_import import SLUG_PATTERN, _validate_config
from youtube_automation.infrastructure.auth.client_secrets import template_bytes

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_VALIDATION = 3
EXIT_CONFLICT = 4

_EXCLUDED_DIRECTORIES = {".automation-run", ".tmp", "__pycache__"}
_EXCLUDED_FILES = ("*.lock", ".collection-serve-*.pid", ".DS_Store")
_GENERATED_FILES = {Path(".gitignore"), Path("auth/client_secrets.template.json")}
_GITIGNORE = """# yt-channel-export single-repository policy
.env
auth/client_secrets.json
auth/token*.json
collections/**/*.mp3
collections/**/*.wav
collections/**/*.mp4
assets/stock/**/*.mp3
"""


def _excluded(relative: Path, *, directory: bool) -> bool:
    if any(part in _EXCLUDED_DIRECTORIES for part in relative.parts):
        return True
    if directory:
        return False
    return (
        relative.name == ".env"
        or relative in _GENERATED_FILES
        or any(fnmatch.fnmatch(relative.name, pattern) for pattern in _EXCLUDED_FILES)
    )


def _copy_plan(source: Path) -> list[tuple[Path, Path, int]]:
    plan: list[tuple[Path, Path, int]] = []
    for root, directories, files in os.walk(source, followlinks=False):
        root_path = Path(root)
        retained: list[str] = []
        for name in directories:
            path = root_path / name
            relative = path.relative_to(source)
            if _excluded(relative, directory=True):
                continue
            if path.is_symlink():
                _validated_target(path, source)
            retained.append(name)
        directories[:] = retained
        for name in files:
            path = root_path / name
            relative = path.relative_to(source)
            if _excluded(relative, directory=False):
                continue
            copy_source = _validated_target(path, source) if path.is_symlink() else path
            if not copy_source.is_file():
                raise ValueError(f"通常ファイルではありません: {path}")
            plan.append((path, relative, copy_source.stat().st_size))
    return plan


def _validated_target(path: Path, source: Path) -> Path:
    try:
        target = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ValueError(f"壊れた、または循環する symlink はコピーできません: {path}") from error
    if not target.is_relative_to(source.resolve()) or not target.is_file():
        raise ValueError(f"内部の通常ファイル以外を指す symlink はコピーできません: {path} -> {target}")
    target_relative = target.relative_to(source.resolve())
    if _excluded(target_relative, directory=False):
        raise ValueError(f"コピー対象外を指す symlink はコピーできません: {path} -> {target}")
    return target


def _dirty(workspace: Path, slug: str) -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", f"channels/{slug}"],
        cwd=workspace,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError("workspace の git status を確認できません")
    return bool(result.stdout.strip())


def _write_templates(staging: Path) -> None:
    (staging / ".gitignore").write_text(_GITIGNORE, encoding="utf-8")
    auth = staging / "auth"
    auth.mkdir(exist_ok=True)
    (auth / "client_secrets.template.json").write_bytes(template_bytes())


def export_channel(
    slug: str,
    destination: Path,
    *,
    workspace: Path,
    allow_dirty: bool = False,
    dry_run: bool = False,
) -> int:
    workspace = workspace.expanduser().resolve()
    if not SLUG_PATTERN.fullmatch(slug):
        print("[error] slug は小文字英数字と単一ハイフンだけで指定してください", file=sys.stderr)
        return EXIT_USAGE
    source = workspace / "channels" / slug
    if source.is_symlink() or not (source / "config/channel").is_dir():
        print(f"[error] channel が見つかりません: {source}", file=sys.stderr)
        return EXIT_USAGE
    destination = destination.expanduser().absolute()
    try:
        destination.resolve(strict=False).relative_to(workspace)
    except ValueError:
        pass
    else:
        print("[error] dest は workspace の外を指定してください", file=sys.stderr)
        return EXIT_USAGE
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        print(f"[error] dest が空ではありません（上書きしません）: {destination}", file=sys.stderr)
        return EXIT_CONFLICT
    if not destination.parent.is_dir():
        print(f"[error] dest の親 directory が存在しません: {destination.parent}", file=sys.stderr)
        return EXIT_USAGE
    try:
        if not allow_dirty and _dirty(workspace, slug):
            print("[error] channel に未 commit の変更があります（--allow-dirty で override）", file=sys.stderr)
            return EXIT_USAGE
        plan = _copy_plan(source)
    except (OSError, ValueError) as error:
        print(f"[error] export の検証に失敗しました: {error}", file=sys.stderr)
        return EXIT_VALIDATION
    count, size = len(plan), sum(item[2] for item in plan)
    print(f"export plan: {source} -> {destination} ({count} files, {size} bytes)")
    if (source / ".env").exists():
        print("[warning] .env は不要のはずなので copy しません")
    if dry_run:
        return EXIT_OK

    staging = Path(tempfile.mkdtemp(prefix=f".channel-export-{slug}-", dir=destination.parent))
    destination_was_empty = destination.is_dir()
    try:
        for copy_source, relative, _ in plan:
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(_validated_target(copy_source, source) if copy_source.is_symlink() else copy_source, target)
        copied_count = len(plan)
        copied_size = sum((staging / relative).stat().st_size for _, relative, _ in plan)
        if (copied_count, copied_size) != (count, size):
            raise ValueError("copy 前後のファイル数または総サイズが一致しません")
        _validate_config(staging)
        _write_templates(staging)
        if destination_was_empty:
            destination.rmdir()
        staging.rename(destination)
    except (OSError, ValueError) as error:
        shutil.rmtree(staging, ignore_errors=True)
        if destination_was_empty and not destination.exists():
            destination.mkdir()
        print(f"[error] export を rollback しました: {error}", file=sys.stderr)
        return EXIT_VALIDATION

    print(f"export: OK ({count} files, {size} bytes)")
    print("dest で `/setup --tool` を実行してください。")
    print(
        "参考: uv init; uv add git+https://github.com/daiki-beppu/youtube-automation; uv run yt-skills sync; git init"
    )
    print("案内: bootstrap 後に `uv run yt-doctor` と workflow-state の path を確認してください。")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug", help="workspace の channels/<slug> にある channel slug")
    parser.add_argument("dest", type=Path, help="workspace 外の、存在しないか空の出力 directory")
    parser.add_argument("--allow-dirty", action="store_true", help="未 commit（untracked を含む）の source を許可する")
    parser.add_argument("--dry-run", action="store_true", help="copy せず対象ファイル数と総サイズだけ表示する")
    return parser


def run(args: argparse.Namespace) -> int:
    return export_channel(
        args.slug,
        args.dest,
        workspace=Path.cwd(),
        allow_dirty=args.allow_dirty,
        dry_run=args.dry_run,
    )


def main(argv: list[str] | None = None) -> int:
    return run_cli(build_parser, run, argv)


if __name__ == "__main__":
    raise SystemExit(main())
