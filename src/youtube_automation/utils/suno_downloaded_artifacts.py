"""Suno helper の downloaded artifact 適用ロジック。

HTTP handler から切り離し、payload validation、ZIP 展開、music dir commit、
workflow-state 更新をこのモジュールに閉じる。
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from youtube_automation.scripts.suno_artifacts import DOCUMENTATION_DIRNAME, SUNO_PROMPTS_JSON_FILENAME
from youtube_automation.utils.collection_paths import CollectionPaths

_AUDIO_EXTENSIONS = frozenset({".mp3", ".m4a", ".wav"})
_VALID_DOWNLOAD_FORMATS = frozenset({"mp3", "m4a", "wav"})
_SUNO_CLIPS_PER_PROMPT = 2
_ZIP_MAX_TOTAL_SIZE = 2 * 1024 * 1024 * 1024
_ZIP_MAX_SINGLE_FILE = 500 * 1024 * 1024
_ZIP_MAX_ENTRIES = 1000


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


class AtomicJsonWriter(Protocol):
    def __call__(self, target: Path, data: dict, *, prefix: str) -> None: ...


def _count_audio_files(music_dir: Path) -> int:
    if not music_dir.is_dir():
        return 0
    return sum(1 for f in music_dir.iterdir() if f.is_file() and f.suffix.lower() in _AUDIO_EXTENSIONS)


def _expected_download_count(pattern_count: int | None, explicit_expected: int | None = None) -> int | None:
    if pattern_count is None:
        return explicit_expected
    pattern_expected = pattern_count * _SUNO_CLIPS_PER_PROMPT
    if explicit_expected is None:
        return pattern_expected
    return max(pattern_expected, explicit_expected)


def _read_pattern_count(coll_dir: Path, *, default: int | None = None) -> int | None:
    prompts_path = coll_dir / DOCUMENTATION_DIRNAME / SUNO_PROMPTS_JSON_FILENAME
    if not prompts_path.is_file():
        return default
    try:
        prompts = json.loads(prompts_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default
    if not isinstance(prompts, list):
        return default
    return len(prompts)


def _parse_downloaded_payload(payload: object) -> DownloadedPayload:
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
        if not suno_playlist_url:
            raise DownloadedPayloadError("suno_playlist_url is required when download_path is present")
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


def _commit_staged_music_files(coll_dir: Path, staging_dir: Path) -> None:
    music_dir = CollectionPaths(coll_dir).music_dir
    music_dir.parent.mkdir(parents=True, exist_ok=True)
    backup_dir = Path(tempfile.mkdtemp(dir=str(coll_dir), prefix=".suno-music-backup-"))
    backup_payload = backup_dir / "02-Individual-music"
    had_existing_music_dir = music_dir.exists()

    try:
        if had_existing_music_dir:
            shutil.move(str(music_dir), str(backup_payload))
        music_dir.mkdir(parents=True, exist_ok=True)
        for staged in sorted(staging_dir.iterdir()):
            if staged.is_file():
                shutil.move(str(staged), str(music_dir / staged.name))
    except Exception:
        shutil.rmtree(music_dir, ignore_errors=True)
        if had_existing_music_dir and backup_payload.exists():
            shutil.move(str(backup_payload), str(music_dir))
        raise
    else:
        shutil.rmtree(backup_dir, ignore_errors=True)
    finally:
        if backup_dir.exists() and not backup_payload.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)


def _extract_downloaded_archive(coll_dir: Path, download_path: str, expected_count: int | None) -> int:
    resolved_dp = Path(download_path).resolve()
    staging_dir = Path(tempfile.mkdtemp(dir=str(coll_dir), prefix=".suno-music-"))
    try:
        placed_count = _extract_and_rename_music(coll_dir, str(resolved_dp), target_dir=staging_dir)
        if placed_count == 0:
            raise DownloadedArtifactError("ZIP extraction failed: 0 audio files placed")
        if expected_count is not None and placed_count < expected_count:
            raise DownloadedArtifactError(
                f"ZIP extraction incomplete: expected at least {expected_count} audio files, placed {placed_count}"
            )
        _commit_staged_music_files(coll_dir, staging_dir)
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
    return placed_count


def _apply_downloaded_artifacts(
    coll_dir: Path,
    payload: DownloadedPayload,
    *,
    atomic_json_write: AtomicJsonWriter,
) -> int:
    pattern_count = _read_pattern_count(coll_dir, default=0)
    expected_count = _expected_download_count(pattern_count, payload.expected_file_count)
    placed_count_for_response = payload.file_count
    file_count = payload.file_count
    paths = CollectionPaths(coll_dir)
    music_dir = paths.music_dir
    workflow_state_path = paths.workflow_state_path
    music_backup_dir: Path | None = None
    workflow_existed = workflow_state_path.exists()
    workflow_backup = workflow_state_path.read_bytes() if workflow_existed else None

    try:
        if payload.download_path:
            if music_dir.exists():
                music_backup_dir = Path(tempfile.mkdtemp(dir=str(coll_dir), prefix=".suno-music-apply-backup-"))
                shutil.copytree(music_dir, music_backup_dir / "02-Individual-music")
            placed_count = _extract_downloaded_archive(coll_dir, payload.download_path, expected_count)
            placed_count_for_response = placed_count
            file_count = placed_count

        _update_workflow_state_downloaded(
            coll_dir,
            file_count=file_count,
            suno_playlist_url=payload.suno_playlist_url,
            expected_file_count=expected_count,
            atomic_json_write=atomic_json_write,
        )
    except Exception as exc:
        if payload.download_path:
            shutil.rmtree(music_dir, ignore_errors=True)
            if music_backup_dir is not None:
                restored = music_backup_dir / "02-Individual-music"
                if restored.exists():
                    shutil.copytree(restored, music_dir)
            if workflow_backup is not None:
                workflow_state_path.parent.mkdir(parents=True, exist_ok=True)
                workflow_state_path.write_bytes(workflow_backup)
            elif not workflow_existed:
                workflow_state_path.unlink(missing_ok=True)
        if isinstance(exc, DownloadedArtifactError):
            raise
        raise DownloadedArtifactError(str(exc)) from exc
    finally:
        if music_backup_dir is not None:
            shutil.rmtree(music_backup_dir, ignore_errors=True)
    return placed_count_for_response


def _update_workflow_state_downloaded(
    coll_dir: Path,
    *,
    file_count: int,
    suno_playlist_url: str | None = None,
    expected_file_count: int | None = None,
    atomic_json_write: AtomicJsonWriter,
) -> None:
    ws_path = CollectionPaths(coll_dir).workflow_state_path
    data: dict = {}
    if ws_path.is_file():
        try:
            data = json.loads(ws_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    if not isinstance(data, dict):
        data = {}

    planning = data.setdefault("planning", {})
    if not isinstance(planning, dict):
        planning = {}
        data["planning"] = planning
    music = planning.setdefault("music", {})
    if not isinstance(music, dict):
        music = {}
        planning["music"] = music
    if suno_playlist_url:
        music["suno_playlist_url"] = suno_playlist_url
    pattern_count = _read_pattern_count(coll_dir)
    full_expected_count = _expected_download_count(pattern_count)
    effective_expected_count = _expected_download_count(pattern_count, expected_file_count)
    if (
        expected_file_count is not None
        and full_expected_count is not None
        and expected_file_count >= full_expected_count
    ):
        music["expected_file_count"] = expected_file_count

    assets = data.setdefault("assets", {})
    if not isinstance(assets, dict):
        assets = {}
        data["assets"] = assets
    if file_count > 0:
        if effective_expected_count is not None and file_count >= effective_expected_count:
            assets["music_downloaded"] = True
        elif effective_expected_count is None:
            assets["music_downloaded"] = True
        elif "music_downloaded" in assets:
            del assets["music_downloaded"]

    ws_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json_write(ws_path, data, prefix=".workflow-state-")


_SUNO_TRACK_PREFIX_RE = re.compile(r"^Track\s+\d+\s+(.+)$", re.IGNORECASE)
_LATIN_TITLE_TAIL_RE = re.compile(r"([A-Za-z][A-Za-z0-9 &'(),.!?:/-]*)$")


def _strip_suno_track_prefix(stem: str) -> str:
    match = _SUNO_TRACK_PREFIX_RE.match(stem.strip())
    if match is None:
        return stem.strip()
    return match.group(1).strip()


def _suno_name_lookup_candidates(name: str) -> list[str]:
    base = _strip_suno_track_prefix(name)
    candidates = [base]
    if " — " in base:
        candidates.append(base.split(" — ", 1)[1].strip())
    tail_match = _LATIN_TITLE_TAIL_RE.search(base)
    if tail_match:
        candidates.append(tail_match.group(1).strip())

    deduped: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in deduped:
            deduped.append(candidate)
    return deduped


def _build_name_to_index(coll_dir: Path) -> dict[str, int]:
    prompts_path = coll_dir / DOCUMENTATION_DIRNAME / SUNO_PROMPTS_JSON_FILENAME
    name_to_index: dict[str, int] = {}
    if not prompts_path.is_file():
        return name_to_index
    try:
        prompts = json.loads(prompts_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[yt-collection-serve] invalid {SUNO_PROMPTS_JSON_FILENAME}: {prompts_path}: {exc}")
        raise ValueError(f"invalid {SUNO_PROMPTS_JSON_FILENAME}") from exc
    if not isinstance(prompts, list):
        raise ValueError(f"invalid {SUNO_PROMPTS_JSON_FILENAME}: root must be a list")
    for i, entry in enumerate(prompts, 1):
        if not isinstance(entry, dict):
            raise ValueError(f"invalid {SUNO_PROMPTS_JSON_FILENAME}: entry {i} must be an object")
        full_name = entry.get("name", "")
        if not isinstance(full_name, str):
            raise ValueError(f"invalid {SUNO_PROMPTS_JSON_FILENAME}: entry {i}.name must be a string")
        parts = full_name.split(" — ", 1)
        english_name = parts[1] if len(parts) == 2 else full_name
        for candidate in _suno_name_lookup_candidates(english_name):
            name_to_index[candidate] = i
        for candidate in _suno_name_lookup_candidates(full_name):
            name_to_index[candidate] = i
        title = entry.get("title")
        if title is not None and not isinstance(title, str):
            raise ValueError(f"invalid {SUNO_PROMPTS_JSON_FILENAME}: entry {i}.title must be a string")
        if title:
            for candidate in _suno_name_lookup_candidates(title):
                name_to_index.setdefault(candidate, i)
    return name_to_index


def _is_safe_zip_member(filename: str) -> bool:
    path = PurePosixPath(filename)
    return not path.is_absolute() and all(part != ".." for part in path.parts)


def _extract_and_rename_music(coll_dir: Path, download_path: str, target_dir: Path | None = None) -> int:
    zip_path = Path(download_path)
    if not zip_path.is_file() or not zipfile.is_zipfile(zip_path):
        print(f"[yt-collection-serve] ZIP が無効です（skip）: {download_path}")
        return 0

    name_to_index = _build_name_to_index(coll_dir)
    music_dir = target_dir or CollectionPaths(coll_dir).music_dir
    music_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="suno-extract-")
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            infos = zf.infolist()
            if len(infos) > _ZIP_MAX_ENTRIES:
                print(f"[yt-collection-serve] ZIP entry 数が上限超過 ({len(infos)} > {_ZIP_MAX_ENTRIES}): skip")
                return 0
            total_size = 0
            for info in infos:
                if info.file_size > _ZIP_MAX_SINGLE_FILE:
                    print(
                        f"[yt-collection-serve] ZIP 内ファイルがサイズ上限超過"
                        f" ({info.filename}: {info.file_size} bytes): skip"
                    )
                    return 0
                total_size += info.file_size
            if total_size > _ZIP_MAX_TOTAL_SIZE:
                print(f"[yt-collection-serve] ZIP 総展開サイズが上限超過 ({total_size} bytes): skip")
                return 0
            audio_infos = [
                info for info in infos if not info.is_dir() and Path(info.filename).suffix.lower() in _AUDIO_EXTENSIONS
            ]
            for info in audio_infos:
                if not _is_safe_zip_member(info.filename):
                    print(f"[yt-collection-serve] 危険な ZIP entry をスキップします: {info.filename}")
                    continue
                zf.extract(info, tmp_dir)

        moved_count = 0
        for extracted in Path(tmp_dir).rglob("*"):
            if not extracted.is_file():
                continue
            ext = extracted.suffix.lower()
            if ext not in _AUDIO_EXTENSIONS:
                continue
            stem = extracted.stem
            if stem.endswith("_1"):
                lookups = _suno_name_lookup_candidates(stem[:-2])
                variant = "b"
            else:
                lookups = _suno_name_lookup_candidates(stem)
                variant = "a"
            lookup = lookups[0]
            track_num = None
            for candidate in lookups:
                if candidate in name_to_index:
                    lookup = candidate
                    track_num = name_to_index[candidate]
                    break
            if track_num is None:
                print(f"[yt-collection-serve] prompts に未対応の音声ファイルをスキップします: {extracted.name}")
                continue
            new_name = f"{track_num:02d}{variant}-{lookup}{ext}"
            dest = music_dir / new_name
            if dest.exists():
                raise ValueError(f"ZIP extraction output name collision: {dest.name}")
            shutil.move(str(extracted), str(dest))
            moved_count += 1

        print(f"[yt-collection-serve] 展開完了: {moved_count} files → {music_dir}")
        return moved_count
    except Exception as exc:
        print(f"[yt-collection-serve] ZIP 展開エラー（skip）: {exc}")
        return 0
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
