"""Git-managed workflow control-plane migration for downstream channels."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Final

from youtube_automation.core.errors import ConfigError

STATE_GITIGNORE_MARKER: Final[str] = "# yt-state-git control plane (ADR-0024)"
_ROOT_HISTORY_NAMES: Final[tuple[str, ...]] = (
    "post_publish_history.json",
    "pinned_comment_history.json",
)
_SENSITIVE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "client_secret",
        "cookie",
        "password",
        "private_key",
        "refresh_token",
        "resume_session_uri",
        "resumable_session_uri",
        "upload_session_uri",
    }
)
_SENSITIVE_VALUE_MARKERS: Final[tuple[str, ...]] = (
    "-----BEGIN PRIVATE KEY-----",
    "Bearer ",
    "ya29.",
)
_MAX_CONTROL_FILE_BYTES: Final[int] = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class StateGitContext:
    channel_dir: Path
    repository: Path
    gitignore: Path
    control_files: tuple[Path, ...]


def channel_gitignore_template() -> str:
    resource = files("youtube_automation.infrastructure.resources.channel").joinpath("gitignore.template")
    return resource.read_text(encoding="utf-8")


def state_gitignore_block() -> str:
    template = channel_gitignore_template()
    marker_at = template.index(STATE_GITIGNORE_MARKER)
    return template[marker_at:].rstrip() + "\n"


def _workspace_state_gitignore_block() -> str:
    channel_lines = state_gitignore_block().splitlines()
    workspace_lines = [channel_lines[0], "!channels/", "!channels/*/"]
    workspace_lines.extend(f"!channels/*/{line.removeprefix('!')}" for line in channel_lines[1:])
    return "\n".join(workspace_lines) + "\n"


def _uses_workspace_gitignore(context: StateGitContext) -> bool:
    return context.channel_dir != context.repository and context.gitignore == context.repository / ".gitignore"


def _run_git(repository: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )


def _regular_directory(path: Path, *, label: str) -> None:
    if path.is_symlink():
        raise ConfigError(f"{label} に symlink は使えません: {path}")
    if not path.is_dir():
        raise ConfigError(f"{label} が存在しません: {path}")


def _regular_file(path: Path, *, label: str) -> None:
    if path.is_symlink():
        raise ConfigError(f"{label} に symlink は使えません: {path}")
    if not path.is_file():
        raise ConfigError(f"{label} が存在しません: {path}")


def _collection_control_files(channel_dir: Path) -> list[Path]:
    collections = channel_dir / "collections"
    if not collections.exists() and not collections.is_symlink():
        return []
    _regular_directory(collections, label="collections directory")
    discovered: list[Path] = []
    for stage in sorted(collections.iterdir(), key=lambda path: path.name):
        if stage.is_symlink():
            raise ConfigError(f"collections 配下に symlink は使えません: {stage}")
        if not stage.is_dir():
            continue
        for collection in sorted(stage.iterdir(), key=lambda path: path.name):
            if collection.is_symlink():
                raise ConfigError(f"collection に symlink は使えません: {collection}")
            if not collection.is_dir():
                continue
            state = collection / "workflow-state.json"
            if state.exists() or state.is_symlink():
                _regular_file(state, label="workflow-state.json")
                discovered.append(state)
            docs = collection / "20-documentation"
            if docs.is_symlink():
                raise ConfigError(f"20-documentation に symlink は使えません: {docs}")
            tracking = docs / "upload_tracking.json"
            if tracking.exists() or tracking.is_symlink():
                _regular_file(tracking, label="upload_tracking.json")
                discovered.append(tracking)
    return discovered


def _discover_control_files(channel_dir: Path) -> tuple[Path, ...]:
    discovered = _collection_control_files(channel_dir)
    for name in _ROOT_HISTORY_NAMES:
        path = channel_dir / name
        if path.exists() or path.is_symlink():
            _regular_file(path, label=name)
            discovered.append(path)
    return tuple(sorted(discovered))


def _contains_secret(value: object, *, key: str | None = None) -> bool:
    normalized_key = re.sub(r"(?<!^)(?=[A-Z])", "_", key or "").lower().replace("-", "_")
    key_is_sensitive = (
        normalized_key in _SENSITIVE_KEYS
        or normalized_key.endswith("_token")
        or normalized_key.endswith("_session_uri")
        or "secret" in normalized_key
    )
    if key_is_sensitive and value not in (None, "", [], {}):
        return True
    if isinstance(value, dict):
        return any(_contains_secret(child, key=str(child_key).lower()) for child_key, child in value.items())
    if isinstance(value, list):
        return any(_contains_secret(child) for child in value)
    if isinstance(value, str):
        return any(marker in value for marker in _SENSITIVE_VALUE_MARKERS)
    return False


def _validate_control_file(path: Path) -> None:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ConfigError(f"制御面JSONを検査できません: {path}") from exc
    if size > _MAX_CONTROL_FILE_BYTES:
        raise ConfigError(f"制御面JSONが上限を超えています: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigError(f"制御面JSONが不正です: {path}") from exc
    if _contains_secret(value):
        raise ConfigError(f"secretを含む可能性があるためGit管理へ移行できません: {path}")


def build_pull_context(channel_dir: Path) -> StateGitContext:
    """Resolve a channel Git boundary without reading control-plane documents."""
    raw = channel_dir.expanduser()
    if raw.is_symlink():
        raise ConfigError(f"channel directory に symlink は使えません: {raw}")
    _regular_directory(raw, label="channel directory")
    channel = raw.resolve()
    top_level = _run_git(channel, "rev-parse", "--show-toplevel")
    if top_level.returncode != 0:
        raise ConfigError(f"channel directory は Git repository 内でなければなりません: {channel}")
    repository = Path(top_level.stdout.strip()).resolve()
    if not channel.is_relative_to(repository):
        raise ConfigError(f"channel directory が Git repository 外です: {channel}")
    channel_gitignore = channel / ".gitignore"
    if channel_gitignore.exists() or channel_gitignore.is_symlink():
        _regular_file(channel_gitignore, label="channel .gitignore")
        gitignore = channel_gitignore
    elif channel.parent.name == "channels" and channel.parent.parent == repository:
        gitignore = repository / ".gitignore"
        _regular_file(gitignore, label="workspace .gitignore")
    else:
        _regular_file(channel_gitignore, label="channel .gitignore")
    return StateGitContext(channel, repository, gitignore, ())


def build_context(channel_dir: Path) -> StateGitContext:
    base = build_pull_context(channel_dir)
    control_files = _discover_control_files(base.channel_dir)
    for path in control_files:
        _validate_control_file(path)
    return StateGitContext(base.channel_dir, base.repository, base.gitignore, control_files)


def _repo_relative(context: StateGitContext, path: Path) -> str:
    return path.relative_to(context.repository).as_posix()


def _read_gitignore(context: StateGitContext) -> str:
    try:
        return context.gitignore.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"channel .gitignoreを読み取れません: {context.gitignore}") from exc


def _changed_paths(context: StateGitContext, *, cached: bool) -> set[str]:
    args = ["diff", "--name-only"]
    if cached:
        args.insert(1, "--cached")
    result = _run_git(context.repository, *args, "--")
    if result.returncode != 0:
        raise ConfigError("Gitの変更状態を確認できません")
    return set(result.stdout.splitlines())


def _untracked_paths(context: StateGitContext) -> set[str]:
    result = _run_git(context.repository, "ls-files", "--others", "--exclude-standard")
    if result.returncode != 0:
        raise ConfigError("Gitの未追跡状態を確認できません")
    return set(result.stdout.splitlines())


def validate_migration_worktree(context: StateGitContext) -> None:
    allowed = {
        _repo_relative(context, context.gitignore),
        *(_repo_relative(context, path) for path in context.control_files),
    }
    marker_present = STATE_GITIGNORE_MARKER in _read_gitignore(context)
    unstaged = _changed_paths(context, cached=False)
    staged = _changed_paths(context, cached=True)
    untracked = _untracked_paths(context)
    unrelated = (unstaged | staged | untracked) - allowed
    if unrelated or (not marker_present and (_repo_relative(context, context.gitignore) in unstaged | staged)):
        raise ConfigError("作業ツリーに移行対象外の staged / dirty / untracked 変更があります")


def _is_tracked(context: StateGitContext, path: Path) -> bool:
    result = _run_git(context.repository, "ls-files", "--error-unmatch", "--", _repo_relative(context, path))
    return result.returncode == 0


def _policy_probe_paths(context: StateGitContext) -> tuple[str, ...]:
    probe_root = context.channel_dir / "collections" / "planning" / "__yt_state_git_probe__"
    return (
        _repo_relative(context, probe_root / "workflow-state.json"),
        _repo_relative(context, probe_root / "20-documentation" / "upload_tracking.json"),
        _repo_relative(context, context.channel_dir / "post_publish_history.json"),
        _repo_relative(context, context.channel_dir / "pinned_comment_history.json"),
    )


def _ignored_policy_paths(context: StateGitContext) -> tuple[str, ...]:
    ignored: list[str] = []
    for relative in _policy_probe_paths(context):
        result = _run_git(context.repository, "check-ignore", "--no-index", "--quiet", "--", relative)
        if result.returncode == 0:
            ignored.append(relative)
        elif result.returncode != 1:
            raise ConfigError(f"Git ignore状態を確認できません: {relative}")
    return tuple(ignored)


def check_state_git(context: StateGitContext) -> tuple[str, ...]:
    diagnostics: list[str] = []
    if not _uses_workspace_gitignore(context) and STATE_GITIGNORE_MARKER not in _read_gitignore(context):
        diagnostics.append(f"Git管理ポリシーがありません: {_repo_relative(context, context.gitignore)}")
    for relative in _ignored_policy_paths(context):
        diagnostics.append(f"制御面JSONがignoreされています: {relative}")
    changed = _changed_paths(context, cached=False) | _changed_paths(context, cached=True)
    untracked = _untracked_paths(context)
    for path in context.control_files:
        relative = _repo_relative(context, path)
        if not _is_tracked(context, path):
            diagnostics.append(f"未追跡の制御面JSONです: {relative}")
        elif relative in changed:
            diagnostics.append(f"未commitの制御面JSONです: {relative}")
    gitignore_relative = _repo_relative(context, context.gitignore)
    if gitignore_relative in changed or gitignore_relative in untracked:
        diagnostics.append(f"Git管理ポリシーが未commitです: {gitignore_relative}")
    unrelated = (changed | untracked) - {
        gitignore_relative,
        *(_repo_relative(context, path) for path in context.control_files),
    }
    if unrelated:
        diagnostics.append("作業ツリーに未commitの変更があります")
    return tuple(diagnostics)


def planned_gitignore(context: StateGitContext) -> str:
    current = _read_gitignore(context)
    block = _workspace_state_gitignore_block() if _uses_workspace_gitignore(context) else state_gitignore_block()
    if current.endswith(block):
        return current
    if block in current:
        current = current.replace(block, "").rstrip() + "\n"
    separator = "" if not current or current.endswith("\n\n") else "\n" if current.endswith("\n") else "\n\n"
    return current + separator + block


def _atomic_write(path: Path, text: str) -> None:
    mode = path.stat().st_mode & 0o777
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


def apply_state_git(context: StateGitContext) -> None:
    validate_migration_worktree(context)
    before = context.gitignore.read_bytes()
    planned = planned_gitignore(context)
    try:
        if planned != before.decode("utf-8"):
            _atomic_write(context.gitignore, planned)
        paths = [context.gitignore, *context.control_files]
        ignored_paths = _ignored_policy_paths(context)
        if ignored_paths:
            raise ConfigError(f"Git ignoreを解除できません: {ignored_paths[0]}")
        added = _run_git(context.repository, "add", "--", *(_repo_relative(context, path) for path in paths))
        if added.returncode != 0:
            raise ConfigError("Git indexへ制御面JSONを追加できません")
    except (ConfigError, OSError) as exc:
        if context.gitignore.read_bytes() != before:
            _atomic_write(context.gitignore, before.decode("utf-8"))
        raise ConfigError("state Git管理への移行に失敗しました。既存.gitignoreを復元しました") from exc
