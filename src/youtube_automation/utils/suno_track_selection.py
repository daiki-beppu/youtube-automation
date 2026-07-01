#!/usr/bin/env python3
"""Select Suno downloaded clips before masterup.

Suno generates two clips per prompt. For vocal prompts, keep one winner per
prompt and move the other clips to stock. For instrumental prompts, keep both
clips. In both modes, filter obviously broken durations before selection.
"""

from __future__ import annotations

import json
import os
import random
import re
import shutil
import string
import tempfile
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from youtube_automation.utils.collection_paths import CollectionPaths
from youtube_automation.utils.exceptions import ValidationError
from youtube_automation.utils.probe import probe_duration
from youtube_automation.utils.suno_artifact_contracts import DOCUMENTATION_DIRNAME, SUNO_PROMPTS_JSON_FILENAME

_AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav"}
_DOWNLOADED_NAME_RE = re.compile(r"^(?P<idx>\d{2,})(?P<variant>[a-z])?-(?P<title>.+)$", re.IGNORECASE)
_BRACKET_LINE_RE = re.compile(r"^\s*\[[^\]]+\]\s*$")
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_DEFAULT_SELECTION_LOG = "01-master/.selection.log"
_DEFAULT_STOCK_DIR = "assets/stock/music/b-side"
_DEFAULT_FILENAME_TEMPLATE = "{collection_slug}__{song_id}__{title_slug}.{ext}"
_STOCK_TEMPLATE_FIELDS = {"collection_slug", "song_id", "title_slug", "ext"}


@dataclass(frozen=True)
class PromptEntry:
    index: int
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


@dataclass(frozen=True)
class OverLimitException:
    candidate: Candidate
    max_song_sec: float
    reason: str


@dataclass(frozen=True)
class PairSelectionConfig:
    mode: str
    min_song_sec: float | None
    max_song_sec: float | None
    out_of_range_action: str
    strategy: str
    random_seed: int | None
    selection_log_path: Path


@dataclass(frozen=True)
class StockConfig:
    dir: Path
    filename_template: str
    on_duplicate: str


@dataclass(frozen=True)
class SelectionConfig:
    pair: PairSelectionConfig
    stock: StockConfig


@dataclass(frozen=True)
class SelectionPlan:
    seed: int
    log_path: Path
    kept: list[Path]
    stocked: list[tuple[Candidate, Path]]
    deleted: list[Candidate]
    dropped: list[Candidate]
    winners: list[Candidate]
    renames: list[tuple[Candidate, Path]]
    exceptions_over_limit: list[OverLimitException]
    mode_counts: dict[str, int]


@dataclass
class SelectionResult:
    kept: list[Path]
    stocked: list[Path]
    deleted: list[Path]
    dropped: list[Candidate]
    winners: list[Candidate]
    exceptions_over_limit: list[OverLimitException]
    mode_counts: dict[str, int]
    log_path: Path


@dataclass(frozen=True)
class WorkflowStateSnapshot:
    path: Path
    data: dict[str, object]


@dataclass(frozen=True)
class FileSnapshot:
    path: Path
    existed: bool
    content: bytes | None


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValidationError(f"{label} must be a mapping")
    return value


def _optional_mapping(value: object, label: str) -> Mapping[str, object]:
    if value is None:
        return {}
    return _require_mapping(value, label)


