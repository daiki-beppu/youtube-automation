#!/usr/bin/env python3
"""Select Suno downloaded clips before masterup.

Suno generates two clips per prompt. For vocal prompts, keep one winner per
prompt and move the other clips to stock. For instrumental prompts, keep both
clips. In both modes, filter obviously broken durations before selection.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from youtube_automation.utils.collection_paths import resolve_collection_dir
from youtube_automation.utils.exceptions import ValidationError
from youtube_automation.utils.probe import probe_duration
from youtube_automation.utils.skill_config import load_skill_config
from youtube_automation.utils.suno_artifact_contracts import DOCUMENTATION_DIRNAME, SUNO_PROMPTS_JSON_FILENAME

_AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav"}
_DOWNLOADED_NAME_RE = re.compile(r"^(?P<idx>\d{2,})(?P<variant>[a-z])?-(?P<title>.+)$", re.IGNORECASE)
_BRACKET_LINE_RE = re.compile(r"^\s*\[[^\]]+\]\s*$")
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_DEFAULT_SELECTION_LOG = "01-master/.selection.log"
_DEFAULT_STOCK_DIR = "assets/stock/music/b-side"
_DEFAULT_FILENAME_TEMPLATE = "{collection_slug}__{song_id}__{title_slug}.{ext}"


@dataclass(frozen=True)
class PromptEntry:
    index: int
    title: str
    has_lyrics: bool


@dataclass(frozen=True)
class Candidate:
    path: Path
    prompt_index: int
    variant: str
    title: str
    duration: float

    @property
    def ext(self) -> str:
        return self.path.suffix.lower().lstrip(".")

    @property
    def song_id(self) -> str:
        return self.path.stem


@dataclass
class SelectionResult:
    kept: list[Path]
    stocked: list[Path]
    deleted: list[Path]
    dropped: list[Candidate]
    winners: list[Candidate]
    mode_counts: dict[str, int]
    log_path: Path


def _title_from_prompt(entry: dict[str, Any], index: int) -> str:
    raw = entry.get("title") or entry.get("name") or f"track-{index:02d}"
    if not isinstance(raw, str):
        raise ValidationError(f"{SUNO_PROMPTS_JSON_FILENAME}: entry {index}.title/name must be a string")
    parts = raw.split(" — ", 1)
    return (parts[1] if len(parts) == 2 else raw).strip() or f"track-{index:02d}"


def _has_substantive_lyrics(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    lines = []
    for line in value.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _BRACKET_LINE_RE.match(stripped):
            continue
        lines.append(stripped)
    text = " ".join(lines).strip()
    if not text:
        return False
    lowered = text.lower()
    return lowered not in {"instrumental", "extended outro"}


def load_prompts(collection_dir: Path) -> list[PromptEntry]:
    path = collection_dir / DOCUMENTATION_DIRNAME / SUNO_PROMPTS_JSON_FILENAME
    if not path.is_file():
        raise ValidationError(f"{SUNO_PROMPTS_JSON_FILENAME} が見つかりません: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValidationError(f"{SUNO_PROMPTS_JSON_FILENAME} root must be a list")
    prompts: list[PromptEntry] = []
    for i, entry in enumerate(data, 1):
        if not isinstance(entry, dict):
            raise ValidationError(f"{SUNO_PROMPTS_JSON_FILENAME}: entry {i} must be an object")
        prompts.append(
            PromptEntry(
                index=i,
                title=_title_from_prompt(entry, i),
                has_lyrics=_has_substantive_lyrics(entry.get("lyrics")),
            )
        )
    return prompts


def _slugify(value: str) -> str:
    slug = _SLUG_RE.sub("-", value.lower()).strip("-")
    return slug or "untitled"


def _collection_root(collection_dir: Path) -> Path:
    for parent in collection_dir.parents:
        if parent.name == "collections":
            return parent.parent
    return collection_dir.parent


def _parse_candidate(path: Path) -> tuple[int, str, str] | None:
    if path.suffix.lower() not in _AUDIO_EXTENSIONS:
        return None
    match = _DOWNLOADED_NAME_RE.match(path.stem)
    if match is None:
        return None
    return int(match.group("idx")), (match.group("variant") or ""), match.group("title")


def collect_candidates(collection_dir: Path) -> list[Candidate]:
    music_dir = collection_dir / "02-Individual-music"
    if not music_dir.is_dir():
        raise ValidationError(f"02-Individual-music が見つかりません: {music_dir}")
    candidates: list[Candidate] = []
    for path in sorted(music_dir.iterdir(), key=lambda p: p.name):
        if not path.is_file():
            continue
        parsed = _parse_candidate(path)
        if parsed is None:
            continue
        prompt_index, variant, title = parsed
        duration = probe_duration(path)
        if duration is None:
            raise ValidationError(f"音源 duration の probe に失敗: {path}")
        candidates.append(
            Candidate(
                path=path,
                prompt_index=prompt_index,
                variant=variant,
                title=title,
                duration=duration,
            )
        )
    if not candidates:
        raise ValidationError(f"選別対象の音源が見つかりません: {music_dir}")
    return candidates


def _is_duration_out_of_range(candidate: Candidate, *, min_song_sec: float | None, max_song_sec: float | None) -> bool:
    if min_song_sec is not None and candidate.duration < min_song_sec:
        return True
    if max_song_sec is not None and candidate.duration > max_song_sec:
        return True
    return False


def _stock_destination(candidate: Candidate, collection_dir: Path, stock_cfg: dict[str, Any]) -> Path:
    root = _collection_root(collection_dir)
    stock_dir = root / str(stock_cfg.get("dir") or _DEFAULT_STOCK_DIR)
    template = str(stock_cfg.get("filename_template") or _DEFAULT_FILENAME_TEMPLATE)
    name = template.format(
        collection_slug=collection_dir.name,
        song_id=_slugify(candidate.song_id),
        title_slug=_slugify(candidate.title),
        ext=candidate.ext,
    )
    return stock_dir / name


def _move_to_stock(candidate: Candidate, collection_dir: Path, stock_cfg: dict[str, Any], *, dry_run: bool) -> Path:
    dest = _stock_destination(candidate, collection_dir, stock_cfg)
    on_duplicate = str(stock_cfg.get("on_duplicate") or "skip")
    if dry_run:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        if on_duplicate == "skip":
            candidate.path.unlink()
            return dest
        if on_duplicate == "overwrite":
            dest.unlink()
        elif on_duplicate == "fail":
            raise ValidationError(f"stock destination already exists: {dest}")
        else:
            raise ValidationError(f"invalid stock.on_duplicate: {on_duplicate}")
    shutil.move(str(candidate.path), str(dest))
    return dest


def _rename_winner(candidate: Candidate, *, dry_run: bool) -> Path:
    dest = candidate.path.with_name(f"{candidate.prompt_index:02d}-{candidate.title}{candidate.path.suffix.lower()}")
    if candidate.path == dest:
        return dest
    if dry_run:
        return dest
    if dest.exists():
        raise ValidationError(f"winner destination already exists: {dest}")
    candidate.path.rename(dest)
    return dest


def _write_log(
    *,
    collection_dir: Path,
    log_path: Path,
    seed: int,
    kept: list[Path],
    stocked: list[Path],
    deleted: list[Path],
    dropped: list[Candidate],
    winners: list[Candidate],
    mode_counts: dict[str, int],
    dry_run: bool,
) -> None:
    winner_lines = [
        f"{c.prompt_index:02d} {c.variant or '-'} {c.title} duration={c.duration:.2f}s source={c.path.name}"
        for c in winners
    ]
    dropped_lines = [
        f"{c.prompt_index:02d} {c.variant or '-'} {c.title} duration={c.duration:.2f}s source={c.path.name}"
        for c in dropped
    ]
    lines = [
        f"executed_at={datetime.now(timezone.utc).isoformat()}",
        f"seed={seed}",
        f"dry_run={str(dry_run).lower()}",
        f"vocal_groups={mode_counts.get('vocal', 0)}",
        f"instrumental_groups={mode_counts.get('instrumental', 0)}",
        "---",
        "[kept]",
        *[str(p.relative_to(collection_dir)) if p.is_relative_to(collection_dir) else str(p) for p in kept],
        "[winners]",
        *winner_lines,
        "[dropped_duration]",
        *dropped_lines,
        "[stocked]",
        *[str(p) for p in stocked],
        "[deleted]",
        *[str(p) for p in deleted],
        "",
    ]
    if dry_run:
        print("\n".join(lines))
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\n".join(lines), encoding="utf-8")


def select_suno_tracks(collection_dir: Path, cfg: dict[str, Any], *, dry_run: bool = False) -> SelectionResult:
    pair_cfg = cfg.get("pair_selection") or {}
    mode = str(pair_cfg.get("mode") or "auto")
    if mode == "never":
        log_path = collection_dir / str(pair_cfg.get("selection_log_path") or _DEFAULT_SELECTION_LOG)
        return SelectionResult([], [], [], [], [], {}, log_path)
    if mode != "auto":
        raise ValidationError(f"pair_selection.mode は auto / never のいずれかです: {mode}")

    min_song_sec = pair_cfg.get("min_song_sec", 45)
    max_song_sec = pair_cfg.get("max_song_sec", 300)
    min_sec = None if min_song_sec is None else float(min_song_sec)
    max_sec = None if max_song_sec is None else float(max_song_sec)
    if min_sec is not None and min_sec < 0:
        raise ValidationError("pair_selection.min_song_sec は 0 以上または null")
    if max_sec is not None and max_sec <= 0:
        raise ValidationError("pair_selection.max_song_sec は 0 より大きい値または null")
    if min_sec is not None and max_sec is not None and min_sec >= max_sec:
        raise ValidationError("pair_selection.min_song_sec は max_song_sec 未満にしてください")

    out_of_range_action = str(pair_cfg.get("out_of_range_action") or "stock")
    if out_of_range_action not in {"stock", "delete"}:
        raise ValidationError("pair_selection.out_of_range_action は stock / delete のいずれかです")

    strategy = str(pair_cfg.get("strategy") or "random")
    if strategy != "random":
        raise ValidationError(f"pair_selection.strategy は現在 random のみ対応: {strategy}")

    seed_value = pair_cfg.get("random_seed")
    if seed_value is None:
        seed = random.SystemRandom().randrange(2**32)
    elif isinstance(seed_value, bool) or not isinstance(seed_value, int):
        raise ValidationError("pair_selection.random_seed は整数または null")
    else:
        seed = seed_value
    rng = random.Random(seed)

    prompts = {p.index: p for p in load_prompts(collection_dir)}
    candidates = collect_candidates(collection_dir)
    log_path = collection_dir / str(pair_cfg.get("selection_log_path") or _DEFAULT_SELECTION_LOG)
    stock_cfg = cfg.get("stock") if isinstance(cfg.get("stock"), dict) else {}

    grouped: dict[int, list[Candidate]] = {}
    dropped: list[Candidate] = []
    stocked: list[Path] = []
    deleted: list[Path] = []
    kept: list[Path] = []
    winners: list[Candidate] = []
    mode_counts = {"vocal": 0, "instrumental": 0}

    for candidate in candidates:
        if candidate.prompt_index not in prompts:
            raise ValidationError(f"prompts に存在しない track index の音源です: {candidate.path.name}")
        if _is_duration_out_of_range(candidate, min_song_sec=min_sec, max_song_sec=max_sec):
            dropped.append(candidate)
            if out_of_range_action == "stock":
                stocked.append(_move_to_stock(candidate, collection_dir, stock_cfg, dry_run=dry_run))
            elif dry_run:
                deleted.append(candidate.path)
            else:
                candidate.path.unlink()
                deleted.append(candidate.path)
            continue
        grouped.setdefault(candidate.prompt_index, []).append(candidate)

    for prompt_index in sorted(grouped):
        prompt = prompts[prompt_index]
        group = sorted(grouped[prompt_index], key=lambda c: c.path.name)
        if prompt.has_lyrics:
            mode_counts["vocal"] += 1
            winner = rng.choice(group)
            winners.append(winner)
            kept.append(_rename_winner(winner, dry_run=dry_run))
            for loser in group:
                if loser == winner:
                    continue
                stocked.append(_move_to_stock(loser, collection_dir, stock_cfg, dry_run=dry_run))
        else:
            mode_counts["instrumental"] += 1
            kept.extend(candidate.path for candidate in group)

    missing_after_filter = [p.index for p in prompts.values() if p.index not in grouped]
    if missing_after_filter:
        raise ValidationError(
            "尺フィルタ後に採用候補が 0 件になった prompt があります: "
            + ", ".join(f"{i:02d}" for i in missing_after_filter)
        )

    _write_log(
        collection_dir=collection_dir,
        log_path=log_path,
        seed=seed,
        kept=kept,
        stocked=stocked,
        deleted=deleted,
        dropped=dropped,
        winners=winners,
        mode_counts=mode_counts,
        dry_run=dry_run,
    )
    return SelectionResult(kept, stocked, deleted, dropped, winners, mode_counts, log_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Suno clips を歌詞-aware に選別し、尺外音源を除外する")
    parser.add_argument("collection", nargs="?", help="コレクションディレクトリ (省略時は CWD)")
    parser.add_argument("--dry-run", action="store_true", help="ファイル移動せず plan と log を stdout 表示")
    args = parser.parse_args()

    try:
        collection_dir = resolve_collection_dir(args.collection)
        cfg = load_skill_config("masterup")
        result = select_suno_tracks(collection_dir, cfg, dry_run=args.dry_run)
    except (ValidationError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(
        "[yt-suno-select-tracks] "
        f"kept={len(result.kept)} stocked={len(result.stocked)} "
        f"deleted={len(result.deleted)} dropped_duration={len(result.dropped)} "
        f"log={result.log_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
