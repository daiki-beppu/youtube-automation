"""Thumbnail TTP reference-image contract helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.image_provider.composition import normalize_reference_default
from youtube_automation.utils.placeholders import is_placeholder_value


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


def plan_ttp_reference_assignments(
    reference_images: list[Path],
    count: int,
    rotate: bool,
    *,
    benchmark_root: Path | None = None,
) -> list[Path | None]:
    """Plan strict thumbnail TTP reference assignment before generation."""
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
    selected_references = reference_images[:count]
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
        unknown_refs = [str(ref) for ref, channel in zip(selected_references, channels) if channel == "unknown"]
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