def _string_value(value: object, default: str, label: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValidationError(f"{label} must be a string")
    return value


def _number_or_none(value: object, default: float | None, label: str) -> float | None:
    if value is None:
        return None
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValidationError(f"{label} must be a number or null")
    return float(value)


def _relative_path_value(value: object, default: str, label: str) -> Path:
    raw = _string_value(value, default, label)
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValidationError(f"{label} must be a relative path without '..': {raw}")
    return path


def _resolve_inside(base: Path, relative_path: Path, label: str) -> Path:
    base_resolved = base.resolve()
    resolved = (base_resolved / relative_path).resolve()
    if not resolved.is_relative_to(base_resolved):
        raise ValidationError(f"{label} must stay under {base_resolved}: {relative_path}")
    return resolved


def _collection_root(collection_dir: Path) -> Path:
    for parent in collection_dir.parents:
        if parent.name == "collections":
            return parent.parent
    return collection_dir.parent


def _stock_root(collection_dir: Path) -> Path:
    return _collection_root(collection_dir).resolve() / "assets" / "stock"


class _Missing:
    pass


_MISSING = _Missing()


def _parse_pair_config(cfg: Mapping[str, object], collection_dir: Path) -> PairSelectionConfig:
    raw = _optional_mapping(cfg.get("pair_selection"), "pair_selection")
    mode = _string_value(raw.get("mode"), "auto", "pair_selection.mode")
    if mode not in {"auto", "never"}:
        raise ValidationError(f"pair_selection.mode は auto / never のいずれかです: {mode}")

    min_song_sec = _number_or_none(raw.get("min_song_sec", _MISSING), 45, "pair_selection.min_song_sec")
    max_song_sec = _number_or_none(raw.get("max_song_sec", _MISSING), 300, "pair_selection.max_song_sec")
    if min_song_sec is not None and min_song_sec < 0:
        raise ValidationError("pair_selection.min_song_sec は 0 以上または null")
    if max_song_sec is not None and max_song_sec <= 0:
        raise ValidationError("pair_selection.max_song_sec は 0 より大きい値または null")
    if min_song_sec is not None and max_song_sec is not None and min_song_sec >= max_song_sec:
        raise ValidationError("pair_selection.min_song_sec は max_song_sec 未満にしてください")

    out_of_range_action = _string_value(raw.get("out_of_range_action"), "stock", "pair_selection.out_of_range_action")
    if out_of_range_action not in {"stock", "delete"}:
        raise ValidationError("pair_selection.out_of_range_action は stock / delete のいずれかです")

    strategy = _string_value(raw.get("strategy"), "random", "pair_selection.strategy")
    if strategy != "random":
        raise ValidationError(f"pair_selection.strategy は現在 random のみ対応: {strategy}")

    seed_value = raw.get("random_seed")
    if seed_value is None:
        random_seed = None
    elif isinstance(seed_value, bool) or not isinstance(seed_value, int):
        raise ValidationError("pair_selection.random_seed は整数または null")
    else:
        random_seed = seed_value

    selection_log_rel = _relative_path_value(
        raw.get("selection_log_path"), _DEFAULT_SELECTION_LOG, "pair_selection.selection_log_path"
    )
    selection_log_path = _resolve_inside(collection_dir, selection_log_rel, "pair_selection.selection_log_path")
    return PairSelectionConfig(
        mode=mode,
        min_song_sec=min_song_sec,
        max_song_sec=max_song_sec,
        out_of_range_action=out_of_range_action,
        strategy=strategy,
        random_seed=random_seed,
        selection_log_path=selection_log_path,
    )


def _validate_template(template: str) -> None:
    formatter = string.Formatter()
    try:
        fields = [field_name for _, field_name, _, _ in formatter.parse(template) if field_name is not None]
    except ValueError as exc:
        raise ValidationError(f"stock.filename_template is invalid: {exc}") from exc
    invalid = sorted(field for field in fields if field not in _STOCK_TEMPLATE_FIELDS)
    if invalid:
        raise ValidationError("stock.filename_template contains unsupported placeholder: " + ", ".join(invalid))


def _parse_stock_config(cfg: Mapping[str, object], collection_dir: Path) -> StockConfig:
    raw = _optional_mapping(cfg.get("stock"), "stock")
    stock_dir_rel = _relative_path_value(raw.get("dir"), _DEFAULT_STOCK_DIR, "stock.dir")
    stock_dir = (_collection_root(collection_dir).resolve() / stock_dir_rel).resolve()
    root = _stock_root(collection_dir)
    if not stock_dir.is_relative_to(root):
        raise ValidationError(f"stock.dir must stay under {root}: {stock_dir_rel}")

    filename_template = _string_value(
        raw.get("filename_template"), _DEFAULT_FILENAME_TEMPLATE, "stock.filename_template"
    )
    _validate_template(filename_template)
    on_duplicate = _string_value(raw.get("on_duplicate"), "skip", "stock.on_duplicate")
    if on_duplicate not in {"skip", "overwrite", "fail"}:
        raise ValidationError("stock.on_duplicate は skip / overwrite / fail のいずれかです")
    return StockConfig(dir=stock_dir, filename_template=filename_template, on_duplicate=on_duplicate)


def parse_selection_config(cfg: Mapping[str, object], collection_dir: Path) -> SelectionConfig:
    return SelectionConfig(
        pair=_parse_pair_config(cfg, collection_dir),
        stock=_parse_stock_config(cfg, collection_dir),
    )


def _has_substantive_lyrics(value: object) -> bool:
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
    data: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValidationError(f"{SUNO_PROMPTS_JSON_FILENAME} root must be a list")
    prompts: list[PromptEntry] = []
    for i, entry in enumerate(data, 1):
        if not isinstance(entry, Mapping):
            raise ValidationError(f"{SUNO_PROMPTS_JSON_FILENAME}: entry {i} must be an object")
        prompts.append(
            PromptEntry(
                index=i,
                has_lyrics=_has_substantive_lyrics(entry.get("lyrics")),
            )
        )
    return prompts


def _slugify(value: str) -> str:
    slug = _SLUG_RE.sub("-", value.lower()).strip("-")
    return slug or "untitled"


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
    invalid_audio: list[str] = []
    for path in sorted(music_dir.iterdir(), key=lambda p: p.name):
        if not path.is_file():
            continue
        parsed = _parse_candidate(path)
        if parsed is None:
            if path.suffix.lower() in _AUDIO_EXTENSIONS:
                invalid_audio.append(path.name)
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
    if invalid_audio:
        raise ValidationError("命名規則に合わない音源があります: " + ", ".join(invalid_audio))
    if not candidates:
        raise ValidationError(f"選別対象の音源が見つかりません: {music_dir}")
    return candidates


def _validate_download_complete(prompts: Mapping[int, PromptEntry], candidates: list[Candidate]) -> None:
    counts = {prompt_index: 0 for prompt_index in prompts}
    for candidate in candidates:
        if candidate.prompt_index in counts:
            counts[candidate.prompt_index] += 1
    missing = [prompt_index for prompt_index, count in counts.items() if count < 2]
    if missing:
        details = ", ".join(f"{prompt_index:02d}={counts[prompt_index]}/2" for prompt_index in missing)
        raise ValidationError(f"Suno download が完了していません。prompt ごとに 2 clip 必要です: {details}")


def _is_duration_out_of_range(candidate: Candidate, *, min_song_sec: float | None, max_song_sec: float | None) -> bool:
    if min_song_sec is not None and candidate.duration < min_song_sec:
        return True
    if max_song_sec is not None and candidate.duration > max_song_sec:
        return True
    return False


def _is_over_max_only(candidate: Candidate, *, min_song_sec: float | None, max_song_sec: float | None) -> bool:
    if max_song_sec is None or candidate.duration <= max_song_sec:
        return False
    if min_song_sec is not None and candidate.duration < min_song_sec:
        return False
    return True


def _stock_name(candidate: Candidate, collection_dir: Path, stock_cfg: StockConfig) -> str:
    try:
        name = stock_cfg.filename_template.format(
            collection_slug=collection_dir.name,
            song_id=_slugify(candidate.song_id),
            title_slug=_slugify(candidate.title),
            ext=candidate.ext,
        )
    except (KeyError, ValueError) as exc:
        raise ValidationError(f"stock.filename_template is invalid: {exc}") from exc
    if not name or name in {".", ".."}:
        raise ValidationError("stock.filename_template produced an invalid filename")
    if "/" in name or "\\" in name or Path(name).is_absolute() or ".." in Path(name).parts:
        raise ValidationError(f"stock.filename_template must produce a basename only: {name}")
    return name


def _stock_destination(candidate: Candidate, collection_dir: Path, stock_cfg: StockConfig) -> Path:
    return stock_cfg.dir / _stock_name(candidate, collection_dir, stock_cfg)


def _winner_destination(candidate: Candidate) -> Path:
    return candidate.path.with_name(f"{candidate.prompt_index:02d}-{candidate.title}{candidate.path.suffix.lower()}")


def _plan_suno_selection(
    *,
    collection_dir: Path,
    prompts: Mapping[int, PromptEntry],
    candidates: list[Candidate],
    cfg: SelectionConfig,
    allow_best_effort_over_max: bool,
) -> SelectionPlan:
    seed = cfg.pair.random_seed if cfg.pair.random_seed is not None else random.SystemRandom().randrange(2**32)
    rng = random.Random(seed)
    grouped: dict[int, list[Candidate]] = {}
    dropped: list[Candidate] = []
    stocked: list[tuple[Candidate, Path]] = []
    deleted: list[Candidate] = []
    kept: list[Path] = []
    winners: list[Candidate] = []
    renames: list[tuple[Candidate, Path]] = []
    exceptions_over_limit: list[OverLimitException] = []
    mode_counts = {"vocal": 0, "instrumental": 0}

    for candidate in candidates:
        if candidate.prompt_index not in prompts:
            raise ValidationError(f"prompts に存在しない track index の音源です: {candidate.path.name}")
        if _is_duration_out_of_range(
            candidate,
            min_song_sec=cfg.pair.min_song_sec,
            max_song_sec=cfg.pair.max_song_sec,
        ):
            dropped.append(candidate)
            if cfg.pair.out_of_range_action == "stock":
                stocked.append((candidate, _stock_destination(candidate, collection_dir, cfg.stock)))
            else:
                deleted.append(candidate)
            continue
        grouped.setdefault(candidate.prompt_index, []).append(candidate)

    missing_after_filter = [p.index for p in prompts.values() if p.index not in grouped]
    if missing_after_filter and allow_best_effort_over_max:
        dropped_by_prompt: dict[int, list[Candidate]] = {}
        for candidate in dropped:
            dropped_by_prompt.setdefault(candidate.prompt_index, []).append(candidate)

        still_missing: list[int] = []
        for prompt_index in missing_after_filter:
            prompt_dropped = dropped_by_prompt.get(prompt_index, [])
            all_dropped_are_over_max_only = bool(prompt_dropped) and all(
                _is_over_max_only(
                    candidate,
                    min_song_sec=cfg.pair.min_song_sec,
                    max_song_sec=cfg.pair.max_song_sec,
                )
                for candidate in prompt_dropped
            )
            if not all_dropped_are_over_max_only:
                still_missing.append(prompt_index)
                continue
            selected = sorted(prompt_dropped, key=lambda c: (c.duration, c.path.name))[0]
            grouped.setdefault(prompt_index, []).append(selected)
            dropped.remove(selected)
            stocked = [(candidate, dest) for candidate, dest in stocked if candidate != selected]
            deleted = [candidate for candidate in deleted if candidate != selected]
            exceptions_over_limit.append(
                OverLimitException(
                    candidate=selected,
                    max_song_sec=cfg.pair.max_song_sec,
                    reason="all_candidates_over_max_song_sec; selected_shortest_over_limit",
                )
            )
        missing_after_filter = still_missing

    if missing_after_filter:
        raise ValidationError(
            "尺フィルタ後に採用候補が 0 件になった prompt があります: "
            + ", ".join(f"{i:02d}" for i in missing_after_filter)
            + "。5分超など max_song_sec 超過だけが原因なら "
            + "--allow-best-effort-over-max で最短候補を警告付き例外採用できます。"
        )

    for prompt_index in sorted(grouped):
        prompt = prompts[prompt_index]
        group = sorted(grouped[prompt_index], key=lambda c: c.path.name)
        if prompt.has_lyrics:
            mode_counts["vocal"] += 1
            winner = rng.choice(group)
            winner_dest = _winner_destination(winner)
            winners.append(winner)
            kept.append(winner_dest)
            if winner.path != winner_dest:
                renames.append((winner, winner_dest))
            for loser in group:
                if loser == winner:
                    continue
                stocked.append((loser, _stock_destination(loser, collection_dir, cfg.stock)))
        else:
            mode_counts["instrumental"] += 1
            kept.extend(candidate.path for candidate in group)

    _validate_plan_destinations(stocked=stocked, renames=renames, stock_cfg=cfg.stock)
    return SelectionPlan(
        seed=seed,
        log_path=cfg.pair.selection_log_path,
        kept=kept,
        stocked=stocked,
        deleted=deleted,
        dropped=dropped,
        winners=winners,
        renames=renames,
        exceptions_over_limit=exceptions_over_limit,
        mode_counts=mode_counts,
    )


def _validate_plan_destinations(
    *,
    stocked: list[tuple[Candidate, Path]],
    renames: list[tuple[Candidate, Path]],
    stock_cfg: StockConfig,
) -> None:
    moving_sources = {candidate.path.resolve() for candidate, _ in stocked}
    moving_sources.update(candidate.path.resolve() for candidate, _ in renames)
    seen_stock_destinations: dict[Path, Candidate] = {}

    for candidate, dest in stocked:
        dest_resolved = dest.resolve()
        if not dest_resolved.is_relative_to(stock_cfg.dir):
            raise ValidationError(f"stock destination must stay under {stock_cfg.dir}: {dest}")
        if stock_cfg.on_duplicate == "fail" and dest_resolved in seen_stock_destinations:
            first = seen_stock_destinations[dest_resolved]
            raise ValidationError(
                f"duplicate stock destination in selection plan: {first.path.name}, {candidate.path.name} -> {dest}"
            )
        seen_stock_destinations[dest_resolved] = candidate
        if dest.exists() and stock_cfg.on_duplicate == "fail":
            raise ValidationError(f"stock destination already exists: {dest}")

    for candidate, dest in renames:
        if dest.exists() and dest.resolve() != candidate.path.resolve() and dest.resolve() not in moving_sources:
            raise ValidationError(f"winner destination already exists: {dest}")


def _prepare_log_destination(log_path: Path) -> None:
    if log_path.exists() and log_path.is_dir():
        raise ValidationError(f"selection log path is a directory: {log_path}")
    if log_path.parent.exists() and not log_path.parent.is_dir():
        raise ValidationError(f"selection log parent is not a directory: {log_path.parent}")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    probe = log_path.parent / f".{log_path.name}.{uuid.uuid4().hex}.write-test"
    probe.write_text("", encoding="utf-8")
    probe.unlink()


def _backup_path(transaction_dir: Path, source: Path, label: str, index: int) -> Path:
    return transaction_dir / f"{index:03d}-{label}-{source.name}"


def _safe_move(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))


