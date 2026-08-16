#!/usr/bin/env python3
"""Validate a `/wf-new` batch plan manifest without mutating it."""

from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from pathlib import Path

_ID = re.compile(r"[a-z0-9][a-z0-9-]*\Z")
_PLAN_FIELDS = (
    "plan_id",
    "collection_name",
    "theme_slug",
    "final_title",
    "target_persona",
    "viewing_scene",
    "proposal_markdown",
)


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _unique_strings(value: object, *, field: str) -> list[str]:
    if not isinstance(value, list) or not all(_nonempty(item) for item in value):
        raise ValueError(f"{field} は空でない string の array でなければなりません")
    if len(set(value)) != len(value):
        raise ValueError(f"{field} に重複があります")
    return value


def validate_manifest(manifest: object) -> dict:
    if not isinstance(manifest, dict):
        raise ValueError("manifest root は object でなければなりません")
    if manifest.get("schema_version") != 1:
        raise ValueError("schema_version は 1 でなければなりません")
    batch_id = manifest.get("batch_id")
    if not isinstance(batch_id, str) or not _ID.fullmatch(batch_id):
        raise ValueError("batch_id は lowercase kebab-case でなければなりません")
    requested_count = manifest.get("requested_count")
    if isinstance(requested_count, bool) or not isinstance(requested_count, int) or requested_count < 2:
        raise ValueError("requested_count は 2 以上の整数でなければなりません")
    if not _nonempty(manifest.get("approved_at")):
        raise ValueError("approved_at がない manifest は未承認です")

    provenance = manifest.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("provenance は object でなければなりません")
    if provenance.get("producer") != "wf-new" or provenance.get("mode") != "batch-plan":
        raise ValueError("provenance producer/mode が batch plan 契約と一致しません")
    if not _nonempty(provenance.get("input_mode")) or not isinstance(provenance.get("ttp_mode"), bool):
        raise ValueError("provenance input_mode/ttp_mode が不正です")

    existing_slugs = _unique_strings(manifest.get("existing_collection_slugs"), field="existing_collection_slugs")
    plans = manifest.get("plans")
    if not isinstance(plans, list) or len(plans) != requested_count:
        raise ValueError("plans は requested_count と同じ件数でなければなりません")
    plan_ids = []
    theme_slugs = []
    for index, plan in enumerate(plans):
        if not isinstance(plan, dict):
            raise ValueError(f"plans[{index}] は object でなければなりません")
        for field in _PLAN_FIELDS:
            if not _nonempty(plan.get(field)):
                raise ValueError(f"plans[{index}].{field} は空でない string でなければなりません")
        if not _ID.fullmatch(plan["plan_id"]) or not _ID.fullmatch(plan["theme_slug"]):
            raise ValueError(f"plans[{index}] の plan_id/theme_slug は lowercase kebab-case が必要です")
        track_count = plan.get("track_count")
        if isinstance(track_count, bool) or not isinstance(track_count, int) or track_count < 1:
            raise ValueError(f"plans[{index}].track_count は 1 以上の整数でなければなりません")
        if plan.get("music_engine") not in {"suno", "lyria", "minimax"}:
            raise ValueError(f"plans[{index}].music_engine は suno / lyria / minimax のいずれかが必要です")
        plan_ids.append(plan["plan_id"])
        theme_slugs.append(plan["theme_slug"])
    if len(set(plan_ids)) != len(plan_ids):
        raise ValueError("plan_id に重複があります")
    if len(set(theme_slugs)) != len(theme_slugs):
        raise ValueError("theme_slug に重複があります")
    collisions = sorted(set(theme_slugs) & set(existing_slugs))
    if collisions:
        raise ValueError(f"theme_slug が既存 collection と衝突します: {', '.join(collisions)}")

    matrix = manifest.get("differentiation_matrix")
    if not isinstance(matrix, list):
        raise ValueError("differentiation_matrix は array でなければなりません")
    observed_pairs = []
    observed_existing = []
    for index, row in enumerate(matrix):
        if not isinstance(row, dict) or not _nonempty(row.get("differences")):
            raise ValueError(f"differentiation_matrix[{index}] は非空 differences を持つ object が必要です")
        if row.get("kind") == "batch_pair":
            observed_pairs.append((row.get("left_plan_id"), row.get("right_plan_id")))
        elif row.get("kind") == "existing_collection":
            observed_existing.append((row.get("plan_id"), row.get("existing_collection_slug")))
        else:
            raise ValueError(f"differentiation_matrix[{index}].kind が不正です")

    expected_pairs = list(itertools.combinations(plan_ids, 2))
    expected_existing = list(itertools.product(plan_ids, existing_slugs))
    if len(set(observed_pairs)) != len(observed_pairs) or observed_pairs != expected_pairs:
        raise ValueError("batch_pair は plan 順の全 unordered pair を重複・欠落なく含める必要があります")
    if len(set(observed_existing)) != len(observed_existing) or observed_existing != expected_existing:
        raise ValueError("existing_collection row は plan と既存 slug の直積を重複・欠落なく含める必要があります")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        validated = validate_manifest(manifest)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"invalid batch manifest: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": "valid", "batch_id": validated["batch_id"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
