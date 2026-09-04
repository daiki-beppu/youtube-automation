"""Suno Download all ZIP の展開と music dir への配置。"""

from __future__ import annotations

import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from youtube_automation.core.adapters.media import CollectionPaths
from youtube_automation.domains.suno.downloaded.models import (
    DOCUMENTATION_DIRNAME,
    SUNO_PROMPTS_JSON_FILENAME,
    DownloadedArtifactError,
    PromptEntriesReader,
)
from youtube_automation.domains.suno.name_matching import (
    SunoNameIndex,
    split_suno_duplicate_stem,
    split_suno_studio_track_prefix,
    suno_filename_lookup_candidates,
    suno_name_lookup_candidates,
)

_AUDIO_EXTENSIONS = frozenset({".mp3", ".m4a", ".wav"})
_ZIP_MAX_TOTAL_SIZE = 2 * 1024 * 1024 * 1024
_ZIP_MAX_SINGLE_FILE = 500 * 1024 * 1024
_ZIP_MAX_ENTRIES = 1000


@dataclass(frozen=True, slots=True)
class DownloadedArchiveResult:
    audio_count: int
    placed_count: int


@dataclass(slots=True)
class _ExtractedAudio:
    """ZIP から展開した 1 メンバーの配置先。`variant` だけが Studio トラック順の割当で書き換わる。"""

    path: Path
    lookup: str
    track_num: int
    variant: str
    studio_track_number: int | None
    archive_order: int


def count_audio_files(music_dir: Path) -> int:
    return len(list_audio_files(music_dir))


def list_audio_files(music_dir: Path) -> tuple[Path, ...]:
    if not music_dir.is_dir():
        return ()
    return tuple(
        sorted(path for path in music_dir.iterdir() if path.is_file() and path.suffix.lower() in _AUDIO_EXTENSIONS)
    )


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


def extract_downloaded_archive_detailed(
    coll_dir: Path, download_path: str, *, prompt_entries_reader: PromptEntriesReader
) -> DownloadedArchiveResult:
    # 期待数未満の部分 ZIP も受け入れて配置する（#1913）。不足の記録と警告は
    # workflow-state（actual/missing_file_count）と downloaded API response が担う
    resolved_dp = Path(download_path).resolve()
    staging_dir = Path(tempfile.mkdtemp(dir=str(coll_dir), prefix=".suno-music-"))
    try:
        result = _extract_and_rename_music_to_dir(
            coll_dir,
            str(resolved_dp),
            staging_dir,
            prompt_entries_reader,
        )
        if result.placed_count == 0:
            raise DownloadedArtifactError("ZIP extraction failed: 0 audio files placed")
        commit_staged_music_files(coll_dir, staging_dir)
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
    return result


def extract_downloaded_archive(
    coll_dir: Path, download_path: str, *, prompt_entries_reader: PromptEntriesReader
) -> int:
    return extract_downloaded_archive_detailed(
        coll_dir,
        download_path,
        prompt_entries_reader=prompt_entries_reader,
    ).placed_count


_CANONICAL_MUSIC_FILENAME_RE = re.compile(r"^(?P<index>\d{2,})(?P<variant>[ab])-(?P<title>.+)$")
# ブラウザ手動 DL の重複ベース名（`Title (1).mp3`）と Suno ZIP 由来の `Title_1.mp3` を同一 entry の別 clip とみなす
_OUTPUT_STEM_SEPARATOR_RE = re.compile(r"[\\/]+")
_OUTPUT_STEM_SPACE_RE = re.compile(r"\s+")


def _studio_track_prefix_aliases(stem: str) -> tuple[frozenset[str], int | None]:
    """Studio の数字 prefix を剥がしてはじめて得られる候補と、そのトラック番号を返す。"""
    base, studio_track_number = split_suno_studio_track_prefix(stem)
    if studio_track_number is None:
        return frozenset(), None
    return frozenset(suno_name_lookup_candidates(base)), studio_track_number