def _restore_missing(source: Path, destination: Path) -> None:
    if source.exists() and not destination.exists():
        _safe_move(source, destination)


def _rollback(
    *,
    stocked_new: list[tuple[Path, Path]],
    stock_overwrites: list[tuple[Path, Path, Path]],
    hidden_sources: list[tuple[Path, Path]],
    renames: list[tuple[Path, Path]],
) -> None:
    for source, destination in reversed(renames):
        _restore_missing(destination, source)
    for source, destination in reversed(stocked_new):
        _restore_missing(destination, source)
    for source, destination, backup in reversed(stock_overwrites):
        _restore_missing(destination, source)
        _restore_missing(backup, destination)
    for source, backup in reversed(hidden_sources):
        _restore_missing(backup, source)


def _snapshot_file(path: Path) -> FileSnapshot:
    if path.is_file():
        return FileSnapshot(path=path, existed=True, content=path.read_bytes())
    return FileSnapshot(path=path, existed=False, content=None)


def _restore_file_snapshot(snapshot: FileSnapshot) -> None:
    if snapshot.existed:
        snapshot.path.parent.mkdir(parents=True, exist_ok=True)
        snapshot.path.write_bytes(snapshot.content or b"")
    elif snapshot.path.exists():
        snapshot.path.unlink()


