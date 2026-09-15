"""Record Suno provenance and generate a Content ID dispute draft."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.core.adapters.media import probe_duration
from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.collections.paths import CollectionPaths, resolve_collection_dir
from youtube_automation.domains.suno.downloaded.archive import list_audio_files

_FILENAME = "suno-content-id-evidence.json"
_PROMPTS_FILENAME = "suno-prompts.json"


def _format_start_time(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def _evidence_path(collection: Path) -> Path:
    """Resolve the evidence file inside an existing collection (fail loud otherwise)."""
    paths = CollectionPaths(collection)
    if not paths.root.is_dir():
        raise ValidationError(f"コレクションディレクトリが見つかりません: {paths.root}")
    return paths.docs_dir / _FILENAME


def _validate_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.netloc != "suno.com" or not parsed.path.startswith("/song/"):
        raise ValidationError("clip URL は https://suno.com/song/<id> の形式で指定してください")
    return value


def _load(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValidationError(f"{path} は JSON 配列である必要があります")
    if not all(isinstance(item, dict) for item in value):
        raise ValidationError(f"{path} の各要素は JSON オブジェクトである必要があります")
    return value


def _normalize_generated_at(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError("generated-at は ISO 8601 形式で指定してください") from exc
    if parsed.tzinfo is None:
        raise ValidationError("generated-at はタイムゾーン付き ISO 8601 形式で指定してください")
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def record(
    collection: Path,
    *,
    track: str,
    url: str,
    generated_at: str,
    model: str,
    plan: str,
    start_time: str = "00:00",
) -> Path:
    """Append or replace one track's generation evidence."""
    path = _evidence_path(collection)
    entries = [item for item in _load(path) if item.get("track") != track]
    entries.append(
        {
            "track": track,
            "clip_url": _validate_url(url),
            "generated_at": _normalize_generated_at(generated_at),
            "model": model,
            "plan": plan,
            "start_time": start_time,
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def record_downloaded_evidence(
    collection: Path,
    *,
    clip_ids: tuple[str, ...],
    generated_at: str,
    studio_ordered_tracks: tuple[str, ...],
) -> Path:
    """Record provenance automatically at the successful archive-placement boundary."""
    prompts_path = CollectionPaths(collection).docs_dir / _PROMPTS_FILENAME
    prompts = json.loads(prompts_path.read_text(encoding="utf-8"))
    model = prompts.get("model") if isinstance(prompts, dict) else None
    if not isinstance(model, str) or not model:
        raise ValidationError(f"Suno の使用モデルが生成 prompt に記録されていません: {prompts_path}")
    # Studio Multitrack export 自体が Premier 専用であり、成功した配置境界が plan の一次証跡になる。
    plan = "Premier"
    music_dir = CollectionPaths(collection).music_dir
    tracks_by_name = {path.name: path for path in list_audio_files(music_dir)}
    # The archive boundary returns canonical filenames in Studio slot order, the exact
    # order in which suno-helper passed clip_ids to requestStudioMultitrackExport.
    tracks = tuple(tracks_by_name[name] for name in studio_ordered_tracks if name in tracks_by_name)
    # archive apply replaces the entire music directory transactionally, so this list is the
    # current Studio export. Never guess a mapping when placement skipped a member: an incorrect
    # Content ID provenance URL is worse than an explicit missing-evidence warning.
    if len(tracks) != len(clip_ids):
        raise ValidationError(
            f"Content ID 証跡の clip 数と配置済み音源数が一致しません: clips={len(clip_ids)}, tracks={len(tracks)}"
        )
    start_seconds = 0.0
    start_times: dict[str, str] = {}
    for track_path in list_audio_files(music_dir):
        start_times[track_path.name] = _format_start_time(start_seconds)
        duration = probe_duration(track_path)
        if duration is None:
            raise ValidationError(f"音源 duration の取得に失敗しました: {track_path}")
        start_seconds += duration
    path = _evidence_path(collection)
    track_names = {track.name for track in tracks}
    entries = [item for item in _load(path) if item.get("track") not in track_names]
    for track_path, clip_id in zip(tracks, clip_ids, strict=True):
        entries.append(
            {
                "track": track_path.name,
                "clip_url": _validate_url(f"https://suno.com/song/{clip_id}"),
                "generated_at": _normalize_generated_at(generated_at),
                "model": model,
                "plan": plan,
                "start_time": start_times[track_path.name],
            }
        )
    if not tracks or not clip_ids:
        raise ValidationError("Content ID 証跡へ記録する配置済み音源がありません")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def render_draft(collection: Path, track: str) -> str:
    """Render a paste-ready dispute draft for a recorded track."""
    path = _evidence_path(collection)
    entry = next((item for item in _load(path) if item.get("track") == track), None)
    if entry is None:
        raise ValidationError(f"トラック {track!r} の生成記録がありません: {path}")
    return (
        "この音源は私が Suno で生成したオリジナルコンテンツです。\n"
        f"トラック: {entry['track']}\n動画内の開始位置: {entry['start_time']}\n生成日時: {entry['generated_at']}\n"
        f"生成元: {entry['clip_url']}\nモデル: {entry['model']}\n利用プラン: {entry['plan']}\n\n"
        "上記の生成記録をご確認のうえ、Content ID の申し立てを解除してください。\n\n"
        "注意: 最初の異議申し立てが拒否された後の再審査請求は、著作権ストライクにつながる可能性があります。"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Suno の生成証跡を記録し Content ID 異議申し立て文を作る")
    parser.add_argument("collection", nargs="?", help="コレクションディレクトリ（省略時は CWD）")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("record", help="曲の生成証跡を記録する")
    add.add_argument("--track", required=True, help="トラック名（タイムスタンプの曲名と同じ値）")
    add.add_argument("--url", required=True, help="https://suno.com/song/<id> URL")
    add.add_argument("--generated-at", required=True, help="生成日時（ISO 8601）")
    add.add_argument("--model", required=True, help="Suno モデル名")
    add.add_argument("--plan", required=True, help="生成時の利用プラン（Premier 等）")
    add.add_argument("--start-time", required=True, help="動画トラックリスト上の開始位置（例: 00:00）")
    draft = sub.add_parser("draft", help="異議申し立て文の下書きを表示する")
    draft.add_argument("--track", required=True, help="記録済みトラック名")
    return parser


def run(args: argparse.Namespace) -> int:
    collection = resolve_collection_dir(args.collection)
    if args.command == "record":
        print(
            record(
                collection,
                track=args.track,
                url=args.url,
                generated_at=args.generated_at,
                model=args.model,
                plan=args.plan,
                start_time=args.start_time,
            )
        )
    else:
        print(render_draft(collection, args.track))
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_cli(
        build_parser,
        run,
        argv,
        failure_message="Content ID 生成証跡の処理に失敗しました",
        handled_errors=(OSError, json.JSONDecodeError, ValidationError),
    )


if __name__ == "__main__":
    raise SystemExit(main())
