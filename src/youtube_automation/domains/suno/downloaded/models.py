"""Suno collection artifact path and route contracts shared by scripts and utils."""

from __future__ import annotations

import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

DOCUMENTATION_DIRNAME = "20-documentation"
SUNO_PATTERNS_FILENAME = "suno-patterns.yaml"
SUNO_LYRICS_JSON_FILENAME = "suno-lyrics.json"
SUNO_PROMPTS_MD_FILENAME = "suno-prompts.md"
SUNO_PROMPTS_JSON_FILENAME = "suno-prompts.json"

SUNO_PROMPTS_ROUTE = "/suno/prompts.json"
COLLECTIONS_ROUTE = "/collections"
DOWNLOADED_ROUTE_SUFFIX = "/downloaded"


class PromptEntriesReader(Protocol):
    def __call__(self, collection_dir: Path) -> list[Any]: ...


class SunoConfig(Protocol):
    genre_line: str
    exclude_styles: str
    raw: Mapping[str, object]


class SunoModeInferer(Protocol):
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


def parse_downloaded_payload(payload: object) -> DownloadedPayload:
    if not isinstance(payload, dict):
        raise DownloadedPayloadError("payload must be an object")

    file_count = payload.get("file_count")
    fmt = payload.get("format")
    suno_playlist_url = payload.get("suno_playlist_url")
    expected_file_count = payload.get("expected_file_count")
    download_path = payload.get("download_path")

    if file_count is None or not fmt:
        raise DownloadedPayloadError("file_count and format are required")
    if not isinstance(file_count, int) or isinstance(file_count, bool) or file_count < 0:
        raise DownloadedPayloadError("file_count must be a non-negative integer")
    if not isinstance(fmt, str) or fmt not in _VALID_DOWNLOAD_FORMATS:
        raise DownloadedPayloadError("format is invalid")
    if file_count > 0 and download_path is None:
        raise DownloadedPayloadError("download_path is required when file_count is positive")
    if expected_file_count is not None and (
        not isinstance(expected_file_count, int) or isinstance(expected_file_count, bool) or expected_file_count < 0
    ):
        raise DownloadedPayloadError("expected_file_count must be a non-negative integer")
    if download_path is not None:
        if not isinstance(download_path, str):
            raise DownloadedPayloadError("download_path must be a string")
        if not Path(download_path).is_absolute():
            raise DownloadedPayloadError("download_path must be absolute")
    if suno_playlist_url is not None and not isinstance(suno_playlist_url, str):
        raise DownloadedPayloadError("suno_playlist_url must be a string")

    return DownloadedPayload(
        file_count=file_count,
        format=fmt,
        suno_playlist_url=suno_playlist_url,
        expected_file_count=expected_file_count,
        download_path=download_path,
    )
