#!/usr/bin/env python3
"""マスター音源確定済み・未動画化の collection を並列動画化する。"""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from youtube_automation.application.master_video_review import approve_generated_master_video
from youtube_automation.configuration import channel_dir
from youtube_automation.configuration.skills import load_channel_override
from youtube_automation.core.errors import (
    ConfigError,
    ReviewError,
    ValidationError,
    WorkflowStateError,
    WorkflowStateSectionTypeError,
)
from youtube_automation.domains.collections.workflow_state import WorkflowState
from youtube_automation.domains.collections.workflow_state import read as read_workflow_state
from youtube_automation.domains.collections.workflow_state import update as update_workflow_state
from youtube_automation.infrastructure.media.collection_paths import CollectionPaths

DEFAULT_MAX_WORKERS = 3
MAX_WORKERS_ENV = "YT_VIDEOUP_MAX_WORKERS"


@dataclass(frozen=True)
class BatchResult:
    """1 collection の動画生成結果。"""

    collection: Path
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0


def _read_state(path: Path) -> dict:
    try:
        return read_workflow_state(path).to_dict()
    except WorkflowStateError as error:
        if "root must be an object" in str(error):
            raise ValidationError(f"workflow-state.json の root は object である必要があります: {path}") from error
        raise ValidationError(f"workflow-state.json を読めません: {path}: {error}") from error


def _is_batch_target(collection: Path) -> bool:
    state_path = collection / "workflow-state.json"
    if not state_path.is_file():
        return False
    try:
        state = _read_state(state_path)
    except ValidationError:
        return False
    assets = state.get("assets")
    if not isinstance(assets, dict):
        return False
    master_audio = assets.get("master_audio")
    return isinstance(master_audio, str) and bool(master_audio.strip()) and assets.get("master_video") is None


def find_batch_targets(channel_root: Path | str | None = None, *, include_live: bool = False) -> list[Path]:
    """v2 state でマスター音源確定済み・未動画化の collection を返す。"""

    root = Path(channel_dir() if channel_root is None else channel_root).resolve()
    stages = ["planning", "live"] if include_live else ["planning"]
    targets: list[Path] = []
    for stage in stages:
        stage_root = root / "collections" / stage
        if not stage_root.is_dir():
            continue
        targets.extend(
            collection.resolve()
            for collection in sorted(path for path in stage_root.iterdir() if path.is_dir())
            if _is_batch_target(collection)
        )
    return targets


def _positive_int(value: object, source: str) -> int:
    if isinstance(value, bool):
        raise ConfigError(f"{source} は 1 以上の整数で指定してください")
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{source} は 1 以上の整数で指定してください: {value!r}") from exc
    if parsed < 1 or str(value).strip() != str(parsed):
        raise ConfigError(f"{source} は 1 以上の整数で指定してください: {value!r}")
    return parsed


def resolve_max_workers(
    cli_value: int | None,
    *,
    environ: Mapping[str, str] | None = None,
    skill_config: Mapping[str, object] | None = None,
    detected_cpu_count: int | None = None,
) -> int:
    """CLI > env > channel skill-config > CPU 検出 > 3 で並列度を解決する。"""

    if cli_value is not None:
        return _positive_int(cli_value, "--max-workers")

    env = os.environ if environ is None else environ
    env_value = env.get(MAX_WORKERS_ENV)
    if env_value is not None:
        return _positive_int(env_value, MAX_WORKERS_ENV)

    config = load_channel_override("video") if skill_config is None else skill_config
    config = config.get("generate", {}) if skill_config is None else config
    batch = config.get("batch")
    if batch is not None and not isinstance(batch, Mapping):
        raise ConfigError("config/skills/video.yaml::generate.batch は object で指定してください")
    config_value = batch.get("max_workers") if isinstance(batch, Mapping) else None
    if config_value is not None:
        return _positive_int(config_value, "config/skills/video.yaml::generate.batch.max_workers")

    cpu_count = os.cpu_count() if detected_cpu_count is None else detected_cpu_count
    if isinstance(cpu_count, int) and cpu_count > 0:
        return cpu_count
    return DEFAULT_MAX_WORKERS


