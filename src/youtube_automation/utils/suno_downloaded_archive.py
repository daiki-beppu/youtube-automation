"""Suno Download all ZIP の展開と music dir への配置。"""

from __future__ import annotations

import re
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from youtube_automation.utils.collection_paths import CollectionPaths
from youtube_automation.utils.suno_artifact_contracts import DOCUMENTATION_DIRNAME, SUNO_PROMPTS_JSON_FILENAME
from youtube_automation.utils.suno_downloaded_payload import DownloadedArtifactError
from youtube_automation.utils.suno_prompts_json import read_suno_prompt_entries

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


_CANONICAL_MUSIC_FILENAME_RE = re.compile(r"^(?P<index>\d{2,})(?P<variant>[ab])-(?P<title>.+)$")
# ブラウザ手動 DL の重複ベース名（`Title (1).mp3`）と Suno ZIP 由来の `Title_1.mp3` を同一 entry の別 clip とみなす
_DUP_SUFFIX_RE = re.compile(r"^(?P<base>.+?)(?:\s*\((?P<paren>\d+)\)|_(?P<underscore>\d+))$")
_SUNO_TRACK_PREFIX_RE = re.compile(r"^Track\s+\d+\s+(.+)$", re.IGNORECASE)
_LATIN_TITLE_TAIL_RE = re.compile(r"([A-Za-z][A-Za-z0-9 &'(),.!?:/-]*)$")
# Suno はダウンロード ZIP 内のファイル名からアポストロフィを除去する（例: Greed's Rhythm → Greeds Rhythm.m4a）。
# typographic apostrophe（U+2019）も同一視する。それ以外の記号は Suno 仕様が未確認のため除去しない
_APOSTROPHE_RE = re.compile(r"['’]")
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
        prompts = read_suno_prompt_entries(coll_dir)
    except ValueError as exc:
        print(f"[yt-collection-serve] invalid {SUNO_PROMPTS_JSON_FILENAME}: {prompts_path}: {exc}")
        raise ValueError(f"invalid {SUNO_PROMPTS_JSON_FILENAME}") from exc
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
    # Suno が ZIP ファイル名から除去するアポストロフィの除去版キーを fallback として登録する (#1787)。
    # exact match を優先するため setdefault（既存キーは上書きしない）
    for key, track_index in list(name_to_index.items()):
        stripped = _APOSTROPHE_RE.sub("", key)
        if stripped and stripped != key:
            name_to_index.setdefault(stripped, track_index)
    return name_to_index


def _music_stem_lookup_candidates(stem: str) -> list[tuple[str, int]]:
    """非正準形 stem から (照合候補, 重複連番) を列挙する。重複連番 0 は suffix なしの基準ファイル。"""
    candidates: list[tuple[str, int]] = []
    for candidate in _suno_name_lookup_candidates(stem):
        candidates.append((candidate, 0))
    dup_match = _DUP_SUFFIX_RE.fullmatch(stem.strip())
    if dup_match is not None:
        dup_no = int(dup_match.group("paren") or dup_match.group("underscore"))
        for candidate in _suno_name_lookup_candidates(dup_match.group("base")):
            item = (candidate, dup_no)
            if item not in candidates:
                candidates.append(item)
    return candidates


def canonicalize_noncanonical_music_files(coll_dir: Path, music_dir: Path) -> list[tuple[str, str]]:
    """music_dir 内の非正準形音声ファイルを suno-prompts.json と照合し `NN{a|b}-Title.ext` へリネームする。

    どの entry とも照合できないファイルはリネームせず残す（呼び出し側の突合で unknown として fail-loud）。
    同一 entry へ照合されたファイルは重複連番順に、既存の正準形が占有していない variant へ割り当てる。
    variant（a/b）に収まらない場合と リネーム先衝突は ValueError で停止し、部分リネームを行わない。
    戻り値はリネームした (旧ファイル名, 新ファイル名) の一覧。
    """
    if not music_dir.is_dir():
        return []
    name_to_index = _build_name_to_index(coll_dir)
    if not name_to_index:
        return []

    occupied_variants: dict[int, set[str]] = {}
    matched_files: dict[int, list[tuple[int, str, Path, str]]] = {}
    for audio_path in sorted(music_dir.iterdir()):
        if not audio_path.is_file() or audio_path.suffix.lower() not in _AUDIO_EXTENSIONS:
            continue
        canonical_match = _CANONICAL_MUSIC_FILENAME_RE.fullmatch(audio_path.stem)
        if canonical_match is not None:
            occupied_variants.setdefault(int(canonical_match.group("index")), set()).add(
                canonical_match.group("variant")
            )
            continue
        for candidate, dup_no in _music_stem_lookup_candidates(audio_path.stem):
            track_num = name_to_index.get(candidate)
            if track_num is not None:
                matched_files.setdefault(track_num, []).append((dup_no, audio_path.name, audio_path, candidate))
                break

    renames: list[tuple[Path, Path]] = []
    planned_dests: set[str] = set()
    for track_num, files in sorted(matched_files.items()):
        files.sort()
        free_variants = [v for v in ("a", "b") if v not in occupied_variants.get(track_num, set())]
        if len(files) > len(free_variants):
            names = ", ".join(name for _, name, _, _ in files)
            raise ValueError(
                f"entry {track_num:02d} へ照合されたファイルが variant (a/b) の空きを超えています: {names}"
            )
        for (_, _, audio_path, lookup), variant in zip(files, free_variants, strict=False):
            new_name = f"{track_num:02d}{variant}-{_sanitize_output_stem(lookup)}{audio_path.suffix.lower()}"
            dest = music_dir / new_name
            if dest.exists() or new_name in planned_dests:
                raise ValueError(f"リネーム先が既に存在します: {new_name}")
            planned_dests.add(new_name)
            renames.append((audio_path, dest))

    for src, dest in renames:
        src.rename(dest)
    return [(src.name, dest.name) for src, dest in renames]


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
