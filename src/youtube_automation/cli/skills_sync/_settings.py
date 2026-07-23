"""Claude Code settings の安全な JSON merge。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


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


def missing_hooks(target: dict[str, object], template: dict[str, object]) -> list[tuple[str, dict[str, object]]]:
    target_hooks = target.get("hooks", {})
    template_hooks = template.get("hooks", {})
    if not isinstance(target_hooks, dict) or not isinstance(template_hooks, dict):
        raise ValueError("hooks は object である必要があります")
    existing_by_event: dict[str, set[tuple[object, object, object]]] = {}
    for event, groups in target_hooks.items():
        if not isinstance(groups, list):
            raise ValueError("hooks の event は配列である必要があります")
        signatures = existing_by_event.setdefault(str(event), set())
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks", []), list):
                raise ValueError("hook group の形式が不正です")
            signatures.update(_hook_signature(group.get("matcher"), hook) for hook in group.get("hooks", []))
    missing: list[tuple[str, dict[str, object]]] = []
    for event, groups in template_hooks.items():
        if not isinstance(groups, list):
            raise ValueError("template hooks の event は配列である必要があります")
        signatures = existing_by_event.setdefault(str(event), set())
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks", []), list):
                raise ValueError("template hook group の形式が不正です")
            matcher = group.get("matcher")
            hooks = [hook for hook in group["hooks"] if _hook_signature(matcher, hook) not in signatures]
            if hooks:
                missing.append((event, {"matcher": matcher, "hooks": hooks}))
                signatures.update(_hook_signature(matcher, hook) for hook in hooks)
    return missing


def sync_settings_asset(spec: dict[str, str], root: Path, target: Path, args: argparse.Namespace) -> int:
    if args.symlink:
        print("  [warn] settings は JSON merge のため --symlink を無視します", file=sys.stderr)
    try:
        template = read_json_object(root / spec["source_filename"])
        merged = read_json_object(target, missing_ok=True)
        missing_allow = merge_unique_strings(merged, template, "allow")
        missing_deny = merge_unique_strings(merged, template, "deny")
        hooks = missing_hooks(merged, template)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"  [error] settings をマージできません: {exc}", file=sys.stderr)
        return 1

    for event, group in hooks:
        for hook in group["hooks"]:
            print(f"  hook 追加候補: {event} / {group.get('matcher')} / {hook.get('type')} / {hook.get('command')}")
    accept_hooks = bool(getattr(args, "accept_hooks", False))
    if hooks and not accept_hooks and getattr(sys.stdin, "isatty", lambda: False)():
        accept_hooks = input("  hook を追加しますか? [y/N] ").strip().lower() in {"y", "yes"}
    if hooks and accept_hooks:
        merged_hooks = merged.setdefault("hooks", {})
        assert isinstance(merged_hooks, dict)
        for event, group in hooks:
            merged_hooks.setdefault(event, []).append(group)
    elif hooks:
        print("  [skip] hook 追加は未承認です (--accept-hooks で承認)")

    changed = bool(missing_allow or missing_deny or (hooks and accept_hooks) or not target.exists())
    result = "created" if not target.exists() else "updated" if changed else "unchanged"
    if changed and not args.dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.tmp")
        tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(target)
    prefix = "[dry-run] " if args.dry_run else ""
    print(f"  {prefix}{result:>8}: {target}")
    return 0