def _run_collection(collection: Path, script_path: Path) -> BatchResult:
    try:
        completed = subprocess.run(
            ["bash", str(script_path), str(collection)],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return BatchResult(collection=collection, returncode=127, stderr=str(exc))
    return BatchResult(
        collection=collection,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def run_batch_parallel(
    targets: Sequence[Path | str],
    *,
    max_workers: int,
    script_path: Path | str | None = None,
) -> list[BatchResult]:
    """既存 generate_videos.sh を collection 単位で並列実行する。"""

    collections = [Path(target).resolve() for target in targets]
    if not collections:
        return []
    workers = min(_positive_int(max_workers, "max_workers"), len(collections))
    results: list[BatchResult | None] = [None] * len(collections)
    script = _script_path(Path(channel_dir()).resolve()) if script_path is None else Path(script_path).resolve()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_index = {
            executor.submit(_run_collection, collection, script): index for index, collection in enumerate(collections)
        }
        for future in concurrent.futures.as_completed(future_to_index):
            results[future_to_index[future]] = future.result()
    return [result for result in results if result is not None]


def _update_workflow_state(collection: Path) -> str:
    paths = CollectionPaths(collection)
    video = paths.find_master_video()
    if video is None:
        raise ValidationError(f"生成成功後も 01-master/*.mp4 が見つかりません: {collection}")

    def record_master_video(state: WorkflowState) -> None:
        approve_generated_master_video(state, video)

    try:
        update_workflow_state(paths.workflow_state_path, record_master_video)
    except ReviewError as error:
        raise ValidationError(f"生成された master video を読み込めません: {video}: {error}") from error
    except WorkflowStateError as error:
        if isinstance(error.__cause__, OSError) and "could not be written" in str(error):
            raise error.__cause__ from error
        if isinstance(error, WorkflowStateSectionTypeError) and error.section == "assets":
            raise ValidationError(
                f"workflow-state.json::assets は object である必要があります: {collection}"
            ) from error
        raise ValidationError(f"workflow-state.json を読めません: {paths.workflow_state_path}: {error}") from error
    return video.name


def update_workflow_states(results: Sequence[BatchResult | Path | str]) -> dict[Path, str]:
    """成功した collection の master_video をファイルロック下で直列記録する。"""

    updated: dict[Path, str] = {}
    for result in results:
        if isinstance(result, BatchResult):
            if not result.succeeded:
                continue
            collection = result.collection
        else:
            collection = Path(result).resolve()
        updated[collection] = _update_workflow_state(collection)
    return updated


def _script_path(root: Path) -> Path:
    script = root / ".claude" / "skills" / "video" / "references" / "generate_videos.sh"
    if not script.is_file():
        raise ValidationError(f"generate_videos.sh が見つかりません: {script}")
    return script


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "assets.master_audio が設定済みかつ assets.master_video: null の collection を並列動画化。"
            "既定では collections/planning/ のみを対象にし、--include-live で collections/live/ も含める。"
            "成功した collection のみ assets.master_video を更新し、部分失敗は non-zero で終了"
        )
    )
    parser.add_argument(
        "--include-live",
        action="store_true",
        help="既定の collections/planning/ に加えて collections/live/ も検出対象に含める",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        help=(
            "最大並列数（1 以上）。未指定時は CLI > YT_VIDEOUP_MAX_WORKERS > channel skill-config > "
            "CPU 検出 > 3 の優先順で解決。channel skill-config は "
            "config/skills/video.yaml::generate.batch.max_workers"
        ),
    )
    args = parser.parse_args()

    root = Path(channel_dir()).resolve()
    try:
        targets = find_batch_targets(root, include_live=args.include_live)
        if not targets:
            print("動画化対象の collection はありません。")
            return 0
        max_workers = resolve_max_workers(args.max_workers)
        print(f"対象: {len(targets)} collection / 最大並列数: {min(max_workers, len(targets))}")
        results = run_batch_parallel(targets, max_workers=max_workers, script_path=_script_path(root))
        updated = update_workflow_states(results)
    except (ConfigError, ValidationError, OSError) as exc:
        print(f"ERROR: {exc}")
        return 1

    failed = [result for result in results if not result.succeeded]
    for result in results:
        if result.succeeded:
            print(f"SUCCESS {result.collection.name}: {updated[result.collection]}")
        else:
            detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
            print(f"FAILED  {result.collection.name}: {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