def _zip_member_lookup_candidates(filename: str) -> list[tuple[str, str, int | None]]:
    member_path = PurePosixPath(filename)
    relative_stem = member_path.with_suffix("").as_posix()
    raw_stems = [relative_stem, member_path.stem]
    deduped: list[tuple[str, str, int | None]] = []
    for raw_stem in raw_stems:
        stem, duplicate_number = split_suno_duplicate_stem(raw_stem)
        studio_aliases, studio_track_number = _studio_track_prefix_aliases(stem)
        variant = "b" if duplicate_number == 1 else "a"
        for candidate in suno_filename_lookup_candidates(stem):
            # prefix を剥がしてはじめて照合できた候補だけを Studio トラックとして扱う。
            # 数字始まりの曲名が prefix なしで一致した場合は既存どおり重複連番で variant を決める
            is_studio_alias = candidate in studio_aliases and duplicate_number == 0
            item = (candidate, variant, studio_track_number if is_studio_alias else None)
            if item not in deduped:
                deduped.append(item)
    return deduped


def _studio_track_sort_key(item: _ExtractedAudio) -> tuple[int, int]:
    """Studio トラック番号を数値昇順に、同番号は ZIP 内の出現順に並べる。"""
    track_number = item.studio_track_number
    return (-1 if track_number is None else track_number, item.archive_order)


def _sanitize_output_stem(stem: str) -> str:
    sanitized = _OUTPUT_STEM_SEPARATOR_RE.sub(" - ", stem)
    sanitized = _OUTPUT_STEM_SPACE_RE.sub(" ", sanitized).strip(" .")
    if not sanitized:
        raise ValueError("ZIP extraction output name is empty after sanitization")
    return sanitized


def _build_name_to_index(coll_dir: Path, prompt_entries_reader: PromptEntriesReader) -> SunoNameIndex:
    prompts_path = coll_dir / DOCUMENTATION_DIRNAME / SUNO_PROMPTS_JSON_FILENAME
    if not prompts_path.is_file():
        return SunoNameIndex.build([])
    try:
        prompts = prompt_entries_reader(coll_dir)
    except ValueError as exc:
        print(f"[yt-collection-serve] invalid {SUNO_PROMPTS_JSON_FILENAME}: {prompts_path}: {exc}")
        raise ValueError(f"invalid {SUNO_PROMPTS_JSON_FILENAME}") from exc
    alias_groups: list[tuple[int, tuple[str, ...]]] = []
    for i, entry in enumerate(prompts, 1):
        if not isinstance(entry, dict):
            raise ValueError(f"invalid {SUNO_PROMPTS_JSON_FILENAME}: entry {i} must be an object")
        full_name = entry.get("name", "")
        if not isinstance(full_name, str):
            raise ValueError(f"invalid {SUNO_PROMPTS_JSON_FILENAME}: entry {i}.name must be a string")
        title = entry.get("title")
        if title is not None and not isinstance(title, str):
            raise ValueError(f"invalid {SUNO_PROMPTS_JSON_FILENAME}: entry {i}.title must be a string")
        sources = (full_name, title) if title else (full_name,)
        aliases = tuple(
            dict.fromkeys(candidate for source in sources for candidate in suno_name_lookup_candidates(source))
        )
        alias_groups.append((i, aliases))
    return SunoNameIndex.build(alias_groups)


def _music_stem_lookup_candidates(stem: str) -> list[tuple[str, int, int | None]]:
    """非正準形 stem から (照合候補, 重複連番, Studio トラック番号) を列挙する。

    重複連番 0 は suffix なしの基準ファイル。Studio トラック番号は数字 prefix を
    剥がしてはじめて照合できた候補にだけ付き、ZIP 経路と同じ順序で variant を決めるために使う。
    """
    candidates: list[tuple[str, int, int | None]] = []
    studio_aliases, studio_track_number = _studio_track_prefix_aliases(stem)
    for candidate in suno_filename_lookup_candidates(stem):
        candidates.append((candidate, 0, studio_track_number if candidate in studio_aliases else None))
    base, dup_no = split_suno_duplicate_stem(stem)
    if dup_no:
        for candidate in suno_name_lookup_candidates(base):
            item = (candidate, dup_no, None)
            if item not in candidates:
                candidates.append(item)
    return candidates


