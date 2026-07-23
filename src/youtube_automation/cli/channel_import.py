"""既存の単一 channel repository を multi-channel workspace へコピーする。"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import unicodedata
from collections.abc import Iterable
from pathlib import Path

from youtube_automation.configuration import find_workspace_root, load_config, reset
from youtube_automation.utils.exceptions import ConfigError

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_VALIDATION = 3
EXIT_CONFLICT = 4

PER_CHANNEL_PATHS = (
    Path("config"),
    Path("auth"),
    Path("data"),
    Path("collections"),
    Path("assets"),
    Path("branding"),
    Path("research"),
    Path("docs/channel"),
    Path("docs/benchmarks"),
)
REQUIRED_CONFIG_FILES = ("meta.json", "content.json", "youtube.json")
SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
GITIGNORE_MARKER = "# yt-channel-import workspace policy"
_AUDIO_SUFFIXES = ("mp3", "m4a", "wav", "flac", "aac", "ogg")
_COLLECTION_MEDIA_SUFFIXES = (
    *_AUDIO_SUFFIXES,
    "mp4",
    "mov",
    "webm",
    "mkv",
    "png",
    "jpg",
    "jpeg",
    "webp",
    "gif",
    "zip",
)


def _workspace_root(start: Path) -> Path:
    detected = find_workspace_root(start)
    if detected is not None:
        return detected
    current = start.expanduser().resolve()
    for parent in (current, *current.parents):
        if (parent / "channels").is_dir():
            return parent
    return current


def _slugify(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")


def _propose_slug(source: Path) -> str:
    meta_path = source / "config" / "channel" / "meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        meta = {}
    channel = meta.get("channel") if isinstance(meta, dict) else None
    candidates: list[object] = []
    if isinstance(channel, dict):
        candidates.extend(
            (str(channel.get("youtube_handle", "")).lstrip("@"), channel.get("short"), channel.get("name"))
        )
    candidates.append(source.name)
    for candidate in candidates:
        if isinstance(candidate, str) and (slug := _slugify(candidate)) and SLUG_PATTERN.fullmatch(slug):
            return slug
    raise ValueError("config/channel/meta.json から有効な channel slug を提案できません。--slug を指定してください")


def _validated_slug(value: str) -> str:
    if not SLUG_PATTERN.fullmatch(value):
        raise ValueError("slug は小文字英数字と単一ハイフンだけで指定してください（例: ambient-island）")
    return value


def _warn_source_residue(source: Path) -> None:
    env_path = source / ".env"
    if env_path.exists():
        print(f"[warning] 移行元に .env が残っています（コピーしません）: {env_path}", file=sys.stderr)
        try:
            if re.search(r"(?m)^\s*CHANNEL_DIR\s*=", env_path.read_text(encoding="utf-8")):
                print("[warning] 移行元 .env の CHANNEL_DIR は workspace 運用前に削除してください", file=sys.stderr)
        except OSError as error:
            print(f"[warning] 移行元 .env を確認できません: {error}", file=sys.stderr)
    configured = os.environ.get("CHANNEL_DIR")
    if configured:
        try:
            points_to_source = Path(configured).expanduser().resolve() == source
        except OSError:
            points_to_source = False
        if points_to_source:
            print(
                "[warning] 現在の CHANNEL_DIR が移行元を指しています。workspace 運用前に解除してください",
                file=sys.stderr,
            )


def _validated_symlink_target(path: Path, *, source: Path, selected_roots: tuple[Path, ...]) -> Path:
    """Return a safe regular-file target contained by the selected source tree."""
    try:
        target = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ValueError(f"壊れた、または循環する symlink はコピーできません: {path}") from error
    if not target.is_relative_to(source):
        raise ValueError(f"移行元 repository 外を指す symlink はコピーできません: {path} -> {target}")
    if not any(target.is_relative_to(root) for root in selected_roots):
        raise ValueError(f"コピー対象外を指す symlink はコピーできません: {path} -> {target}")
    if not target.is_file():
        raise ValueError(f"通常ファイル以外を指す symlink はコピーできません: {path} -> {target}")
    return target


def _validate_symlinks(path: Path, *, source: Path, selected_roots: tuple[Path, ...]) -> None:
    if path.is_symlink():
        _validated_symlink_target(path, source=source, selected_roots=selected_roots)
        return
    if not path.is_dir():
        return
    for candidate in path.rglob("*"):
        if candidate.is_symlink():
            _validated_symlink_target(candidate, source=source, selected_roots=selected_roots)


def _copy_validated_file(source: Path, destination: Path, *, repository: Path, selected_roots: tuple[Path, ...]) -> str:
    copy_source = (
        _validated_symlink_target(source, source=repository, selected_roots=selected_roots)
        if source.is_symlink()
        else source
    )
    return shutil.copy2(copy_source, destination)


def _copy_per_channel_paths(source: Path, temporary: Path) -> list[str]:
    copied: list[str] = []
    selected_roots = tuple(
        origin.resolve(strict=True)
        for relative in PER_CHANNEL_PATHS
        if (origin := source / relative).exists() and not origin.is_symlink()
    )
    for relative in PER_CHANNEL_PATHS:
        origin = source / relative
        if not origin.exists():
            continue
        current = source
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise ValueError(f"symlink はコピーできません: {current}")
        _validate_symlinks(origin, source=source, selected_roots=selected_roots)
        destination = temporary / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if origin.is_dir():
            shutil.copytree(
                origin,
                destination,
                copy_function=lambda source_path, destination_path: _copy_validated_file(
                    Path(source_path),
                    Path(destination_path),
                    repository=source,
                    selected_roots=selected_roots,
                ),
            )
        elif origin.is_file():
            shutil.copy2(origin, destination)
        else:
            raise ValueError(f"通常ファイルまたは directory ではありません: {origin}")
        copied.append(relative.as_posix())
    return copied


def _validate_config(channel_root: Path) -> None:
    config_dir = channel_root / "config" / "channel"
    missing = [name for name in REQUIRED_CONFIG_FILES if not (config_dir / name).is_file()]
    if missing:
        raise ValueError(f"必須 config が不足しています: {', '.join(missing)}")

    previous_cwd = Path.cwd()
    previous_channel_dir = os.environ.get("CHANNEL_DIR")
    previous_channel = os.environ.get("CHANNEL")
    try:
        os.chdir(channel_root)
        os.environ["CHANNEL_DIR"] = str(channel_root)
        os.environ.pop("CHANNEL", None)
        reset()
        load_config()
    finally:
        reset()
        os.chdir(previous_cwd)
        if previous_channel_dir is None:
            os.environ.pop("CHANNEL_DIR", None)
        else:
            os.environ["CHANNEL_DIR"] = previous_channel_dir
        if previous_channel is None:
            os.environ.pop("CHANNEL", None)
        else:
            os.environ["CHANNEL"] = previous_channel


def _gitignore_block() -> str:
    lines = [
        GITIGNORE_MARKER,
        "channels/*/auth/client_secrets.json",
        "channels/*/auth/token*.json",
    ]
    lines.extend(f"channels/*/collections/**/*.{suffix}" for suffix in _COLLECTION_MEDIA_SUFFIXES)
    lines.extend(f"channels/*/assets/stock/**/*.{suffix}" for suffix in _AUDIO_SUFFIXES)
    return "\n".join(lines) + "\n"


def _scaffold_workspace(workspace: Path) -> None:
    (workspace / "channels").mkdir(parents=True, exist_ok=True)
    ignore_path = workspace / ".gitignore"
    if ignore_path.is_symlink():
        raise ValueError(f"workspace .gitignore に symlink は使えません: {ignore_path}")
    existing = ignore_path.read_text(encoding="utf-8") if ignore_path.exists() else ""
    if GITIGNORE_MARKER in existing:
        return
    separator = "" if not existing or existing.endswith("\n") else "\n"
    if existing and not existing.endswith("\n\n"):
        separator += "\n"
    ignore_path.write_text(existing + separator + _gitignore_block(), encoding="utf-8")


def _auth_summary(target: Path) -> tuple[str, str]:
    auth = target / "auth"
    client = auth / "client_secrets.json"
    tokens = sorted(auth.glob("token*.json")) if auth.is_dir() else []
    client_text = client.relative_to(target).as_posix() if client.is_file() else "missing"
    token_text = ", ".join(path.relative_to(target).as_posix() for path in tokens) or "missing"
    return client_text, token_text


def import_channel(source: Path, *, slug: str | None, workspace: Path, confirm: bool = True) -> int:
    source = source.expanduser()
    if source.is_symlink() or not source.is_dir():
        print(f"[error] 移行元は symlink でない directory を指定してください: {source}", file=sys.stderr)
        return EXIT_USAGE
    source = source.resolve()
    try:
        if slug is None:
            slug = _propose_slug(source)
            print(f"提案 channel slug: {slug}")
            if confirm:
                try:
                    accepted = input(f"'{slug}' で workspace に取り込みますか? [y/N]: ").strip().lower()
                except EOFError:
                    accepted = ""
                if accepted not in {"y", "yes"}:
                    print("[error] 取り込みを中止しました。--slug で明示指定できます", file=sys.stderr)
                    return EXIT_USAGE
        slug = _validated_slug(slug)
    except ValueError as error:
        print(f"[error] {error}", file=sys.stderr)
        return EXIT_USAGE

    workspace = workspace.expanduser().resolve()
    try:
        workspace.relative_to(source)
    except ValueError:
        pass
    else:
        print("[error] workspace は移行元 repository の外側に作成してください", file=sys.stderr)
        return EXIT_USAGE
    target = workspace / "channels" / slug
    if target.exists() or target.is_symlink():
        print(f"[error] 取り込み先が既に存在します（上書きしません）: {target}", file=sys.stderr)
        return EXIT_CONFLICT

    _warn_source_residue(source)
    channels_root = workspace / "channels"
    if channels_root.is_symlink():
        print(f"[error] workspace channels に symlink は使えません: {channels_root}", file=sys.stderr)
        return EXIT_VALIDATION
    channels_created = not channels_root.exists()
    temporary = Path(tempfile.mkdtemp(prefix=f".channel-import-{slug}-", dir=workspace))
    try:
        copied = _copy_per_channel_paths(source, temporary)
        _validate_config(temporary)
        _scaffold_workspace(workspace)
        temporary.rename(target)
    except (ConfigError, OSError, ValueError) as error:
        shutil.rmtree(temporary, ignore_errors=True)
        if channels_created:
            try:
                channels_root.rmdir()
            except OSError:
                pass
        print(f"[error] 取り込みを rollback しました: {error}", file=sys.stderr)
        return EXIT_VALIDATION

    client, tokens = _auth_summary(target)
    print(f"import: OK ({source} -> {target})")
    print(f"copied: {', '.join(copied) or '(none)'}")
    print("config load: OK")
    print(f"auth client: {client}")
    print(f"auth token: {tokens}")
    print("shared files はコピーしていません。workspace ルートで `uv run yt-skills sync` を 1 回実行してください。")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-channel-import",
        description="既存の単一 channel repository を現在の workspace へコピーし、config を検証する。",
    )
    parser.add_argument("source", type=Path, help="既存 channel repository の path（move せずそのまま残す）")
    parser.add_argument("--slug", help="取り込み先 channels/<slug>。省略時は meta.json から提案して確認する")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return import_channel(args.source, slug=args.slug, workspace=_workspace_root(Path.cwd()))


if __name__ == "__main__":
    raise SystemExit(main())
