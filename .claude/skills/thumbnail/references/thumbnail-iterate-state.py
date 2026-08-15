#!/usr/bin/env python3
"""Validate thumbnail iteration plans and promote Studio-proven champions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ALLOWED_ELEMENTS = {"composition", "text", "color", "subject", "expression"}


class ContractError(ValueError):
    """Raised when operator input violates the iteration contract."""


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"JSON root must be an object: {path}")
    return value


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    os.close(fd)
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{field} must be a number")
    return float(value)


def _safe_file(repo: Path, relative: object, collection: str) -> tuple[str, str]:
    if not isinstance(relative, str) or not relative:
        raise ContractError("candidate file must be a non-empty relative path")
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ContractError(f"candidate escapes repository: {relative}")
    if not relative.startswith(f"{collection}/10-assets/"):
        raise ContractError(f"candidate must be inside {collection}/10-assets/: {relative}")
    absolute = repo / path
    current = repo
    for part in path.parts:
        current /= part
        if current.is_symlink():
            raise ContractError(f"candidate path contains symlink: {relative}")
    try:
        absolute.resolve(strict=True).relative_to(repo.resolve(strict=True))
    except (FileNotFoundError, ValueError) as exc:
        raise ContractError(f"candidate is missing or outside repository: {relative}") from exc
    if not absolute.is_file():
        raise ContractError(f"candidate is not a file: {relative}")
    digest = hashlib.sha256(absolute.read_bytes()).hexdigest()
    return relative, digest


def _plan(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve(strict=True)
    payload = _read_json(Path(args.input))
    video_id = payload.get("video_id")
    collection = payload.get("collection")
    if not isinstance(video_id, str) or not video_id or "/" in video_id or video_id in {".", ".."}:
        raise ContractError("video_id must be a non-empty filename-safe string")
    if (
        not isinstance(collection, str)
        or not collection
        or Path(collection).is_absolute()
        or ".." in Path(collection).parts
    ):
        raise ContractError("collection must be a repository-relative path")

    target_ctr = _number(payload.get("target_ctr"), "target_ctr")
    average_ctr = _number(payload.get("channel_average_ctr"), "channel_average_ctr")
    browse_share = _number(payload.get("browse_share"), "browse_share")
    suggested_share = _number(payload.get("suggested_share"), "suggested_share")
    if average_ctr <= 0 or min(target_ctr, browse_share, suggested_share) < 0:
        raise ContractError("CTR and traffic shares must be non-negative; channel average must be positive")
    ctr_ratio = round(target_ctr / average_ctr, 4)
    source_share = round(browse_share + suggested_share, 4)
    supported = ctr_ratio >= 1.20 and source_share >= 50.0
    attribution = {
        "target_ctr": target_ctr,
        "channel_average_ctr": average_ctr,
        "ctr_ratio": ctr_ratio,
        "browse_suggested_share": source_share,
        "verdict": "thumbnail_supported" if supported else "thumbnail_not_supported",
    }
    run_path = repo / "data/thumbnail-iterate/runs" / f"{video_id}.json"
    if not supported:
        _write_json(
            run_path,
            {
                "schema_version": 1,
                "video_id": video_id,
                "collection": collection,
                "status": "stopped",
                "stop_reason": "thumbnail causality threshold not met",
                "attribution": attribution,
            },
        )
        print("thumbnail causality is not supported; route to /flop-analysis", file=sys.stderr)
        return 2

    hypotheses = payload.get("hypotheses")
    if (
        not isinstance(hypotheses, list)
        or not 1 <= len(hypotheses) <= 2
        or len(set(hypotheses)) != len(hypotheses)
        or not set(hypotheses) <= ALLOWED_ELEMENTS
    ):
        raise ContractError("hypotheses must contain 1-2 unique allowed elements")
    round_type = payload.get("round_type", "controlled")
    if round_type not in {"controlled", "coherent_synthesis"}:
        raise ContractError("round_type must be controlled or coherent_synthesis")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not 2 <= len(candidates) <= 3:
        raise ContractError("candidates must contain 2-3 items")
    if [candidate.get("id") for candidate in candidates if isinstance(candidate, dict)] != ["A", "B", "C"][
        : len(candidates)
    ]:
        raise ContractError("candidate IDs must be A, B, then optional C")

    normalized: list[dict[str, object]] = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            raise ContractError("each candidate must be an object")
        changes = candidate.get("changed_elements")
        if not isinstance(changes, list) or len(set(changes)) != len(changes) or not set(changes) <= ALLOWED_ELEMENTS:
            raise ContractError("changed_elements must contain unique allowed elements")
        if index == 0 and changes:
            raise ContractError("control A must change zero elements")
        if index > 0 and round_type == "controlled" and len(changes) != 1:
            raise ContractError("each controlled variant must change exactly one element")
        if index > 0 and round_type == "coherent_synthesis" and len(changes) < 2:
            raise ContractError("a coherent synthesis variant must change at least two elements")
        if not set(changes) <= set(hypotheses):
            raise ContractError("candidate changes must be selected from ranked hypotheses")
        relative, digest = _safe_file(repo, candidate.get("file"), collection)
        normalized.append({"id": candidate["id"], "file": relative, "changed_elements": changes, "sha256": digest})
    if len({item["file"] for item in normalized}) != len(normalized) or len(
        {item["sha256"] for item in normalized}
    ) != len(normalized):
        raise ContractError("candidate files and contents must be unique")

    pending_path = repo / "data/thumbnail-iterate/synthesis-required.json"
    if round_type == "coherent_synthesis":
        if not pending_path.exists():
            raise ContractError("coherent synthesis requires synthesis-required.json")
        pending = _read_json(pending_path)
        if pending.get("status") != "coherent_synthesis_required" or hypotheses != pending.get("elements"):
            raise ContractError("coherent synthesis hypotheses must match pending elements in order")
        control = pending.get("control")
        if not isinstance(control, dict) or normalized[0]["sha256"] != control.get("sha256"):
            raise ContractError("coherent synthesis control A must match the current champion content hash")
        if any(set(candidate["changed_elements"]) != set(hypotheses) for candidate in normalized[1:]):
            raise ContractError("each coherent synthesis variant must implement all pending elements")
    elif pending_path.exists():
        raise ContractError("coherent synthesis is pending; another controlled round cannot start")

    run = {
        "schema_version": 1,
        "video_id": video_id,
        "collection": collection,
        "status": "planned",
        "attribution": attribution,
        "hypotheses": hypotheses,
        "round_type": round_type,
        "candidates": normalized,
    }
    _write_json(run_path, run)
    print(run_path)
    return 0


def _promote(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve(strict=True)
    video_id = args.video_id
    run_path = repo / "data/thumbnail-iterate/runs" / f"{video_id}.json"
    run = _read_json(run_path)
    if run.get("status") != "planned" or run.get("video_id") != video_id:
        raise ContractError("matching planned run is required")
    history_path = Path(args.history).resolve(strict=True)
    expected_history = (repo / run["collection"] / "20-documentation/thumbnail-test-history.json").resolve()
    if history_path != expected_history:
        raise ContractError(f"history must be the collection history: {expected_history}")
    history = _read_json(history_path)
    entries = [
        entry for entry in history.get("entries", []) if isinstance(entry, dict) and entry.get("video_id") == video_id
    ]
    if not entries:
        raise ContractError("history has no matching video_id")
    entry = entries[-1]
    result = entry.get("result")
    if not isinstance(result, dict) or result.get("status") not in {"winner", "performed_same", "inconclusive"}:
        raise ContractError("history result status is invalid")
    recorded = entry.get("candidates")
    if not isinstance(recorded, list) or len(recorded) != len(run["candidates"]):
        raise ContractError("history candidates do not match planned candidates")
    for expected, actual in zip(run["candidates"], recorded, strict=True):
        if not isinstance(actual, dict) or any(actual.get(key) != expected[key] for key in ("id", "file", "sha256")):
            raise ContractError("history candidate mapping or hash differs from plan")
        _, current_hash = _safe_file(repo, expected["file"], run["collection"])
        if current_hash != expected["sha256"]:
            raise ContractError(f"candidate current content hash differs from plan: {expected['file']}")

    if result["status"] != "winner":
        run["status"] = "completed_without_winner"
        run["completed_at"] = entry.get("completed_at")
        _write_json(run_path, run)
        print("no champion update")
        return 0
    winner_id = result.get("result_candidate_id")
    winner = next((candidate for candidate in run["candidates"] if candidate["id"] == winner_id), None)
    if winner is None:
        raise ContractError("winner candidate ID does not exist")

    champion_path = repo / "data/thumbnail-iterate/champion.json"
    existing = _read_json(champion_path) if champion_path.exists() else None
    if existing:
        existing_file = existing.get("file")
        if not isinstance(existing_file, str) or Path(existing_file).is_absolute() or ".." in Path(existing_file).parts:
            raise ContractError("existing champion file path is invalid")
        existing_path = repo / existing_file
        if existing_path.is_symlink() or not existing_path.is_file():
            raise ContractError("existing champion file is missing or a symlink")
        if hashlib.sha256(existing_path.read_bytes()).hexdigest() != existing.get("sha256"):
            raise ContractError("existing champion current content hash differs")
    new_elements = winner["changed_elements"]
    existing_elements = existing.get("validated_elements", []) if existing else []
    combined = list(dict.fromkeys([*existing_elements, *new_elements]))
    if existing and run["round_type"] == "controlled" and set(new_elements) - set(existing_elements):
        pending = {
            "schema_version": 1,
            "status": "coherent_synthesis_required",
            "elements": combined,
            "control": {"file": existing["file"], "sha256": existing["sha256"]},
            "evidence_video_ids": [existing["video_id"], video_id],
        }
        _write_json(repo / "data/thumbnail-iterate/synthesis-required.json", pending)
        run["status"] = "winner_requires_synthesis"
        _write_json(run_path, run)
        print("independent winners require coherent regeneration and a final comparison", file=sys.stderr)
        return 3

    winner_source = repo / winner["file"]
    suffix = winner_source.suffix.lower()
    snapshot_relative = f"data/thumbnail-iterate/champions/{winner['sha256']}{suffix}"
    _copy_file(winner_source, repo / snapshot_relative)
    champion = {
        "schema_version": 1,
        "video_id": video_id,
        "collection": run["collection"],
        "file": snapshot_relative,
        "sha256": winner["sha256"],
        "validated_elements": combined,
        "promoted_at": entry.get("completed_at"),
        "history": str(history_path.relative_to(repo)),
    }
    _write_json(champion_path, champion)
    if run["round_type"] == "coherent_synthesis":
        (repo / "data/thumbnail-iterate/synthesis-required.json").unlink(missing_ok=True)
    run["status"] = "champion_promoted"
    _write_json(run_path, run)
    print(champion_path)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan")
    plan.add_argument("--repo", required=True)
    plan.add_argument("--input", required=True)
    plan.set_defaults(handler=_plan)
    promote = subparsers.add_parser("promote")
    promote.add_argument("--repo", required=True)
    promote.add_argument("--video-id", required=True)
    promote.add_argument("--history", required=True)
    promote.set_defaults(handler=_promote)
    args = parser.parse_args()
    try:
        return args.handler(args)
    except (ContractError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