def canonicalize_noncanonical_music_files(
    coll_dir: Path, music_dir: Path, *, prompt_entries_reader: PromptEntriesReader
) -> list[tuple[str, str]]:
    """music_dir 内の非正準形音声ファイルを suno-prompts.json と照合し `NN{a|b}-Title.ext` へリネームする。

    どの entry とも照合できないファイルはリネームせず残す（呼び出し側の突合で unknown として fail-loud）。
    同一 entry へ照合されたファイルは重複連番順に、既存の正準形が占有していない variant へ割り当てる。
    variant（a/b）に収まらない場合と リネーム先衝突は ValueError で停止し、部分リネームを行わない。
    戻り値はリネームした (旧ファイル名, 新ファイル名) の一覧。
    """
    if not music_dir.is_dir():
        return []
    name_index = _build_name_to_index(coll_dir, prompt_entries_reader)
    if not name_index:
        return []

    occupied_variants: dict[int, set[str]] = {}
    # ソートキーは (重複連番, Studio トラック番号, ファイル名)。Studio トラック番号は数値で比較するため
    # `2 Title.wav` と `10 Title.wav` がファイル名の辞書順で逆転しない。prefix なしは -1 で先頭に置く
    matched_files: dict[int, list[tuple[int, int, str, Path, str]]] = {}
    for audio_path in sorted(music_dir.iterdir()):
        if not audio_path.is_file() or audio_path.suffix.lower() not in _AUDIO_EXTENSIONS:
            continue
        canonical_match = _CANONICAL_MUSIC_FILENAME_RE.fullmatch(audio_path.stem)
        if canonical_match is not None:
            occupied_variants.setdefault(int(canonical_match.group("index")), set()).add(
                canonical_match.group("variant")
            )
            continue
        lookup_candidates = _music_stem_lookup_candidates(audio_path.stem)
        resolved = name_index.resolve_with_candidate(candidate for candidate, _, _ in lookup_candidates)
        if resolved is not None:
            track_num, lookup = resolved
            dup_no, studio_track_number = next(
                (number, studio) for candidate, number, studio in lookup_candidates if candidate == lookup
            )
            track_order = -1 if studio_track_number is None else studio_track_number
            matched_files.setdefault(track_num, []).append((dup_no, track_order, audio_path.name, audio_path, lookup))

    renames: list[tuple[Path, Path]] = []
    planned_dests: set[str] = set()
    for track_num, files in sorted(matched_files.items()):
        files.sort()
        free_variants = [v for v in ("a", "b") if v not in occupied_variants.get(track_num, set())]
        if len(files) > len(free_variants):
            names = ", ".join(name for _, _, name, _, _ in files)
            raise ValueError(
                f"entry {track_num:02d} へ照合されたファイルが variant (a/b) の空きを超えています: {names}"
            )
        for (_, _, _, audio_path, lookup), variant in zip(files, free_variants, strict=False):
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


