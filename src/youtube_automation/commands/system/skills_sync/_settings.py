"""Claude Code settings の安全な JSON merge。"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

_KNOWN_REPLACED_HOOK_COMMANDS = {
    "uv run yt-progress-hook": 'uv run --project "$CLAUDE_PROJECT_DIR" yt-progress-hook',
    'for f in $CLAUDE_FILE_PATHS; do case "$f" in '
    "*auth/client_secrets.json|*auth/token.json|*.env) "
    'echo "BLOCKED: $f は AI から直接編集禁止。専用ツール経由で更新してください" >&2; '
    "exit 2;; esac; done": 'python3 "$CLAUDE_PROJECT_DIR/.claude/skills/automation/references/guard_secret_edit.py"',
}

_KNOWN_REMOVED_HOOK_COMMANDS = frozenset(
    {
        'for f in $CLAUDE_FILE_PATHS; do case "$f" in '
        "channels|channels/*|*/channels|*/channels/*|collections|collections/*|*/collections|*/collections/*|"
        "config/channel|config/channel/*|*/config/channel|*/config/channel/*|assets|assets/*|*/assets|*/assets/*|"
        "data|data/*|*/data|*/data/*|auth|auth/*|*/auth|*/auth/*) "
        "uv run yt-workspace-guard check $CLAUDE_FILE_PATHS; exit $?;; esac; done; exit 0",
        "uv run yt-workspace-guard context",
        *_KNOWN_REPLACED_HOOK_COMMANDS,
    }
)


def read_json_object(path: Path, *, missing_ok: bool = False) -> dict[str, object]:
    if missing_ok and not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root は object である必要があります: {path}")
    return value


def merge_unique_strings(target: dict[str, object], template: dict[str, object], key: str) -> list[str]:
    target_permissions = target.setdefault("permissions", {})
    template_permissions = template.get("permissions", {})
    if not isinstance(target_permissions, dict) or not isinstance(template_permissions, dict):
        raise ValueError("permissions は object である必要があります")
    current = target_permissions.setdefault(key, [])
    additions = template_permissions.get(key, [])
    if not isinstance(current, list) or not all(isinstance(v, str) for v in current):
        raise ValueError(f"permissions.{key} は文字列配列である必要があります")
    if not isinstance(additions, list) or not all(isinstance(v, str) for v in additions):
        raise ValueError(f"template の permissions.{key} は文字列配列である必要があります")
    missing = [v for v in additions if v not in current]
    current.extend(missing)
    return missing


def _hook_signature(matcher: object, hook: object) -> tuple[object, object, object]:
    return (matcher, hook.get("type"), hook.get("command")) if isinstance(hook, dict) else (matcher, None, None)


def _index_existing_hooks(
    target_hooks: dict[str, object],
) -> tuple[
    dict[str, set[tuple[object, object, object]]],
    dict[tuple[object, object, object], dict[str, object]],
]:
    existing_by_event: dict[str, set[tuple[object, object, object]]] = {}
    replacements: dict[tuple[object, object, object], dict[str, object]] = {}
    for event, groups in target_hooks.items():
        if not isinstance(groups, list):
            raise ValueError("hooks の event は配列である必要があります")
        signatures = existing_by_event.setdefault(str(event), set())
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks", []), list):
                raise ValueError("hook group の形式が不正です")
            signatures.update(_hook_signature(group.get("matcher"), hook) for hook in group.get("hooks", []))
            for hook in group.get("hooks", []):
                if not isinstance(hook, dict) or hook.get("type") != "command":
                    continue
                replacement = _KNOWN_REPLACED_HOOK_COMMANDS.get(hook.get("command"))
                if replacement is not None:
                    replacements[(event, group.get("matcher"), replacement)] = {**hook, "command": replacement}
    return existing_by_event, replacements


def missing_hooks(target: dict[str, object], template: dict[str, object]) -> list[tuple[str, dict[str, object]]]:
    target_hooks = target.get("hooks", {})
    template_hooks = template.get("hooks", {})
    if not isinstance(target_hooks, dict) or not isinstance(template_hooks, dict):
        raise ValueError("hooks は object である必要があります")
    existing_by_event, replacements = _index_existing_hooks(target_hooks)
    missing: list[tuple[str, dict[str, object]]] = []
    for event, groups in template_hooks.items():
        if not isinstance(groups, list):
            raise ValueError("template hooks の event は配列である必要があります")
        signatures = existing_by_event.setdefault(str(event), set())
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks", []), list):
                raise ValueError("template hook group の形式が不正です")
            matcher = group.get("matcher")
            hooks = [
                {**hook, **replacements.get((event, matcher, hook.get("command")), {})}
                if isinstance(hook, dict)
                else hook
                for hook in group["hooks"]
                if _hook_signature(matcher, hook) not in signatures
            ]
            if hooks:
                missing.append((event, {"matcher": matcher, "hooks": hooks}))
                signatures.update(_hook_signature(matcher, hook) for hook in hooks)
    return missing


def removed_hooks(target: dict[str, object]) -> list[tuple[str, object, str]]:
    target_hooks = target.get("hooks", {})
    if not isinstance(target_hooks, dict):
        raise ValueError("hooks は object である必要があります")
    removed: list[tuple[str, object, str]] = []
    for event, groups in target_hooks.items():
        if not isinstance(groups, list):
            raise ValueError("hooks の event は配列である必要があります")
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks", []), list):
                raise ValueError("hook group の形式が不正です")
            for hook in group["hooks"]:
                if isinstance(hook, dict) and hook.get("command") in _KNOWN_REMOVED_HOOK_COMMANDS:
                    removed.append((str(event), group.get("matcher"), str(hook["command"])))
    return removed


def _prune_removed_hooks(target: dict[str, object]) -> None:
    target_hooks = target.get("hooks")
    assert isinstance(target_hooks, dict)
    for event in list(target_hooks):
        groups = target_hooks[event]
        assert isinstance(groups, list)
        retained_groups: list[object] = []
        for group in groups:
            assert isinstance(group, dict)
            hooks = group.get("hooks", [])
            assert isinstance(hooks, list)
            group["hooks"] = [
                hook
                for hook in hooks
                if not (isinstance(hook, dict) and hook.get("command") in _KNOWN_REMOVED_HOOK_COMMANDS)
            ]
            if group["hooks"]:
                retained_groups.append(group)
        if retained_groups:
            target_hooks[event] = retained_groups
        else:
            del target_hooks[event]
    if not target_hooks:
        target.pop("hooks", None)


@dataclass(frozen=True)
class _SettingsChanges:
    merged: dict[str, object]
    missing_allow: list[str]
    missing_deny: list[str]
    hooks: list[tuple[str, dict[str, object]]]
    removals: list[tuple[str, object, str]]


def _settings_changes(template_path: Path, target: Path) -> _SettingsChanges:
    template = read_json_object(template_path)
    merged = read_json_object(target, missing_ok=True)
    return _SettingsChanges(
        merged=merged,
        missing_allow=merge_unique_strings(merged, template, "allow"),
        missing_deny=merge_unique_strings(merged, template, "deny"),
        hooks=missing_hooks(merged, template),
        removals=removed_hooks(merged),
    )


def _report_hook_candidates(changes: _SettingsChanges) -> None:
    for event, group in changes.hooks:
        group_hooks = group["hooks"]
        assert isinstance(group_hooks, list)
        for hook in group_hooks:
            assert isinstance(hook, dict)
            print(
                f"  hook 追加候補: hooks.{event} / {group.get('matcher')} / {hook.get('type')} / {hook.get('command')}"
            )
    for event, matcher, command in changes.removals:
        print(f"  hook 除去候補: hooks.{event} / {matcher} / command / {command}")


def _hooks_accepted(args: argparse.Namespace, *, has_changes: bool) -> bool:
    accepted = bool(getattr(args, "accept_hooks", False))
    if not has_changes or accepted or not getattr(sys.stdin, "isatty", lambda: False)():
        return accepted
    return input("  hook の追加・除去を適用しますか? [y/N] ").strip().lower() in {"y", "yes"}


def _apply_hook_changes(changes: _SettingsChanges, *, accepted: bool) -> None:
    if not accepted:
        if changes.hooks:
            print("  [skip] hook 追加は未承認です (--accept-hooks で承認)")
        if changes.removals:
            print("  [skip] hook 除去は未承認です (--accept-hooks で承認)")
        return
    if changes.removals:
        _prune_removed_hooks(changes.merged)
    if changes.hooks:
        merged_hooks = changes.merged.setdefault("hooks", {})
        assert isinstance(merged_hooks, dict)
        for event, group in changes.hooks:
            merged_hooks.setdefault(event, []).append(group)


def _write_settings(target: Path, merged: dict[str, object]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp")
    tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(target)


def sync_settings_asset(spec: dict[str, str], root: Path, target: Path, args: argparse.Namespace) -> int:
    if args.symlink:
        print("  [warn] settings は JSON merge のため --symlink を無視します", file=sys.stderr)
    try:
        changes = _settings_changes(root / spec["source_filename"], target)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"  [error] settings をマージできません: {exc}", file=sys.stderr)
        return 1

    _report_hook_candidates(changes)
    hook_changes = bool(changes.hooks or changes.removals)
    accept_hooks = _hooks_accepted(args, has_changes=hook_changes)
    _apply_hook_changes(changes, accepted=accept_hooks)
    changed = bool(
        changes.missing_allow or changes.missing_deny or (hook_changes and accept_hooks) or not target.exists()
    )
    result = "created" if not target.exists() else "updated" if changed else "unchanged"
    if changed and not args.dry_run:
        _write_settings(target, changes.merged)
    prefix = "[dry-run] " if args.dry_run else ""
    print(f"  {prefix}{result:>8}: {target}")
    return 0
