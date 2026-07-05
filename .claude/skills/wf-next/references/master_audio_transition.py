#!/usr/bin/env python3
"""Resolve `/wf-next` prepared phase master-audio transition."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

AUDIO_EXTENSIONS = (".m4a", ".wav", ".flac", ".aac", ".mp3")
JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject = dict[str, JsonValue]


@dataclass(frozen=True)
class MasterCandidate:
    name: str
    path: Path
    source: str

    @property
    def identity(self) -> str:
        return f"{self.source}:{self.name}"


def _bool_arg(value: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise argparse.ArgumentTypeError("must be true or false")


def _approval_arg(value: str) -> bool:
    if value == "yes":
        return True
    if value == "no":
        return False
    raise argparse.ArgumentTypeError("must be yes or no")


def _load_state(path: Path) -> JsonObject:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid workflow-state.json: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"workflow-state.json could not be read: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("workflow-state.json root must be an object")
    assets = data.get("assets")
    if not isinstance(assets, dict):
        raise ValueError("workflow-state.json::assets must be an object")
    return cast(JsonObject, data)


def _write_state(path: Path, state: JsonObject) -> None:
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _validate_filename(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"workflow-state.json::{field} must be a non-empty filename string")
    if "/" in value or "\\" in value or ".." in value:
        raise ValueError(f"workflow-state.json::{field} must be a filename: {value}")
    return value


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _git_common_dir(repo_root: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    value = result.stdout.strip()
    return Path(value) if value else None


def _main_repo_master_dir(collection: Path, local_master_dir: Path, main_repo_root: Path | None = None) -> Path | None:
    if main_repo_root is None:
        repo_root = _repo_root()
        common_dir = _git_common_dir(repo_root)
        if common_dir is None or common_dir == repo_root / ".git":
            return None
        main_repo_root = common_dir.parent
    candidate = main_repo_root / "collections" / "planning" / collection.name / "01-master"
    if candidate == local_master_dir:
        return None
    return candidate


def _final_candidates(master_dirs: list[tuple[str, Path]], raw_master: str) -> list[MasterCandidate]:
    candidates: list[MasterCandidate] = []
    seen: set[tuple[str, Path]] = set()
    for source, master_dir in master_dirs:
        if not master_dir.is_dir():
            continue
        for path in sorted(master_dir.iterdir()):
            if path.name == raw_master or not path.is_file():
                continue
            if path.suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            key = (path.name, path.resolve())
            if key in seen:
                continue
            seen.add(key)
            candidates.append(MasterCandidate(name=path.name, path=path, source=source))
    return candidates


def _candidate_names(candidates: list[MasterCandidate]) -> list[str]:
    return [candidate.name for candidate in candidates]


def _find_selected_candidate(candidates: list[MasterCandidate], selection: str) -> MasterCandidate | None:
    for candidate in candidates:
        if candidate.identity == selection:
            return candidate
    filename_matches = [candidate for candidate in candidates if candidate.name == selection]
    if len(filename_matches) > 1:
        identities = ", ".join(candidate.identity for candidate in filename_matches)
        raise ValueError(f"selected-master-audio is ambiguous; use one of: {identities}")
    if len(filename_matches) == 1:
        return filename_matches[0]
    return None


def _copy_to_worktree(candidate: MasterCandidate, master_dir: Path) -> Path:
    target = master_dir / candidate.name
    if candidate.source == "worktree":
        return target
    master_dir.mkdir(parents=True, exist_ok=True)
    if not target.exists() or candidate.path.resolve() != target.resolve():
        shutil.copy2(candidate.path, target)
    return target


def _json_assets(state: JsonObject) -> JsonObject:
    assets = state["assets"]
    if not isinstance(assets, dict):
        raise ValueError("workflow-state.json::assets must be an object")
    return cast(JsonObject, assets)


def _json_string(value: JsonValue) -> str | None:
    return value if isinstance(value, str) else None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _emit(action: str, **payload: JsonValue) -> None:
    print(json.dumps({"action": action, **payload}, ensure_ascii=False, sort_keys=True))


def _ensure_approval_target(args: argparse.Namespace, selected: str, reason: str) -> bool:
    approved_master_audio = _validate_filename(args.approved_master_audio, "approved-master-audio")
    if args.approved is None:
        _emit("needs_approval", master_audio=selected, reason=reason)
        return False
    if approved_master_audio is None:
        raise ValueError("approved-master-audio is required when --approved is set")
    if approved_master_audio != selected:
        _emit(
            "needs_approval",
            approved_master_audio=approved_master_audio,
            master_audio=selected,
            reason="approval target changed",
        )
        return False
    if args.approved is False:
        _emit("approval_rejected", master_audio=selected, reason=reason)
        return False
    return True


def _candidate_sources(candidates: list[MasterCandidate]) -> list[JsonObject]:
    return [
        {
            "name": candidate.name,
            "source": candidate.source,
            "id": candidate.identity,
        }
        for candidate in candidates
    ]


def _emit_selection(candidates: list[MasterCandidate]) -> None:
    _emit(
        "needs_selection",
        candidates=_candidate_names(candidates),
        candidate_sources=_candidate_sources(candidates),
        reason="multiple final candidates",
    )


def _select_candidate_or_emit(
    candidates: list[MasterCandidate],
    selected_arg: str | None,
) -> MasterCandidate | None:
    if selected_arg is not None:
        selected_candidate = _find_selected_candidate(candidates, selected_arg)
        if selected_candidate is None:
            raise ValueError(f"selected-master-audio is not a final candidate: {selected_arg}")
        return selected_candidate
    if len(candidates) > 1:
        _emit_selection(candidates)
        return None
    return candidates[0] if candidates else None


def _local_master_path(master_dir: Path, selected: str) -> Path:
    return master_dir / selected


def _prepare_selected_file(candidate: MasterCandidate | None, master_dir: Path, selected: str) -> None:
    if candidate is not None:
        _copy_to_worktree(candidate, master_dir)
    if not _local_master_path(master_dir, selected).is_file():
        raise ValueError(f"master audio file does not exist: 01-master/{selected}")


def _master_dirs(collection: Path, master_dir: Path, main_repo_root: Path | None = None) -> list[tuple[str, Path]]:
    dirs = [("worktree", master_dir)]
    main_master_dir = _main_repo_master_dir(collection, master_dir, main_repo_root)
    if main_master_dir is not None:
        dirs.append(("main", main_master_dir))
    return dirs


def _adopt(state_path: Path, state: JsonObject, assets: JsonObject, selected: str, reason: str) -> None:
    assets["master_audio"] = selected
    state["phase"] = "mastered"
    state["updated_at"] = _utc_now()
    _write_state(state_path, state)
    _emit(
        "adopted", master_audio=selected, phase="mastered", reason=reason, updated_at=_json_string(state["updated_at"])
    )


def _validate_phase_and_pending(state: JsonObject, assets: JsonObject) -> bool:
    raw_master = _validate_filename(assets.get("raw_master"), "assets.raw_master")
    current_master = _validate_filename(assets.get("master_audio"), "assets.master_audio")
    if state.get("phase") != "prepared":
        _emit("noop", reason="phase is not prepared")
        return False
    if raw_master is None or current_master is not None:
        _emit("noop", reason="master-audio step is not pending")
        return False
    return True


def _raw_master(assets: JsonObject) -> str:
    raw_master = _validate_filename(assets.get("raw_master"), "assets.raw_master")
    if raw_master is None:
        raise ValueError("workflow-state.json::assets.raw_master must be set")
    return raw_master


def _selected_arg(args: argparse.Namespace) -> str | None:
    return _validate_filename(args.selected_master_audio, "selected-master-audio")


def _resolve_transition(
    args: argparse.Namespace,
    collection: Path,
    state_path: Path,
    state: JsonObject,
    assets: JsonObject,
    master_dir: Path,
) -> int:
    if not _validate_phase_and_pending(state, assets):
        return 0

    raw_master = _raw_master(assets)
    selected_arg = _selected_arg(args)
    candidates = _final_candidates(_master_dirs(collection, master_dir, args.main_repo_root), raw_master)
    selected_candidate = _select_candidate_or_emit(candidates, selected_arg)
    if len(candidates) > 1 and selected_candidate is None:
        return 0

    selected = selected_candidate.name if selected_candidate else None
    reason = "final candidate" if selected else "raw master as final"

    if selected is None:
        if not args.skip_manual_mastering:
            _emit("wait_for_master", reason="manual mastering is required")
            return 0
        selected = raw_master

    if args.approval_gate_audio and not _ensure_approval_target(args, selected, reason):
        return 0

    _prepare_selected_file(selected_candidate, master_dir, selected)
    _adopt(state_path, state, assets, selected, reason)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection", type=Path)
    parser.add_argument("--skip-manual-mastering", required=True, type=_bool_arg)
    parser.add_argument("--approval-gate-audio", required=True, type=_bool_arg)
    parser.add_argument("--approved", type=_approval_arg)
    parser.add_argument("--approved-master-audio")
    parser.add_argument("--selected-master-audio")
    parser.add_argument("--main-repo-root", type=Path)
    args = parser.parse_args(argv)

    collection = args.collection
    state_path = collection / "workflow-state.json"
    state = _load_state(state_path)
    assets = _json_assets(state)
    master_dir = collection / "01-master"
    return _resolve_transition(args, collection, state_path, state, assets, master_dir)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