def _extract_and_rename_music_to_dir(
    coll_dir: Path,
    download_path: str,
    target_dir: Path,
    prompt_entries_reader: PromptEntriesReader,
) -> DownloadedArchiveResult:
    zip_path = Path(download_path)
    if not zip_path.is_file() or not zipfile.is_zipfile(zip_path):
        print(f"[yt-collection-serve] ZIP が無効です（skip）: {download_path}")
        return DownloadedArchiveResult(audio_count=0, placed_count=0)

    name_index = _build_name_to_index(coll_dir, prompt_entries_reader)
    target_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="suno-extract-")
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            infos = zf.infolist()
            if len(infos) > _ZIP_MAX_ENTRIES:
                print(f"[yt-collection-serve] ZIP entry 数が上限超過 ({len(infos)} > {_ZIP_MAX_ENTRIES}): skip")
                return DownloadedArchiveResult(audio_count=0, placed_count=0)
            total_size = 0
            for info in infos:
                if info.file_size > _ZIP_MAX_SINGLE_FILE:
                    print(
                        f"[yt-collection-serve] ZIP 内ファイルがサイズ上限超過"
                        f" ({info.filename}: {info.file_size} bytes): skip"
                    )
                    return DownloadedArchiveResult(audio_count=0, placed_count=0)
                total_size += info.file_size
            if total_size > _ZIP_MAX_TOTAL_SIZE:
                print(f"[yt-collection-serve] ZIP 総展開サイズが上限超過 ({total_size} bytes): skip")
                return DownloadedArchiveResult(audio_count=0, placed_count=0)
            audio_infos = [
                info for info in infos if not info.is_dir() and Path(info.filename).suffix.lower() in _AUDIO_EXTENSIONS
            ]
            extracted_audio: list[_ExtractedAudio] = []
            for archive_order, info in enumerate(audio_infos):
                if not _is_safe_zip_member(info.filename):
                    print(f"[yt-collection-serve] 危険な ZIP entry をスキップします: {info.filename}")
                    continue
                extracted_path = Path(zf.extract(info, tmp_dir))
                lookup_candidates = _zip_member_lookup_candidates(info.filename)
                resolved = name_index.resolve_with_candidate(candidate for candidate, _, _ in lookup_candidates)
                if resolved is None:
                    print(f"[yt-collection-serve] prompts に未対応の音声ファイルをスキップします: {info.filename}")
                    continue
                track_num, lookup = resolved
                variant, studio_track_number = next(
                    (variant, studio_track_number)
                    for candidate, variant, studio_track_number in lookup_candidates
                    if candidate == lookup
                )
                extracted_audio.append(
                    _ExtractedAudio(
                        path=extracted_path,
                        lookup=lookup,
                        track_num=track_num,
                        variant=variant,
                        studio_track_number=studio_track_number,
                        archive_order=archive_order,
                    )
                )

        studio_matches: dict[int, list[_ExtractedAudio]] = {}
        occupied_variants: dict[int, set[str]] = {}
        for item in extracted_audio:
            if item.studio_track_number is None:
                occupied_variants.setdefault(item.track_num, set()).add(item.variant)
            else:
                studio_matches.setdefault(item.track_num, []).append(item)
        for track_num, matches in studio_matches.items():
            # Studio のトラック番号は数値で昇順に並べる。同番号は ZIP 内の出現順で決める
            matches.sort(key=_studio_track_sort_key)
            free_variants = [
                variant for variant in ("a", "b") if variant not in occupied_variants.get(track_num, set())
            ]
            if len(matches) > len(free_variants):
                names = ", ".join(item.path.name for item in matches)
                raise ValueError(f"entry {track_num:02d} matched more files than variants (a/b): {names}")
            for item, variant in zip(matches, free_variants, strict=False):
                item.variant = variant

        moved_count = 0
        for item in extracted_audio:
            if not item.path.is_file():
                print(f"[yt-collection-serve] ZIP entry の展開結果が見つかりません: {item.path}")
                continue
            ext = item.path.suffix.lower()
            if ext not in _AUDIO_EXTENSIONS:
                continue
            new_name = f"{item.track_num:02d}{item.variant}-{_sanitize_output_stem(item.lookup)}{ext}"
            dest = target_dir / new_name
            if dest.exists():
                raise ValueError(f"ZIP extraction output name collision: {dest.name}")
            shutil.move(str(item.path), str(dest))
            moved_count += 1

        print(f"[yt-collection-serve] 展開完了: {moved_count} files → {target_dir}")
        return DownloadedArchiveResult(audio_count=len(audio_infos), placed_count=moved_count)
    except zipfile.BadZipFile as exc:
        print(f"[yt-collection-serve] ZIP 展開エラー（skip）: {exc}")
        return DownloadedArchiveResult(audio_count=0, placed_count=0)
    except (OSError, ValueError, shutil.Error) as exc:
        print(f"[yt-collection-serve] ZIP 展開エラー: {exc}")
        raise DownloadedArtifactError(f"ZIP extraction failed: {exc}") from exc
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def extract_and_rename_music(
    coll_dir: Path,
    download_path: str,
    *,
    prompt_entries_reader: PromptEntriesReader,
    target_dir: Path | None = None,
) -> int:
    if target_dir is not None:
        return _extract_and_rename_music_to_dir(coll_dir, download_path, target_dir, prompt_entries_reader).placed_count

    staging_dir = Path(tempfile.mkdtemp(dir=str(coll_dir), prefix=".suno-music-"))
    try:
        placed_count = _extract_and_rename_music_to_dir(
            coll_dir, download_path, staging_dir, prompt_entries_reader
        ).placed_count
        if placed_count > 0:
            try:
                commit_staged_music_files(coll_dir, staging_dir)
            except (OSError, shutil.Error) as exc:
                raise DownloadedArtifactError(f"ZIP extraction commit failed: {exc}") from exc
        return placed_count
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
