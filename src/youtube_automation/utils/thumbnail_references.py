"""Thumbnail TTP reference-image contract helpers."""

from __future__ import annotations

import re
from pathlib import Path

from youtube_automation.utils.exceptions import ConfigError


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
