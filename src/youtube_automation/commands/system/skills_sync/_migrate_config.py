"""下流 skill-config を統合後の名前空間節へ安全に移行する。"""

from __future__ import annotations

import argparse
import difflib
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Mapping

import yaml

from youtube_automation.core.errors import ConfigError


@dataclass(frozen=True, slots=True)
class SkillConfigMigration:
    """One old config filename and its consolidated destination."""

    target_skill: str
    section: str | None


@dataclass(frozen=True, slots=True)
class MigrationAction:
    """One source file moved into a destination root or section."""

    source: Path
    destination: Path
    section: str | None


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    """Fully validated filesystem changes for one channel."""

    actions: tuple[MigrationAction, ...]
    destinations: Mapping[Path, dict[str, object]]
    orphans: tuple[Path, ...]


# 統合先 skill と名前空間 loader key が成立した段から移行を有効化する。
# apply は利用者の明示実行だけで行い、旧 loader key は互換入口として維持する。
SKILL_CONFIG_MIGRATIONS: Final[Mapping[str, SkillConfigMigration]] = {
    "benchmark": SkillConfigMigration("channel-research", "benchmark"),
    "collection-ideate": SkillConfigMigration("wf-new", None),
    "community-post": SkillConfigMigration("publish", "community"),
    "live-clean": SkillConfigMigration("publish", "clean"),
    "loop-video": SkillConfigMigration("thumbnail", "loop"),
    "lyria": SkillConfigMigration("music", "generate"),
    "masterup": SkillConfigMigration("music", "master"),
    "suno": SkillConfigMigration("music", "prompt"),
    "suno-lyric": SkillConfigMigration("music", "lyric"),
    "metadata-audit": SkillConfigMigration("audit", "metadata"),
    "video-upload": SkillConfigMigration("publish", "upload"),
    "video-description": SkillConfigMigration("video", "describe"),
    "videoup": SkillConfigMigration("video", "generate"),
    "video-analyze": SkillConfigMigration("audit", "video"),
}

_COMPATIBLE_CONFIG_NAMES: Final[frozenset[str]] = frozenset({"postmortem"})


def _load_mapping(path: Path) -> dict[str, object]:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"skill-config 読み込み失敗: {path}: {exc}") from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigError(f"skill-config の root は mapping である必要があります: {path}")
    return loaded


def _dump_mapping(data: Mapping[str, object]) -> str:
    return yaml.safe_dump(dict(data), allow_unicode=True, sort_keys=False)


def _orphan_configs(
    config_dir: Path,
    migrations: Mapping[str, SkillConfigMigration],
) -> tuple[Path, ...]:
    if not config_dir.is_dir():
        return ()
    from youtube_automation.commands.system.skills_sync import bundled_skill_names

    known = set(bundled_skill_names()) | set(migrations) | _COMPATIBLE_CONFIG_NAMES
    known.update(migration.target_skill for migration in migrations.values())
    return tuple(path for path in sorted(config_dir.glob("*.yaml")) if path.is_file() and path.stem not in known)


def build_migration_plan(
    channel_dir: Path,
    migrations: Mapping[str, SkillConfigMigration],
) -> MigrationPlan:
    """Read and validate every migration before creating any temporary file."""
    if not channel_dir.is_dir():
        raise ConfigError(f"channel directory が存在しません: {channel_dir}")
    config_dir = channel_dir / "config" / "skills"
    actions: list[MigrationAction] = []
    destinations: dict[Path, dict[str, object]] = {}

    for source_name, migration in sorted(migrations.items()):
        source = config_dir / f"{source_name}.yaml"
        if not source.is_file():
            continue
        destination = config_dir / f"{migration.target_skill}.yaml"
        if destination == source:
            raise ConfigError(f"移行元と移行先が同じです: {source}")

        source_data = _load_mapping(source)
        if destination not in destinations:
            destinations[destination] = _load_mapping(destination) if destination.is_file() else {}
        destination_data = destinations[destination]
        if migration.section is None:
            if destination_data and destination_data != source_data:
                raise ConfigError(f"移行先に既存内容があります: {destination} (既存内容を上書きしません)")
            destinations[destination] = source_data
            actions.append(MigrationAction(source, destination, migration.section))
            continue
        existing = destination_data.get(migration.section)
        if migration.section in destination_data and existing != source_data:
            raise ConfigError(
                f"移行先の節が既存内容と衝突しています: {destination}::{migration.section} (既存内容を上書きしません)"
            )
        destination_data[migration.section] = source_data
        actions.append(MigrationAction(source, destination, migration.section))

    return MigrationPlan(
        actions=tuple(actions),
        destinations=destinations,
        orphans=_orphan_configs(config_dir, migrations),
    )


