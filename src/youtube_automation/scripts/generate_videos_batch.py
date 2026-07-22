#!/usr/bin/env python3
"""マスター音源確定済み・未動画化の collection を並列動画化する。"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from youtube_automation.configuration import channel_dir
from youtube_automation.utils.collection_paths import CollectionPaths
from youtube_automation.utils.cost_tracker import _file_lock
from youtube_automation.utils.exceptions import ConfigError, ValidationError
from youtube_automation.utils.skill_config import load_channel_override

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
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"workflow-state.json を読めません: {path}: {exc}") from exc
    if not isinstance(state, dict):
        raise ValidationError(f"workflow-state.json の root は object である必要があります: {path}")
    return state


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

    config = load_channel_override("videoup") if skill_config is None else skill_config
    batch = config.get("batch")
    if batch is not None and not isinstance(batch, Mapping):
        raise ConfigError("config/skills/videoup.yaml::batch は object で指定してください")
    config_value = batch.get("max_workers") if isinstance(batch, Mapping) else None
    if config_value is not None:
        return _positive_int(config_value, "config/skills/videoup.yaml::batch.max_workers")

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


def _write_state_atomic(path: Path, state: dict) -> None:
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".workflow-state.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(state, file, ensure_ascii=False, indent=2)
            file.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _update_workflow_state(collection: Path) -> str:
    paths = CollectionPaths(collection)
    video = paths.find_master_video()
    if video is None:
        raise ValidationError(f"生成成功後も 01-master/*.mp4 が見つかりません: {collection}")
    with _file_lock(paths.workflow_state_path):
        state = _read_state(paths.workflow_state_path)
        assets = state.get("assets")
        if not isinstance(assets, dict):
            raise ValidationError(f"workflow-state.json::assets は object である必要があります: {collection}")
        assets["master_video"] = video.name
        state["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        _write_state_atomic(paths.workflow_state_path, state)
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
    script = root / ".claude" / "skills" / "videoup" / "references" / "generate_videos.sh"
    if not script.is_file():
        raise ValidationError(f"generate_videos.sh が見つかりません: {script}")
    return script


def main() -> int:
    parser = argparse.ArgumentParser(description="マスター済み・未動画化の collection を並列動画化")
    parser.add_argument("--include-live", action="store_true", help="collections/live/ も検出対象に含める")
    parser.add_argument("--max-workers", type=int, help="最大並列数")
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
    except (ConfigError, ValidationError) as exc:
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
