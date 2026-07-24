"""Thumbnail TTP reference-image contract helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from youtube_automation.infrastructure.errors import ConfigError
from youtube_automation.utils.image_provider.composition import normalize_reference_default
from youtube_automation.utils.placeholders import is_placeholder_value

DEFAULT_DEDUP_RECENT_COLLECTIONS = 5


@dataclass(frozen=True)
class BenchmarkReferenceResolution:
    references: list[Path]
    placeholders: list[str]
    invalid_reasons: list[str]


def resolve_configured_benchmark_references(channel_dir: Path, default_value: object) -> BenchmarkReferenceResolution:
    """Resolve ``reference_images.default`` with the strict TTP benchmark contract."""
    refs: list[Path] = []
    placeholders: list[str] = []
    invalid_reasons: list[str] = []
    benchmark_root = (channel_dir / "data" / "thumbnail_compare" / "benchmark").resolve(strict=False)
    channel_root = channel_dir.resolve(strict=False)

    for value in normalize_reference_default(default_value):  # type: ignore[arg-type]
        stripped = value.strip()
        if is_placeholder_value(stripped):
            placeholders.append(stripped)
            continue
        ref_path = Path(stripped)
        if ref_path.is_absolute():
            invalid_reasons.append(f"絶対パスは指定できない: {stripped}")
            continue
        resolved = (channel_dir / ref_path).resolve(strict=False)
        try:
            resolved.relative_to(channel_root)
        except ValueError:
            invalid_reasons.append(f"channel_dir 外は指定できない: {stripped}")
            continue
        try:
            resolved.relative_to(benchmark_root)
        except ValueError:
            invalid_reasons.append(f"data/thumbnail_compare/benchmark/ 配下ではない: {stripped}")
            continue
        refs.append(resolved)
    return BenchmarkReferenceResolution(references=refs, placeholders=placeholders, invalid_reasons=invalid_reasons)


def canonicalize_benchmark_reference(reference_path: Path, benchmark_root: Path) -> Path:
    """Resolve a benchmark reference and reject paths outside ``benchmark_root``."""
    try:
        canonical_ref = reference_path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ConfigError(f"参照画像が見つかりません: {reference_path}") from exc

    canonical_root = benchmark_root.resolve(strict=False)
    try:
        canonical_ref.relative_to(canonical_root)
    except ValueError as exc:
        raise ConfigError(
            "single_step TTP 生成の参照画像は "
            f"{canonical_root} 配下の benchmark サムネイルに限定してください: {reference_path}"
        ) from exc
    return canonical_ref


def infer_benchmark_channel(reference_path: Path, benchmark_root: Path | None = None) -> str:
    """Infer the benchmark channel from a thumbnail reference path."""
    if benchmark_root is not None:
        try:
            relative = reference_path.resolve(strict=False).relative_to(benchmark_root.resolve(strict=False))
        except ValueError:
            return "unknown"
        if len(relative.parts) > 1:
            return relative.parts[0]
        stem = relative.stem
    else:
        parts = reference_path.parts
        if "benchmark" in parts:
            index = parts.index("benchmark")
            if index + 1 < len(parts) - 1:
                return parts[index + 1]
        stem = reference_path.stem

    underscore_match = re.fullmatch(
        r"(?P<channel>[A-Za-z0-9][A-Za-z0-9_-]*?)_(?:(?:\d+(?:\.\d+)?[kKmM])_)?(?P<video>[A-Za-z0-9_-]{6,})",
        stem,
    )
    if underscore_match:
        return underscore_match.group("channel")

    hyphen_match = re.fullmatch(
        r"(?P<channel>[A-Za-z0-9][A-Za-z0-9_-]*?)-(?P<video>[A-Za-z0-9_]{6,})",
        stem,
    )
    if hyphen_match:
        return hyphen_match.group("channel")
    return "unknown"


def format_reference_assignment(reference_path: Path, benchmark_root: Path | None = None) -> str:
    """Format reference assignment logs with benchmark-channel traceability."""
    return f"{reference_path} (benchmark_channel={infer_benchmark_channel(reference_path, benchmark_root)})"


def record_ttp_reference_assignments(
    prompt_log: Path,
    reference_images: list[Path],
    channel_dir: Path,
) -> None:
    """Append collection-level TTP reference assignments to a thumbnail prompt log."""
    channel_root = channel_dir.resolve(strict=False)
    benchmark_root = channel_dir / "data" / "thumbnail_compare" / "benchmark"
    rows: list[str] = []
    for index, reference in enumerate(reference_images, 1):
        resolved_reference = reference.resolve(strict=False)
        try:
            documented_reference = resolved_reference.relative_to(channel_root)
        except ValueError:
            documented_reference = resolved_reference
        rows.append(
            f"| {index} | collection-ideate preview | `{documented_reference}` | "
            f"{infer_benchmark_channel(resolved_reference, benchmark_root)} |"
        )

    rows_text = "\n".join(rows)
    section = (
        "## Reference Assignments\n"
        "| attempt | output | reference_image | benchmark_channel |\n"
        "|---:|---|---|---|\n"
        f"{rows_text}\n"
    )
    try:
        prompt_log.parent.mkdir(parents=True, exist_ok=True)
        existing = prompt_log.read_text(encoding="utf-8") if prompt_log.exists() else ""
        separator = "\n" if existing and not existing.endswith("\n\n") else ""
        prompt_log.write_text(f"{existing}{separator}{section}", encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"参照画像履歴を保存できません: {prompt_log}: {exc}") from exc


def resolve_dedup_recent_collections(value: object) -> int:
    """Validate the configured number of recent collections used for deduplication."""
    if value is None:
        return DEFAULT_DEDUP_RECENT_COLLECTIONS
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ConfigError("reference_images.dedup_recent_collections は 0 以上の整数で指定してください")
    return value


def _reference_images_from_prompt_log(prompt_log: Path, channel_dir: Path) -> set[Path]:
    """Read documented assignments, rejecting inaccessible history files."""
    try:
        lines = prompt_log.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ConfigError(f"参照画像履歴を読み取れません: {prompt_log}: {exc}") from exc

    in_assignments = False
    references: set[Path] = set()
    for line in lines:
        if line.strip() == "## Reference Assignments":
            in_assignments = True
            continue
        if in_assignments and line.startswith("## "):
            in_assignments = False
            continue
        if not in_assignments or not line.lstrip().startswith("|"):
            continue
        columns = [column.strip() for column in line.strip().split("|")]
        if len(columns) < 5 or columns[1] in {"attempt", "---:"}:
            continue
        reference = columns[3].strip("` ")
        if not reference or reference.startswith("<"):
            continue
        path = Path(reference)
        references.add((path if path.is_absolute() else channel_dir / path).resolve(strict=False))
    return references


def _reference_image_history(channel_dir: Path, recent_limit: int) -> tuple[set[Path], set[Path]]:
    """Return references from the recent window and from all collection prompt logs."""
    collections_root = channel_dir / "collections"
    if not collections_root.is_dir():
        return set(), set()
    collection_dirs = sorted(
        (path for path in collections_root.glob("*/*") if path.is_dir() and not path.name.startswith("_")),
        key=lambda path: path.name,
        reverse=True,
    )
    recent_references: set[Path] = set()
    all_references: set[Path] = set()
    for index, collection in enumerate(collection_dirs):
        prompt_log = collection / "20-documentation" / "thumbnail-prompts.md"
        if prompt_log.is_file():
            references = _reference_images_from_prompt_log(prompt_log, channel_dir)
            all_references.update(references)
            if index < recent_limit:
                recent_references.update(references)
    return recent_references, all_references


def plan_ttp_reference_assignments(
    reference_images: list[Path],
    count: int,
    rotate: bool,
    *,
    benchmark_root: Path | None = None,
    channel_dir: Path | None = None,
    dedup_recent_collections: int = 0,
) -> list[Path | None]:
    """Plan strict TTP assignments, excluding references used by recent collections."""
    if not reference_images:
        raise ConfigError(
            "single_step TTP 生成には参照画像が必須です。"
            "config/skills/thumbnail.yaml の image_generation.gemini.reference_images.default を設定し、"
            "--reference で CLI へ展開してください。"
        )
    if count > 1 and not rotate:
        raise ConfigError(
            "single_step TTP 生成で複数候補を出す場合、--no-rotate は使えません。"
            "候補ごとに別参照画像を割り当てるため、参照画像を候補数分指定してください。"
        )

    if len(reference_images) < count:
        raise ConfigError(
            f"single_step TTP 生成には候補数分のユニークな参照画像が必要です "
            f"(max_attempts={count}, references={len(reference_images)})。"
            "同じベンチマークチャンネル内の別サムネイル画像を追加してください。"
        )
    selected_references = reference_images
    if rotate and channel_dir is not None and dedup_recent_collections:
        recent_references, all_references = _reference_image_history(channel_dir, dedup_recent_collections)
        unused_references = [ref for ref in reference_images if ref.resolve(strict=False) not in all_references]
        references_outside_recent_window = [
            ref for ref in reference_images if ref.resolve(strict=False) not in recent_references
        ]
        if unused_references:
            selected_references = unused_references + [
                ref for ref in references_outside_recent_window if ref not in unused_references
            ]
        elif references_outside_recent_window:
            selected_references = references_outside_recent_window
        selected_references += [ref for ref in reference_images if ref not in selected_references]

    selected_references = selected_references[:count]
    if benchmark_root is not None:
        selected_references = [canonicalize_benchmark_reference(ref, benchmark_root) for ref in selected_references]

    seen: set[Path] = set()
    duplicates: list[Path] = []
    for ref in selected_references:
        if ref in seen:
            duplicates.append(ref)
        seen.add(ref)
    if duplicates:
        duplicate_list = ", ".join(str(path) for path in duplicates)
        raise ConfigError(f"single_step TTP 生成では同一参照画像を再利用できません: {duplicate_list}")

    channels = [infer_benchmark_channel(ref, benchmark_root) for ref in selected_references]
    if any(channel == "unknown" for channel in channels):
        unknown_refs = [
            str(ref) for ref, channel in zip(selected_references, channels, strict=True) if channel == "unknown"
        ]
        raise ConfigError(
            "single_step TTP 生成では全参照画像を同じベンチマークチャンネルとして追跡できる必要があります "
            f"(benchmark_channel=unknown: {', '.join(unknown_refs)})。"
            "data/thumbnail_compare/benchmark/<channel>/ 配下、または既存の benchmark 保存形式の画像を"
            "指定してください。"
        )

    detected_channels = set(channels)
    if len(detected_channels) > 1:
        raise ConfigError(
            "single_step TTP 生成の複数候補では同じベンチマークチャンネル内の参照画像だけを使ってください "
            f"(detected={', '.join(sorted(detected_channels))})。"
            "別チャンネル由来の参照画像は別スコープとして明示してください。"
        )
    return list(selected_references)
