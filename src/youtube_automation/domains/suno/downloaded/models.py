"""Suno collection artifact path and route contracts shared by scripts and utils."""

from __future__ import annotations

import urllib.parse
from abc import abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

DOCUMENTATION_DIRNAME = "20-documentation"
SUNO_PATTERNS_FILENAME = "suno-patterns.yaml"
SUNO_LYRICS_JSON_FILENAME = "suno-lyrics.json"
SUNO_PROMPTS_MD_FILENAME = "suno-prompts.md"
SUNO_PROMPTS_JSON_FILENAME = "suno-prompts.json"

SUNO_PROMPTS_ROUTE = "/suno/prompts.json"
COLLECTIONS_ROUTE = "/collections"
DOWNLOADED_ROUTE_SUFFIX = "/downloaded"


class PromptEntriesReader(Protocol):
    @abstractmethod
    def __call__(self, collection_dir: Path) -> Sequence[object]: ...


class SunoConfig(Protocol):
    genre_line: str
    exclude_styles: str
    raw: Mapping[str, object]


class SunoModeInferer(Protocol):
    @abstractmethod
    def __call__(self, genre_line: str) -> str: ...


def collection_downloaded_route(collection_id: str) -> str:
    """個別 collection の download 完了通知 POST ルートを組み立てる。"""
    encoded_id = urllib.parse.quote(collection_id, safe="")
    return f"{COLLECTIONS_ROUTE}/{encoded_id}{DOWNLOADED_ROUTE_SUFFIX}"


_VALID_DOWNLOAD_FORMATS = frozenset({"mp3", "m4a", "wav"})


class DownloadedPayloadError(ValueError):
    """POST /downloaded の入力 payload が不正。HTTP 400 に変換する。"""


class DownloadedArtifactError(RuntimeError):
    """POST /downloaded の artifact 適用に失敗。HTTP 500 に変換する。"""


@dataclass(frozen=True)
class DownloadedPayload:
    file_count: int
    format: str
    suno_playlist_url: str | None = None
    expected_file_count: int | None = None
    download_path: str | None = None
    clip_ids: tuple[str, ...] = ()
    generated_at: str | None = None


def _nonnegative_file_count(value: object, field: str) -> int:
    """Validate the integer counts accepted by a completed download notification."""
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise DownloadedPayloadError(f"{field} must be a non-negative integer")
    return value


def parse_downloaded_payload(payload: object) -> DownloadedPayload:
    if not isinstance(payload, dict):
        raise DownloadedPayloadError("payload must be an object")

    file_count = payload.get("file_count")
    fmt = payload.get("format")
    suno_playlist_url = payload.get("suno_playlist_url")
    expected_file_count = payload.get("expected_file_count")
    download_path = payload.get("download_path")
    clip_ids = payload.get("clip_ids", [])
    generated_at = payload.get("generated_at")

    if file_count is None or not fmt:
        raise DownloadedPayloadError("file_count and format are required")
    file_count = _nonnegative_file_count(file_count, "file_count")
    if not isinstance(fmt, str) or fmt not in _VALID_DOWNLOAD_FORMATS:
        raise DownloadedPayloadError("format is invalid")
    if file_count > 0 and download_path is None:
        raise DownloadedPayloadError("download_path is required when file_count is positive")
    if expected_file_count is not None:
        expected_file_count = _nonnegative_file_count(expected_file_count, "expected_file_count")
    if download_path is not None:
        if not isinstance(download_path, str):
            raise DownloadedPayloadError("download_path must be a string")
        if not Path(download_path).is_absolute():
            raise DownloadedPayloadError("download_path must be absolute")
    if suno_playlist_url is not None and not isinstance(suno_playlist_url, str):
        raise DownloadedPayloadError("suno_playlist_url must be a string")
    if not isinstance(clip_ids, list) or not all(isinstance(value, str) and value for value in clip_ids):
        raise DownloadedPayloadError("clip_ids must be an array of non-empty strings")
    if clip_ids and not isinstance(generated_at, str):
        raise DownloadedPayloadError("generated_at is required with clip_ids")

    return DownloadedPayload(
        file_count=file_count,
        format=fmt,
        suno_playlist_url=suno_playlist_url,
        expected_file_count=expected_file_count,
        download_path=download_path,
        clip_ids=tuple(clip_ids),
        generated_at=generated_at if isinstance(generated_at, str) else None,
    )
