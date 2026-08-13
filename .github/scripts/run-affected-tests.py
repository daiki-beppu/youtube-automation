#!/usr/bin/env python3
"""worktree の変更pathへ共通selectorを適用してpytestを安全に実行する。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Final

SELECTOR: Final = Path(".github/scripts/select-affected-tests.py")


def _git(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        capture_output=True,
        text=True,
        check=check,
    )


def _resolves_commit(reference: str) -> bool:
    if not reference:
        return False
    return _git("rev-parse", "--verify", "--quiet", f"{reference}^{{commit}}", check=False).returncode == 0


def _diff_base() -> str | None:
    explicit = os.environ.get("PRE_PUSH_DIFF_BASE", "")
    candidates = [explicit] if explicit else ["origin/main", "main"]
    for reference in candidates:
        if _resolves_commit(reference):
            return _git("merge-base", reference, "HEAD").stdout.strip()
    return None


def _lines(result: subprocess.CompletedProcess[str]) -> list[str]:
    return [line for line in result.stdout.splitlines() if line]


def changed_paths() -> list[str]:
    paths: set[str] = set()
    base = _diff_base()
    if base is None:
        return []
    paths.update(_lines(_git("diff", "--name-only", f"{base}...HEAD")))
    paths.update(_lines(_git("diff", "--name-only")))
    paths.update(_lines(_git("diff", "--cached", "--name-only")))
    paths.update(_lines(_git("ls-files", "--others", "--exclude-standard")))
    return sorted(paths)


def _load_plan(paths: list[str]) -> dict[str, object]:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as changed_file:
        changed_file.write("".join(f"{path}\n" for path in paths))
        changed_file.flush()
        result = subprocess.run(
            [sys.executable, str(SELECTOR), "--format", "json", changed_file.name],
            capture_output=True,
            text=True,
            check=True,
        )
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict) or set(payload) != {"mode", "targets"}:
        raise ValueError("invalid affected-test plan keys")
    return payload


def _validated_targets(payload: dict[str, object]) -> list[str] | None:
    mode = payload["mode"]
    targets = payload["targets"]
    if mode == "all" and targets == []:
        return None
    if mode != "selected" or not isinstance(targets, list) or not targets:
        raise ValueError("invalid affected-test plan")
    validated: list[str] = []
    for target in targets:
        if not isinstance(target, str):
            raise ValueError("affected-test target must be a string")
        pure = PurePosixPath(target)
        if (
            pure.is_absolute()
            or ".." in pure.parts
            or not target.startswith("tests/")
            or pure.as_posix() != target
            or not Path(target).is_file()
        ):
            raise ValueError(f"unsafe affected-test target: {target}")
        validated.append(target)
    if validated != sorted(set(validated)):
        raise ValueError("affected-test targets must be sorted and unique")
    return validated


def _total_test_modules() -> int:
    return sum(
        1 for path in Path("tests").rglob("*.py") if path.name.startswith("test_") or path.name.endswith("_test.py")
    )


def main() -> int:
    try:
        targets = _validated_targets(_load_plan(changed_paths()))
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError) as error:
        print(f"affected-test selection failed: {error}", file=sys.stderr)
        return 2

    total = _total_test_modules()
    command = ["nix", "develop", "--command", "uv", "run", "pytest", "-n", "auto"]
    if targets is None:
        print(f"Full pytest suite: {total}/{total} targets")
    else:
        print(f"Selected pytest targets: {len(targets)}/{total}")
        command.extend(["--", *targets])
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