def _stage_mapping(destination: Path, data: Mapping[str, object]) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(_dump_mapping(data))
            stream.flush()
            os.fsync(stream.fileno())
        if _load_mapping(temporary) != data:
            raise ConfigError(f"一時ファイルの検証に失敗しました: {temporary}")
    except (ConfigError, OSError):
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def _restore_files(originals: Mapping[Path, bytes | None]) -> None:
    for path, payload in originals.items():
        if payload is None:
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)


def apply_migration_plan(plan: MigrationPlan) -> None:
    """Stage all writes, then replace destinations and delete sources as one transaction."""
    staged: dict[Path, Path] = {}
    affected = {*plan.destinations, *(action.source for action in plan.actions)}
    originals: dict[Path, bytes | None] = {}
    try:
        originals = {path: path.read_bytes() if path.is_file() else None for path in affected}
        for destination, data in plan.destinations.items():
            staged[destination] = _stage_mapping(destination, data)
        for destination, temporary in staged.items():
            os.replace(temporary, destination)
        for action in plan.actions:
            action.source.unlink()
    except (ConfigError, OSError) as exc:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)
        try:
            _restore_files(originals)
        except OSError as restore_exc:
            raise ConfigError(f"skill-config 移行に失敗し、復元にも失敗しました: {restore_exc}") from exc
        raise ConfigError(f"skill-config 移行に失敗しました。既存ファイルを復元しました: {exc}") from exc


def _print_plan(channel_dir: Path, plan: MigrationPlan, *, dry_run: bool) -> None:
    prefix = "[dry-run] " if dry_run else ""
    for action in plan.actions:
        section_suffix = f"::{action.section}" if action.section is not None else ""
        print(f"{prefix}{action.source.name} -> {action.destination.name}{section_suffix}")
    if dry_run:
        for destination, data in plan.destinations.items():
            before = destination.read_text(encoding="utf-8").splitlines(keepends=True) if destination.is_file() else []
            after = _dump_mapping(data).splitlines(keepends=True)
            print(
                "".join(
                    difflib.unified_diff(
                        before,
                        after,
                        fromfile=f"{destination.relative_to(channel_dir)} (before)",
                        tofile=f"{destination.relative_to(channel_dir)} (after)",
                    )
                ),
                end="",
            )
    for orphan in plan.orphans:
        print(f"[warn] 孤児 skill-config: {orphan.name}（移行せず保持）")


def cmd_migrate_config(args: argparse.Namespace) -> int:
    """`yt-skills migrate-config` — downstream override を明示適用で移行する。"""
    try:
        plan = build_migration_plan(args.channel_dir, SKILL_CONFIG_MIGRATIONS)
        _print_plan(args.channel_dir, plan, dry_run=args.dry_run)
        if not plan.actions:
            print("移行対象はありません")
            return 0
        if args.dry_run:
            print(f"dry-run 完了: {len(plan.actions)} ファイル（変更なし）")
            return 0
        apply_migration_plan(plan)
    except (ConfigError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"移行完了: {len(plan.actions)} ファイル")
    return 0
