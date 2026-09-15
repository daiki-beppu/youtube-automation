"""Record Suno provenance and generate a Content ID dispute draft."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.collections.paths import CollectionPaths, resolve_collection_dir

_FILENAME = "suno-content-id-evidence.json"


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
    return value


def record(collection: Path, *, track: str, url: str, generated_at: str, model: str, plan: str) -> Path:
    """Append or replace one track's generation evidence."""
    try:
        datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError("generated-at は ISO 8601 形式で指定してください") from exc
    path = CollectionPaths(collection).docs_dir / _FILENAME
    entries = [item for item in _load(path) if item.get("track") != track]
    entries.append(
        {
            "track": track,
            "clip_url": _validate_url(url),
            "generated_at": generated_at,
            "model": model,
            "plan": plan,
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def render_draft(collection: Path, track: str) -> str:
    """Render a paste-ready dispute draft for a recorded track."""
    path = CollectionPaths(collection).docs_dir / _FILENAME
    entry = next((item for item in _load(path) if item.get("track") == track), None)
    if entry is None:
        raise ValidationError(f"トラック {track!r} の生成記録がありません: {path}")
    return (
        "この音源は私が Suno で生成したオリジナルコンテンツです。\n"
        f"トラック: {entry['track']}\n生成日時: {entry['generated_at']}\n"
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
