"""Suno Download all ZIP の展開と music dir への配置。"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from youtube_automation.utils.collection_paths import CollectionPaths
from youtube_automation.utils.suno_artifact_contracts import DOCUMENTATION_DIRNAME, SUNO_PROMPTS_JSON_FILENAME
from youtube_automation.utils.suno_downloaded_payload import DownloadedArtifactError

_AUDIO_EXTENSIONS = frozenset({".mp3", ".m4a", ".wav"})
_ZIP_MAX_TOTAL_SIZE = 2 * 1024 * 1024 * 1024
_ZIP_MAX_SINGLE_FILE = 500 * 1024 * 1024
_ZIP_MAX_ENTRIES = 1000


def count_audio_files(music_dir: Path) -> int:
    if not music_dir.is_dir():
        return 0
    return sum(1 for f in music_dir.iterdir() if f.is_file() and f.suffix.lower() in _AUDIO_EXTENSIONS)


def commit_staged_music_files(coll_dir: Path, staging_dir: Path) -> None:
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
    except (OSError, shutil.Error):
        shutil.rmtree(music_dir, ignore_errors=True)
        if had_existing_music_dir and backup_payload.exists():
            shutil.move(str(backup_payload), str(music_dir))
        raise
    else:
        shutil.rmtree(backup_dir, ignore_errors=True)
    finally:
        if backup_dir.exists() and not backup_payload.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)


def extract_downloaded_archive(coll_dir: Path, download_path: str, expected_count: int | None) -> int:
    resolved_dp = Path(download_path).resolve()
    staging_dir = Path(tempfile.mkdtemp(dir=str(coll_dir), prefix=".suno-music-"))
    try:
        placed_count = extract_and_rename_music(coll_dir, str(resolved_dp), target_dir=staging_dir)
        if placed_count == 0:
            raise DownloadedArtifactError("ZIP extraction failed: 0 audio files placed")
        if expected_count is not None and placed_count < expected_count:
            raise DownloadedArtifactError(
                f"ZIP extraction incomplete: expected at least {expected_count} audio files, placed {placed_count}"
            )
        commit_staged_music_files(coll_dir, staging_dir)
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
    return placed_count


_SUNO_TRACK_PREFIX_RE = re.compile(r"^Track\s+\d+\s+(.+)$", re.IGNORECASE)
_LATIN_TITLE_TAIL_RE = re.compile(r"([A-Za-z][A-Za-z0-9 &'(),.!?:/-]*)$")
_OUTPUT_STEM_SEPARATOR_RE = re.compile(r"[\\/]+")
_OUTPUT_STEM_SPACE_RE = re.compile(r"\s+")


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


def _zip_member_lookup_candidates(filename: str) -> list[tuple[str, str]]:
    member_path = PurePosixPath(filename)
    relative_stem = member_path.with_suffix("").as_posix()
    raw_stems = [relative_stem, member_path.stem]
    deduped: list[tuple[str, str]] = []
    for raw_stem in raw_stems:
        if raw_stem.endswith("_1"):
            stem = raw_stem[:-2]
            variant = "b"
        else:
            stem = raw_stem
            variant = "a"
        for candidate in _suno_name_lookup_candidates(stem):
            item = (candidate, variant)
            if item not in deduped:
                deduped.append(item)
    return deduped


def _sanitize_output_stem(stem: str) -> str:
    sanitized = _OUTPUT_STEM_SEPARATOR_RE.sub(" - ", stem)
    sanitized = _OUTPUT_STEM_SPACE_RE.sub(" ", sanitized).strip(" .")
    if not sanitized:
        raise ValueError("ZIP extraction output name is empty after sanitization")
    return sanitized


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


def _extract_and_rename_music_to_dir(coll_dir: Path, download_path: str, target_dir: Path) -> int:
    zip_path = Path(download_path)
    if not zip_path.is_file() or not zipfile.is_zipfile(zip_path):
        print(f"[yt-collection-serve] ZIP が無効です（skip）: {download_path}")
        return 0

    name_to_index = _build_name_to_index(coll_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
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
            extracted_audio: list[tuple[Path, str, int, str]] = []
            for info in audio_infos:
                if not _is_safe_zip_member(info.filename):
                    print(f"[yt-collection-serve] 危険な ZIP entry をスキップします: {info.filename}")
                    continue
                extracted_path = Path(zf.extract(info, tmp_dir))
                track_num = None
                lookup = ""
                variant = "a"
                for candidate, candidate_variant in _zip_member_lookup_candidates(info.filename):
                    if candidate in name_to_index:
                        lookup = candidate
                        variant = candidate_variant
                        track_num = name_to_index[candidate]
                        break
                if track_num is None:
                    print(f"[yt-collection-serve] prompts に未対応の音声ファイルをスキップします: {info.filename}")
                    continue
                extracted_audio.append((extracted_path, lookup, track_num, variant))

        moved_count = 0
        for extracted, lookup, track_num, variant in extracted_audio:
            if not extracted.is_file():
                print(f"[yt-collection-serve] ZIP entry の展開結果が見つかりません: {extracted}")
                continue
            ext = extracted.suffix.lower()
            if ext not in _AUDIO_EXTENSIONS:
                continue
            new_name = f"{track_num:02d}{variant}-{_sanitize_output_stem(lookup)}{ext}"
            dest = target_dir / new_name
            if dest.exists():
                raise ValueError(f"ZIP extraction output name collision: {dest.name}")
            shutil.move(str(extracted), str(dest))
            moved_count += 1

        print(f"[yt-collection-serve] 展開完了: {moved_count} files → {target_dir}")
        return moved_count
    except zipfile.BadZipFile as exc:
        print(f"[yt-collection-serve] ZIP 展開エラー（skip）: {exc}")
        return 0
    except (OSError, ValueError, shutil.Error) as exc:
        print(f"[yt-collection-serve] ZIP 展開エラー: {exc}")
        raise DownloadedArtifactError(f"ZIP extraction failed: {exc}") from exc
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def extract_and_rename_music(coll_dir: Path, download_path: str, target_dir: Path | None = None) -> int:
    if target_dir is not None:
        return _extract_and_rename_music_to_dir(coll_dir, download_path, target_dir)

    staging_dir = Path(tempfile.mkdtemp(dir=str(coll_dir), prefix=".suno-music-"))
    try:
        placed_count = _extract_and_rename_music_to_dir(coll_dir, download_path, staging_dir)
        if placed_count > 0:
            try:
                commit_staged_music_files(coll_dir, staging_dir)
            except (OSError, shutil.Error) as exc:
                raise DownloadedArtifactError(f"ZIP extraction commit failed: {exc}") from exc
        return placed_count
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