def _cleanup_transaction_dir(transaction_dir: Path) -> None:
    if transaction_dir.exists():
        shutil.rmtree(transaction_dir)


def _apply_plan(
    *,
    collection_dir: Path,
    plan: SelectionPlan,
    stock_cfg: StockConfig,
) -> SelectionResult:
    _prepare_log_destination(plan.log_path)
    workflow_state = _read_workflow_state(CollectionPaths(collection_dir).workflow_state_path)
    log_snapshot = _snapshot_file(plan.log_path)
    transaction_dir = collection_dir / ".tmp" / f"suno-select-{uuid.uuid4().hex}"
    transaction_dir.mkdir(parents=True, exist_ok=False)
    stocked_paths: list[Path] = []
    deleted_paths: list[Path] = []
    stocked_new: list[tuple[Path, Path]] = []
    stock_overwrites: list[tuple[Path, Path, Path]] = []
    hidden_sources: list[tuple[Path, Path]] = []
    renames_applied: list[tuple[Path, Path]] = []

    try:
        for i, (candidate, dest) in enumerate(plan.stocked):
            if dest.exists():
                if stock_cfg.on_duplicate == "skip":
                    backup = _backup_path(transaction_dir, candidate.path, "skip-source", i)
                    _safe_move(candidate.path, backup)
                    hidden_sources.append((candidate.path, backup))
                    stocked_paths.append(dest)
                    continue
                if stock_cfg.on_duplicate == "overwrite":
                    backup = _backup_path(transaction_dir, dest, "overwrite-dest", i)
                    _safe_move(dest, backup)
                    stock_overwrites.append((candidate.path, dest, backup))
                    _safe_move(candidate.path, dest)
                    stocked_paths.append(dest)
                    continue
                raise ValidationError(f"stock destination already exists: {dest}")
            _safe_move(candidate.path, dest)
            stocked_new.append((candidate.path, dest))
            stocked_paths.append(dest)

        for i, candidate in enumerate(plan.deleted):
            backup = _backup_path(transaction_dir, candidate.path, "delete-source", i)
            _safe_move(candidate.path, backup)
            hidden_sources.append((candidate.path, backup))
            deleted_paths.append(candidate.path)

        kept_paths = list(plan.kept)
        for candidate, dest in plan.renames:
            if candidate.path == dest:
                continue
            candidate.path.rename(dest)
            renames_applied.append((candidate.path, dest))

        result = SelectionResult(
            kept=kept_paths,
            stocked=stocked_paths,
            deleted=deleted_paths,
            dropped=plan.dropped,
            winners=plan.winners,
            exceptions_over_limit=plan.exceptions_over_limit,
            mode_counts=plan.mode_counts,
            log_path=plan.log_path,
        )
        _write_log(
            collection_dir=collection_dir,
            log_path=plan.log_path,
            seed=plan.seed,
            kept=result.kept,
            stocked=result.stocked,
            deleted=result.deleted,
            dropped=result.dropped,
            winners=result.winners,
            exceptions_over_limit=result.exceptions_over_limit,
            mode_counts=result.mode_counts,
            dry_run=False,
        )
        _sync_workflow_state_music_pair_selection(workflow_state, result)
    except Exception:
        _rollback(
            stocked_new=stocked_new,
            stock_overwrites=stock_overwrites,
            hidden_sources=hidden_sources,
            renames=renames_applied,
        )
        _restore_file_snapshot(log_snapshot)
        raise
    finally:
        _cleanup_transaction_dir(transaction_dir)

    return result


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
    exceptions_over_limit: list[OverLimitException],
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
    exception_lines = [
        (
            f"{e.candidate.prompt_index:02d} {e.candidate.variant or '-'} {e.candidate.title} "
            f"duration={e.candidate.duration:.2f}s max_song_sec={e.max_song_sec:.2f}s "
            f"source={e.candidate.path.name} reason={e.reason}"
        )
        for e in exceptions_over_limit
    ]
    lines = [
        f"executed_at={datetime.now(timezone.utc).isoformat()}",
        f"seed={seed}",
        f"dry_run={str(dry_run).lower()}",
        f"vocal_groups={mode_counts.get('vocal', 0)}",
        f"instrumental_groups={mode_counts.get('instrumental', 0)}",
        f"exceptions_over_limit={len(exceptions_over_limit)}",
        "---",
        "[kept]",
        *[str(p.relative_to(collection_dir)) if p.is_relative_to(collection_dir) else str(p) for p in kept],
        "[winners]",
        *winner_lines,
        "[exceptions_over_limit]",
        *exception_lines,
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
    tmp_path = log_path.parent / f".{log_path.name}.{uuid.uuid4().hex}.tmp"
    tmp_path.write_text("\n".join(lines), encoding="utf-8")
    tmp_path.replace(log_path)


def _exception_payload(exception: OverLimitException) -> dict[str, object]:
    candidate = exception.candidate
    return {
        "prompt_index": candidate.prompt_index,
        "variant": candidate.variant or None,
        "title": candidate.title,
        "source": candidate.path.name,
        "duration_sec": round(candidate.duration, 2),
        "max_song_sec": round(exception.max_song_sec, 2),
        "reason": exception.reason,
    }


def _atomic_json_write(target: Path, data: dict) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=".workflow-state-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_name, target)
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def _read_workflow_state(workflow_state_path: Path) -> WorkflowStateSnapshot:
    if workflow_state_path.is_file():
        try:
            data = json.loads(workflow_state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ValidationError(f"workflow-state.json を読み取れませんでした: {workflow_state_path}") from exc
        if not isinstance(data, dict):
            raise ValidationError(f"workflow-state.json の root は object である必要があります: {workflow_state_path}")
        return WorkflowStateSnapshot(path=workflow_state_path, data=data)
    if workflow_state_path.exists():
        raise ValidationError(f"workflow-state.json は file である必要があります: {workflow_state_path}")
    return WorkflowStateSnapshot(path=workflow_state_path, data={})


def _sync_workflow_state_music_pair_selection(snapshot: WorkflowStateSnapshot, result: SelectionResult) -> None:
    data = dict(snapshot.data)
    if result.exceptions_over_limit:
        data["music_pair_selection"] = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "exceptions_over_limit_count": len(result.exceptions_over_limit),
            "exceptions_over_limit": [_exception_payload(exception) for exception in result.exceptions_over_limit],
        }
    else:
        if "music_pair_selection" not in data:
            return
        data.pop("music_pair_selection", None)

    _atomic_json_write(snapshot.path, data)


def select_suno_tracks(
    collection_dir: Path,
    cfg: Mapping[str, object],
    *,
    dry_run: bool = False,
    allow_best_effort_over_max: bool = False,
) -> SelectionResult:
    parsed_cfg = parse_selection_config(cfg, collection_dir)
    if parsed_cfg.pair.mode == "never":
        return SelectionResult([], [], [], [], [], [], {}, parsed_cfg.pair.selection_log_path)

    prompts = {p.index: p for p in load_prompts(collection_dir)}
    candidates = collect_candidates(collection_dir)
    _validate_download_complete(prompts, candidates)
    plan = _plan_suno_selection(
        collection_dir=collection_dir,
        prompts=prompts,
        candidates=candidates,
        cfg=parsed_cfg,
        allow_best_effort_over_max=allow_best_effort_over_max,
    )

    if dry_run:
        result = SelectionResult(
            kept=plan.kept,
            stocked=[dest for _, dest in plan.stocked],
            deleted=[candidate.path for candidate in plan.deleted],
            dropped=plan.dropped,
            winners=plan.winners,
            exceptions_over_limit=plan.exceptions_over_limit,
            mode_counts=plan.mode_counts,
            log_path=plan.log_path,
        )
        _write_log(
            collection_dir=collection_dir,
            log_path=plan.log_path,
            seed=plan.seed,
            kept=result.kept,
            stocked=result.stocked,
            deleted=result.deleted,
            dropped=result.dropped,
            winners=result.winners,
            exceptions_over_limit=result.exceptions_over_limit,
            mode_counts=result.mode_counts,
            dry_run=True,
        )
    else:
        result = _apply_plan(collection_dir=collection_dir, plan=plan, stock_cfg=parsed_cfg.stock)
    return result
